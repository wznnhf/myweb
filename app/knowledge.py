"""408 knowledge cards, official FSRS-6 scheduling and durable draw/review history.

Mutations run under the caller's BEGIN IMMEDIATE transaction. No user database
is opened here; time and randomness can be injected in tests.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import random
import uuid

from fastapi import HTTPException
from fsrs import Card, Rating, Scheduler, State
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

ROOT = Path(__file__).resolve().parent
LEGACY_CATALOG = json.loads((ROOT/'data/knowledge/archive/legacy-record-ids.json').read_text())
CATALOG = json.loads((ROOT/'data/knowledge/memory-cards.json').read_text())
CARDS = {c['id']: c for c in CATALOG['cards']}
ARCHIVED_CARDS = {c['id']: c for c in LEGACY_CATALOG['cards']}
ALL_CARDS = {**ARCHIVED_CARDS, **CARDS}
import knowledge_sessions as sessions
from knowledge_sessions import StoredSession
SUBJECTS = {s['id']: s for s in CATALOG['subjects']}
FieldName = Literal['ds', 'co', 'os', 'net']
SHANGHAI = timezone(timedelta(hours=8))
PARAMETERS = (0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194,
              0.001, 1.8722, 0.1666, 0.796, 1.4835, 0.0614, 0.2629,
              1.6483, 0.6014, 1.8729, 0.5425, 0.0912, 0.0658, 0.1542)
SCHEDULER = Scheduler(parameters=PARAMETERS, desired_retention=0.9,
                      learning_steps=(timedelta(minutes=10),),
                      relearning_steps=(timedelta(minutes=10),), enable_fuzzing=False)
CONFIG = dict(algorithm='FSRS-6', package='fsrs==6.3.2', selection_version=1,
              scheduler=SCHEDULER.to_dict())
RATINGS = ['忘记了', '勉强想起', '记得', '很熟']

SCHEMA = '''
CREATE TABLE IF NOT EXISTS knowledge_states(
 card_id TEXT PRIMARY KEY, fsrs TEXT, revision INTEGER NOT NULL DEFAULT 0,
 seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_draws(
 id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, card_id TEXT NOT NULL,
 field TEXT NOT NULL, mode TEXT NOT NULL, kind TEXT NOT NULL,
 expected_revision INTEGER NOT NULL, created_at TEXT NOT NULL,
 revealed_at TEXT, status TEXT NOT NULL DEFAULT 'pending'
);
DROP INDEX IF EXISTS knowledge_pending_field;
CREATE UNIQUE INDEX IF NOT EXISTS knowledge_pending_card
 ON knowledge_draws(card_id) WHERE status='pending';
UPDATE knowledge_draws SET status='invalidated' WHERE status='pending' AND card_id NOT LIKE 'mc-%';
CREATE TABLE IF NOT EXISTS knowledge_reviews(
 id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, card_id TEXT NOT NULL,
 field TEXT NOT NULL, mode TEXT NOT NULL, rating INTEGER NOT NULL,
 reviewed_at TEXT NOT NULL, before_state TEXT, after_state TEXT,
 fsrs_log TEXT, undone INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS knowledge_card_history ON knowledge_reviews(card_id, reviewed_at);
CREATE TABLE IF NOT EXISTS knowledge_goals(field TEXT PRIMARY KEY, target INTEGER NOT NULL);
'''


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class DrawRequest(Strict):
    field: FieldName
    request_id: str = Field(min_length=1, max_length=100)
    practice: bool = False


class ScoreRequest(Strict):
    rating: int = Field(ge=1, le=4, strict=True)
    revision: int = Field(ge=0, strict=True)
    request_id: str = Field(min_length=1, max_length=100)


class RevisionRequest(Strict):
    revision: int = Field(ge=0, strict=True)


class GoalRequest(Strict):
    target: int = Field(ge=1, le=100, strict=True)


class StoredState(Strict):
    card_id: str
    fsrs: dict | None
    revision: int = Field(ge=0, strict=True)
    seen_at: str


class StoredDraw(Strict):
    id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=1, max_length=100)
    card_id: str
    field: FieldName
    mode: Literal['review', 'practice']
    kind: Literal['new', 'due', 'relearn', 'practice']
    expected_revision: int = Field(ge=0, strict=True)
    created_at: str
    revealed_at: str | None = None
    status: Literal['pending', 'scored', 'undone', 'invalidated']


class StoredReview(Strict):
    id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=1, max_length=100)
    card_id: str
    field: FieldName
    mode: Literal['review', 'practice']
    rating: int = Field(ge=1, le=4, strict=True)
    reviewed_at: str
    before_state: dict | None
    after_state: dict | None
    fsrs_log: dict | None
    undone: int = Field(ge=0, le=1, strict=True)


class StoredGoal(Strict):
    field: FieldName
    target: int = Field(ge=1, le=100, strict=True)


class KnowledgeBackup(Strict):
    catalog_version: int
    source_sha256: str
    config: dict
    states: list[StoredState] = Field(max_length=10000)
    draws: list[StoredDraw] = Field(max_length=200000)
    reviews: list[StoredReview] = Field(max_length=200000)
    goals: list[StoredGoal] = Field(max_length=4)
    sessions: list[StoredSession] = Field(default_factory=list,max_length=10000)


def now():
    return datetime.now(timezone.utc)


def stamp(value):
    return value.astimezone(timezone.utc).isoformat()


def parse(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError('时间须为 UTC')
    return result


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False) if value is not None else None


def decode(value):
    return json.loads(value) if value is not None else None


def check_card(card_id):
    if card_id not in CARDS:
        raise HTTPException(404, '考点不存在')
    return CARDS[card_id]


def numeric_id(card_id):
    return int(card_id.split('-')[1], 16)


def state(c, card_id):
    row = c.execute('SELECT * FROM knowledge_states WHERE card_id=?', (card_id,)).fetchone()
    return dict(row) if row else dict(card_id=card_id, fsrs=None, revision=0, seen_at=None)


def memory(row, at):
    if row is None or row['fsrs'] is None:
        return dict(status='new', due=None, retention=None)
    card = Card.from_dict(decode(row['fsrs']))
    return dict(status='due' if card.due <= at else 'scheduled', due=stamp(card.due),
                retention=round(SCHEDULER.get_card_retrievability(card, at), 4),
                phase=int(card.state), stability=card.stability, difficulty=card.difficulty)


def counts(c, card_id):
    result = [0, 0, 0, 0]
    for row in c.execute("SELECT rating,COUNT(*) AS n FROM knowledge_reviews WHERE card_id=? AND mode='review' AND undone=0 GROUP BY rating", (card_id,)):
        result[row['rating']-1] = row['n']
    return dict(ratings=result, total=sum(result), remembered=sum(result[1:]))


def detail(c, card_id, at=None, answer=True):
    at = at or now()
    card = check_card(card_id)
    row = state(c, card_id)
    data = {**card, **memory(row, at), **counts(c, card_id), 'revision': row['revision']}
    data['history'] = [dict(r) for r in c.execute(
        'SELECT id,rating,mode,reviewed_at,undone FROM knowledge_reviews WHERE card_id=? ORDER BY reviewed_at DESC,rowid DESC LIMIT 100', (card_id,))]
    if not answer:
        data.pop('answer')
        data.pop('pitfall')
        data.pop('explanation',None)
    return data


def draw_payload(c, draw, at=None):
    at = at or now()
    draw = dict(draw)
    draw['card'] = detail(c, draw['card_id'], at, answer=bool(draw['revealed_at']))
    # Do not leak answer hints in a not-yet-revealed question.
    draw['revision'] = draw['expected_revision']
    if draw['revealed_at'] and draw['status'] == 'pending':
        row = state(c, draw['card_id'])
        if draw['mode'] == 'review':
            fsrs_card = Card.from_dict(decode(row['fsrs'])) if row['fsrs'] else Card(card_id=numeric_id(draw['card_id']), due=at)
            draw['preview_due'] = [stamp(SCHEDULER.review_card(fsrs_card, Rating(r), at)[0].due) for r in range(1, 5)]
    return draw


def overview(c, at=None):
    at = at or now()
    day = at.astimezone(SHANGHAI).date().isoformat()
    rows = {r['card_id']: dict(r) for r in c.execute('SELECT * FROM knowledge_states')}
    goals = {r['field']: r['target'] for r in c.execute('SELECT * FROM knowledge_goals')}
    completed = {field: set() for field in SUBJECTS}
    for r in c.execute("SELECT field,card_id,reviewed_at FROM knowledge_reviews WHERE undone=0 AND mode='review'"):
        if r['card_id'] in CARDS and parse(r['reviewed_at']).astimezone(SHANGHAI).date().isoformat() == day:
            completed[r['field']].add(r['card_id'])
    result = []
    for field, subject in SUBJECTS.items():
        cards = [card for card in CARDS.values() if card['field'] == field]
        memories = [memory(rows.get(card['id']), at) for card in cards]
        pending = c.execute("SELECT * FROM knowledge_draws WHERE field=? AND status='pending'", (field,)).fetchone()
        future = [m['due'] for m in memories if m['status'] == 'scheduled']
        result.append({**subject, 'total': len(cards), 'target': goals.get(field, 5),
                       'completed': len(completed[field]), 'due': sum(m['status']=='due' for m in memories),
                       'new': sum(m['status']=='new' for m in memories),
                       'unseen': sum(card['id'] not in rows for card in cards),
                       'next_due': min(future) if future else None,
                       'pending': draw_payload(c, pending, at) if pending else None})
    last = c.execute('SELECT * FROM knowledge_reviews WHERE undone=0 ORDER BY reviewed_at DESC,rowid DESC LIMIT 1').fetchone()
    last_review = None
    if last and last['card_id'] in CARDS:
        last_review = dict(id=last['id'], field=last['field'], rating=last['rating'],
                           title=CARDS[last['card_id']]['title'], mode=last['mode'],
                           due=memory(state(c, last['card_id']), at)['due'],
                           revision=state(c, last['card_id'])['revision'])
    return dict(day=day, subjects=result, last_review=last_review, config=CONFIG,
                catalog_version=CATALOG['version'], total=len(CARDS), active_session=sessions.summary(c))


def catalog(c, field=None, chapter=None, query='', status_filter=None, at=None):
    at = at or now()
    rows = {r['card_id']: dict(r) for r in c.execute('SELECT * FROM knowledge_states')}
    all_counts = {}
    for r in c.execute("SELECT card_id,rating,COUNT(*) AS n FROM knowledge_reviews WHERE undone=0 AND mode='review' GROUP BY card_id,rating"):
        all_counts.setdefault(r['card_id'], [0]*4)[r['rating']-1] = r['n']
    cards = []
    for card in CARDS.values():
        if field and card['field'] != field or chapter and card['chapter_id'] != chapter:
            continue
        if query and query.casefold() not in ' '.join([card['title'], card['prompt'], card['source'], card['chapter']]).casefold():
            continue
        m = memory(rows.get(card['id']), at)
        if status_filter and m['status'] != status_filter:
            continue
        ratings = all_counts.get(card['id'], [0]*4)
        cards.append({k:v for k,v in card.items() if k not in ('answer', 'pitfall', 'core', 'explanation')}
                     | m | dict(ratings=ratings, total=sum(ratings), remembered=sum(ratings[1:])))
    return dict(subjects=list(SUBJECTS.values()), cards=cards)


def choose(c, field, at, practice=False, rng=None):
    rng = rng or random.SystemRandom()
    candidates = [card for card in CARDS.values() if card['field'] == field]
    rows = {card['id']: state(c, card['id']) for card in candidates}
    fresh, due, relearn, future = [], [], [], []
    for card in candidates:
        row = rows[card['id']]
        if not row['fsrs']:
            fresh.append(card)
            continue
        m = Card.from_dict(decode(row['fsrs']))
        if m.due <= at:
            (relearn if m.state in (State.Learning, State.Relearning) else due).append(card)
        else:
            future.append(card)
    if practice:
        if fresh or due or relearn:
            raise HTTPException(409, '还有新卡或到期考点，请先使用正常抽取。')
        if not future:
            return None
        return rng.choice(future), 'practice'
    if relearn:
        return min(relearn, key=lambda card: Card.from_dict(decode(rows[card['id']]['fsrs'])).due), 'relearn'
    ordinary = c.execute("SELECT COUNT(*) FROM knowledge_draws WHERE field=? AND kind IN ('new','due') AND status='scored'", (field,)).fetchone()[0]
    if fresh and (not due or ordinary % 5 == 4):
        chapter_counts = Counter(card['chapter_id'] for card in candidates)
        seen = Counter(card['chapter_id'] for card in candidates if rows[card['id']]['seen_at'])
        coverage = {card['chapter_id']: seen[card['chapter_id']]/chapter_counts[card['chapter_id']] for card in fresh}
        lowest = min(coverage.values())
        return rng.choice([card for card in fresh if coverage[card['chapter_id']] == lowest]), 'new'
    if due:
        weights = []
        for card in due:
            m = Card.from_dict(decode(rows[card['id']]['fsrs']))
            interval = max((m.due-m.last_review).total_seconds(), 1)
            overdue = max((at-m.due).total_seconds(), 0)/interval
            failures = sum(r['rating']==1 for r in c.execute(
                "SELECT rating FROM knowledge_reviews WHERE card_id=? AND mode='review' AND undone=0 ORDER BY reviewed_at DESC,rowid DESC LIMIT 10", (card['id'],)))
            weights.append((1+4*(1-SCHEDULER.get_card_retrievability(m, at))) *
                           (1+min(overdue, 3)) * (1+min(failures, 3)))
        return rng.choices(due, weights=weights, k=1)[0], 'due'
    return None


def draw(c, body, at=None, rng=None):
    at = at or now()
    existing = c.execute('SELECT * FROM knowledge_draws WHERE request_id=?', (body.request_id,)).fetchone()
    if existing:
        if existing['field'] != body.field or (existing['mode']=='practice') != body.practice:
            raise HTTPException(409, '抽取标识已被另一请求使用。')
        return dict(draw=draw_payload(c, existing, at))
    pending = c.execute("SELECT * FROM knowledge_draws WHERE field=? AND status='pending'", (body.field,)).fetchone()
    if pending:
        return dict(draw=draw_payload(c, pending, at))
    picked = choose(c, body.field, at, body.practice, rng)
    if not picked:
        return dict(draw=None, overview=overview(c, at))
    card, kind = picked
    c.execute('INSERT OR IGNORE INTO knowledge_states(card_id,seen_at) VALUES(?,?)', (card['id'], stamp(at)))
    row = state(c, card['id'])
    draw_id = str(uuid.uuid4())
    c.execute('INSERT INTO knowledge_draws(id,request_id,card_id,field,mode,kind,expected_revision,created_at) VALUES(?,?,?,?,?,?,?,?)',
              (draw_id, body.request_id, card['id'], body.field, 'practice' if body.practice else 'review', kind, row['revision'], stamp(at)))
    return dict(draw=draw_payload(c, c.execute('SELECT * FROM knowledge_draws WHERE id=?', (draw_id,)).fetchone(), at))


def pending_draw(c, draw_id):
    row = c.execute('SELECT * FROM knowledge_draws WHERE id=?', (draw_id,)).fetchone()
    if not row:
        raise HTTPException(404, '这次抽取不存在。')
    if row['status'] != 'pending' or state(c, row['card_id'])['revision'] != row['expected_revision']:
        raise HTTPException(409, '此卡片已在其他页面处理，请刷新继续。')
    return row


def reveal(c, draw_id, at=None):
    at = at or now()
    row = pending_draw(c, draw_id)
    c.execute('UPDATE knowledge_draws SET revealed_at=COALESCE(revealed_at,?) WHERE id=?', (stamp(at), draw_id))
    return draw_payload(c, c.execute('SELECT * FROM knowledge_draws WHERE id=?', (draw_id,)).fetchone(), at)


def score(c, draw_id, body, at=None):
    at = at or now()
    existing = c.execute('SELECT * FROM knowledge_reviews WHERE id=? OR request_id=?', (draw_id, body.request_id)).fetchone()
    if existing:
        if existing['id'] == draw_id and existing['request_id'] == body.request_id and existing['rating'] == body.rating and not existing['undone']:
            return overview(c, at)
        raise HTTPException(409, '这次抽取已评分或请求标识冲突，请刷新查看。')
    row = pending_draw(c, draw_id)
    if not row['revealed_at']:
        raise HTTPException(409, '请先展开答案并核对，再评分。')
    if body.revision != row['expected_revision']:
        raise HTTPException(409, '卡片版本已变化，请刷新。')
    saved = state(c, row['card_id'])
    before = saved['fsrs']
    after, log = before, None
    if row['mode'] == 'review':
        card = Card.from_dict(decode(before)) if before else Card(card_id=numeric_id(row['card_id']), due=at)
        card, review_log = SCHEDULER.review_card(card, Rating(body.rating), at)
        after, log = encode(card.to_dict()), encode(review_log.to_dict())
    c.execute('INSERT INTO knowledge_reviews VALUES(?,?,?,?,?,?,?,?,?,?,0)',
              (draw_id, body.request_id, row['card_id'], row['field'], row['mode'], body.rating, stamp(at), before, after, log))
    c.execute('UPDATE knowledge_states SET fsrs=?,revision=revision+1 WHERE card_id=?', (after, row['card_id']))
    c.execute("UPDATE knowledge_draws SET status='scored' WHERE id=?", (draw_id,))
    sessions.update(c,draw_id)
    return overview(c, at)


def undo(c, review_id, revision, at=None):
    at = at or now()
    row = c.execute('SELECT * FROM knowledge_reviews WHERE id=?', (review_id,)).fetchone()
    if not row:
        raise HTTPException(404, '评分记录不存在。')
    if row['undone']:
        return overview(c, at)
    latest = c.execute('SELECT id FROM knowledge_reviews WHERE undone=0 ORDER BY reviewed_at DESC,rowid DESC LIMIT 1').fetchone()
    saved = state(c, row['card_id'])
    if latest['id'] != review_id or saved['revision'] != revision:
        raise HTTPException(409, '只能撤销最近一次评分，请刷新查看最新记录。')
    c.execute('UPDATE knowledge_reviews SET undone=1 WHERE id=?', (review_id,))
    c.execute("UPDATE knowledge_draws SET status='undone' WHERE id=?", (review_id,))
    c.execute("UPDATE knowledge_draws SET status='invalidated' WHERE card_id=? AND status='pending'", (row['card_id'],))
    c.execute('UPDATE knowledge_states SET fsrs=?,revision=revision+1 WHERE card_id=?', (row['before_state'], row['card_id']))
    sessions.update(c,review_id)
    return overview(c, at)


def export(c):
    records = {}
    for name in ['states', 'draws', 'reviews', 'goals']:
        rows = [dict(r) for r in c.execute('SELECT * FROM knowledge_'+name+' ORDER BY rowid')]
        for r in rows:
            for key in ['fsrs', 'before_state', 'after_state', 'fsrs_log']:
                if key in r:
                    r[key] = decode(r[key])
        records[name] = rows
    return dict(catalog_version=CATALOG['version'], source_sha256=CATALOG['source_sha256'], config=CONFIG, sessions=sessions.export(c), **records)


def validate_fsrs(value, card_id):
    if value is None:
        return
    if set(value) != {'card_id','state','step','stability','difficulty','due','last_review'}:
        raise ValueError('记忆状态字段不完整')
    if value['card_id'] != numeric_id(card_id) or value['state'] not in (1, 2, 3):
        raise ValueError('记忆状态编号或阶段无效')
    if value['step'] not in (None, 0) or (value['state']==2) != (value['step'] is None):
        raise ValueError('学习步骤无效')
    for key in ['stability', 'difficulty']:
        if not isinstance(value[key], (int, float)) or not math.isfinite(value[key]) or value[key] <= 0:
            raise ValueError('记忆参数无效')
    if not 1 <= value['difficulty'] <= 10:
        raise ValueError('难度无效')
    if parse(value['due']) < parse(value['last_review']):
        raise ValueError('复习时间无效')
    Card.from_dict(value)


def normalize_backup_card_ids(body):
    """Recover redundant numeric IDs rounded by older browser JSON transport.

    The canonical string ID remains authoritative. Only accept the same IEEE-754
    value for unsafe integers; the full scheduler/history validation still runs.
    """
    for records, fields in [(body.states, ('fsrs',)),
                            (body.reviews, ('before_state', 'after_state', 'fsrs_log'))]:
        for record in records:
            if record.card_id not in ALL_CARDS:
                continue
            expected = numeric_id(record.card_id)
            if expected <= 2**53 - 1:
                continue
            for field in fields:
                value = getattr(record, field)
                if value is None:
                    continue
                actual = value.get('card_id')
                if type(actual) is int and actual != expected:
                    try:
                        rounded_match = float(actual) == float(expected)
                    except OverflowError:
                        rounded_match = False
                    if rounded_match:
                        value['card_id'] = expected


def validate_backup(body):
    """Check cross-record integrity and replay the official scheduler before restore."""
    compatible={(v['version'],v['source_sha256']) for v in [CATALOG,LEGACY_CATALOG]}
    if body.config != CONFIG or (body.catalog_version,body.source_sha256) not in compatible:
        raise HTTPException(400, '考点备份的大纲版本或调度配置不兼容。')
    try:
        normalize_backup_card_ids(body)
        states = {s.card_id: s for s in body.states}
        draws = {d.id: d for d in body.draws}
        reviews = {r.id: r for r in body.reviews}
        if len(states)!=len(body.states) or len(draws)!=len(body.draws) or len(reviews)!=len(body.reviews):
            raise ValueError('重复的考点记录')
        if len({d.request_id for d in body.draws})!=len(body.draws) or len({r.request_id for r in body.reviews})!=len(body.reviews):
            raise ValueError('重复的提交标识')
        if len({g.field for g in body.goals}) != len(body.goals):
            raise ValueError('重复的每日目标')
        pending_cards = set()
        compatible_cards=ARCHIVED_CARDS if body.catalog_version==LEGACY_CATALOG['version'] else ALL_CARDS
        for s in body.states:
            if s.card_id not in compatible_cards:
                raise ValueError('未知考点')
            parse(s.seen_at)
            validate_fsrs(s.fsrs, s.card_id)
        for d in body.draws:
            if d.card_id not in states or ALL_CARDS[d.card_id]['field'] != d.field:
                raise ValueError('抽取的科目或考点不匹配')
            if (d.mode=='practice') != (d.kind=='practice'):
                raise ValueError('抽取模式不一致')
            created = parse(d.created_at)
            if created < parse(states[d.card_id].seen_at):
                raise ValueError('抽取时间早于首次记录')
            if d.revealed_at and parse(d.revealed_at)<created:
                raise ValueError('展开时间无效')
            if d.expected_revision > states[d.card_id].revision:
                raise ValueError('抽取版本超前')
            if d.status == 'pending':
                if d.card_id in pending_cards or d.expected_revision != states[d.card_id].revision:
                    raise ValueError('重复或过期的待答卡片')
                pending_cards.add(d.card_id)
            if (d.status in ('scored','undone')) != (d.id in reviews):
                raise ValueError('抽取与评分记录不完整')
        last_time = {}
        replay = {card_id: None for card_id in states}
        for r in body.reviews:
            d = draws.get(r.id)
            if not d or (d.card_id,d.field,d.mode)!=(r.card_id,r.field,r.mode) or d.status != ('undone' if r.undone else 'scored'):
                raise ValueError('评分对应的抽取不一致')
            at = parse(r.reviewed_at)
            if not d.revealed_at or at < parse(d.revealed_at) or at < last_time.get(r.card_id, at):
                raise ValueError('评分时间或顺序无效')
            last_time[r.card_id] = at
            validate_fsrs(r.before_state, r.card_id)
            validate_fsrs(r.after_state, r.card_id)
            if r.mode == 'practice':
                if r.before_state != r.after_state or r.fsrs_log is not None or r.before_state is None:
                    raise ValueError('提前练习不能修改记忆调度')
            else:
                card = Card.from_dict(r.before_state) if r.before_state else Card(card_id=numeric_id(r.card_id), due=at)
                scheduled, log = SCHEDULER.review_card(card, Rating(r.rating), at)
                if scheduled.to_dict()!=r.after_state or log.to_dict()!=r.fsrs_log:
                    raise ValueError('评分与记忆调度不一致')
            if not r.undone:
                if r.before_state != replay[r.card_id]:
                    raise ValueError('评分历史断裂')
                replay[r.card_id] = r.after_state
        sessions.validate(body.sessions,draws)
        for card_id, s in states.items():
            if replay[card_id] != s.fsrs:
                raise ValueError('当前记忆状态与历史不一致')
    except (ValueError, TypeError, KeyError, OverflowError, AssertionError) as error:
        raise HTTPException(400, '考点备份无效：'+str(error)) from error


def check_restore_conflicts(c, body):
    incoming = {s.card_id for s in body.states}
    for table, records in [('draws', body.draws), ('reviews', body.reviews)]:
        for record in records:
            for row in c.execute('SELECT card_id FROM knowledge_'+table+' WHERE id=? OR request_id=?', (record.id, record.request_id)):
                if row['card_id'] not in incoming:
                    raise HTTPException(400, '考点备份的记录标识与未覆盖的本地卡片冲突。')
    for session in body.sessions:
        for row in c.execute('SELECT id FROM knowledge_sessions WHERE request_id=?',(session.request_id,)):
            if row['id']!=session.id:raise HTTPException(400,'连续复习标识与本地另一组记录冲突。')
    # Do not replace an unrelated pending card.

    for d in body.draws:
        if d.status == 'pending':
            row = c.execute("SELECT card_id FROM knowledge_draws WHERE card_id=? AND status='pending'", (d.card_id,)).fetchone()
            if row and row['card_id'] not in incoming:
                raise HTTPException(409, '本地该科目还有未作答卡片，请先完成后再恢复此部分备份。')


def restore(c, body):
    check_restore_conflicts(c, body)
    # Bump revisions past both local and imported versions so pre-restore tabs
    # cannot submit a stale score, while imported pending draws stay resumable.
    revisions = {s.card_id: max(state(c, s.card_id)['revision'], s.revision)+1 for s in body.states}
    for s in body.states:
        for table in ['reviews', 'draws', 'states']:
            c.execute('DELETE FROM knowledge_'+table+' WHERE card_id=?', (s.card_id,))
    for name, records in [('states', body.states), ('draws', body.draws), ('reviews', body.reviews)]:
        for record in records:
            row = record.model_dump()
            if name == 'states':
                row['revision'] = revisions[row['card_id']]
            elif name == 'draws' and row['status'] == 'pending':
                row['expected_revision'] = revisions[row['card_id']]
            for key in ['fsrs', 'before_state', 'after_state', 'fsrs_log']:
                if key in row:
                    row[key] = encode(row[key])
            c.execute('INSERT INTO knowledge_'+name+'('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')', tuple(row.values()))
    # Removed outline cards remain archival records, never resumable study cards.
    c.execute("UPDATE knowledge_draws SET status='invalidated' WHERE status='pending' AND card_id NOT LIKE 'mc-%'")
    sessions.restore(c,body.sessions)
    for goal in body.goals:
        c.execute('INSERT OR REPLACE INTO knowledge_goals VALUES(?,?)', (goal.field, goal.target))
