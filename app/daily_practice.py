"""Calendar-based, persistent and non-repeating 408 book practice."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import random
import secrets
from typing import Literal
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parent
CATALOG_PATH = ROOT / 'data/relax-catalog.json'
BOOK = json.loads(CATALOG_PATH.read_text()) if CATALOG_PATH.exists() else {'papers': [], 'sha256': ''}
PAPERS = {p['id']: p for p in BOOK['papers']}
ANSWER_PATH = ROOT / 'data/relax-answers.json'
ANSWERS = json.loads(ANSWER_PATH.read_text()) if ANSWER_PATH.exists() else {'papers': {}}
if ANSWERS.get('papers') and ANSWERS.get('question_book_sha256') != BOOK['sha256']:
    raise RuntimeError('每日一练答案与题册版本不一致')
FIELDS = {'ds': '数据结构', 'co': '计算机组成原理', 'os': '操作系统', 'cn': '计算机网络'}
ALGORITHM = 1
SCHEMA = '''
CREATE TABLE IF NOT EXISTS practice_rounds(
 id TEXT PRIMARY KEY, start_day TEXT NOT NULL UNIQUE, end_day TEXT NOT NULL,
 book_version TEXT NOT NULL, seed TEXT NOT NULL, algorithm INTEGER NOT NULL,
 created_at TEXT NOT NULL, last_day TEXT, last_position INTEGER, last_viewed_at TEXT
);
CREATE TABLE IF NOT EXISTS practice_items(
 round_id TEXT NOT NULL REFERENCES practice_rounds(id) ON DELETE CASCADE,
 day TEXT NOT NULL, position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 40),
 paper_id TEXT NOT NULL, number INTEGER NOT NULL CHECK(number>=1),
 result TEXT CHECK(result IN ('correct','wrong')), answered_at TEXT,
 PRIMARY KEY(round_id,day,position), UNIQUE(round_id,paper_id,number),
 CHECK((result IS NULL AND answered_at IS NULL) OR (result IS NOT NULL AND answered_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS practice_day ON practice_items(round_id,day);
CREATE TABLE IF NOT EXISTS practice_choices(
 round_id TEXT NOT NULL, day TEXT NOT NULL, position INTEGER NOT NULL,
 choice TEXT NOT NULL, selected_at TEXT NOT NULL,
 PRIMARY KEY(round_id,day,position),
 FOREIGN KEY(round_id,day,position) REFERENCES practice_items(round_id,day,position) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS practice_submissions(
 round_id TEXT NOT NULL REFERENCES practice_rounds(id) ON DELETE CASCADE,
 day TEXT NOT NULL, submitted_at TEXT NOT NULL,
 PRIMARY KEY(round_id,day)
);
'''


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Answer(Strict):
    choice: str | None = Field(pattern=r'^[ABCD_]{1,3}$')


class Submission(Strict):
    day: str
    submitted_at: str


class Position(Strict):
    day: str
    position: int = Field(ge=1, le=40)


class ItemRecord(Position):
    paper_id: str
    number: int = Field(ge=1)
    result: Literal['correct', 'wrong'] | None = None
    answered_at: str | None = None
    choice: str | None = Field(default=None, pattern=r'^[ABCD_]{1,3}$')
    selected_at: str | None = None


class RoundRecord(Strict):
    id: str = Field(pattern=r'^[a-f0-9]{32}$')
    start_day: str
    end_day: str
    book_version: str = Field(pattern=r'^[a-f0-9]{64}$')
    seed: str = Field(pattern=r'^[a-f0-9]{32}$')
    algorithm: Literal[1]
    created_at: str
    last_day: str | None = None
    last_position: int | None = Field(default=None, ge=1, le=40)
    last_viewed_at: str | None = None
    items: list[ItemRecord] = Field(min_length=1, max_length=10000)
    submissions: list[Submission] = Field(default_factory=list, max_length=10000)


def today():
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def now():
    return datetime.now(timezone.utc).isoformat()


def iso_day(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() == value:
            return parsed
    except (ValueError, TypeError):
        pass
    raise HTTPException(400, '练习日期格式不正确')


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            return parsed
    except (ValueError, TypeError):
        pass
    raise HTTPException(400, '练习记录的时间格式不正确')


def schedule(seed, start_day):
    """Integer cumulative deficits avoid independent daily rounding bias."""
    start = iso_day(start_day)
    queues = {}
    for field in FIELDS:
        rng = random.Random(seed + ':' + field)
        chapters = sorted((p for p in PAPERS.values() if p['field'] == field), key=lambda p: p['chapter_order'])
        rng.shuffle(chapters)  # Reproducible tie breaking, saved with the round.
        pools = {}
        for p in chapters:
            pool = list(range(1, p['question_count'] + 1))
            rng.shuffle(pool)
            pools[p['id']] = pool
        total = sum(len(pool) for pool in pools.values())
        used = Counter()
        refs = []
        for k in range(1, total + 1):
            p = max((p for p in chapters if used[p['id']] < p['question_count']),
                    key=lambda p: k * p['question_count'] - used[p['id']] * total)
            pid = p['id']
            refs.append((pid, pools[pid][used[pid]]))
            used[pid] += 1
        queues[field] = refs
    days = max(((len(q) + 9) // 10 for q in queues.values()), default=0)
    items = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()
        position = 0
        for field in FIELDS:
            for pid, number in queues[field][offset * 10:offset * 10 + 10]:
                position += 1
                items.append(dict(day=day, position=position, paper_id=pid, number=number))
    return items


def latest(c):
    return c.execute('SELECT * FROM practice_rounds ORDER BY start_day DESC LIMIT 1').fetchone()


def start(c, next_round=False):
    # Caller holds BEGIN IMMEDIATE; retries and concurrent tabs return the same round.
    if not PAPERS:
        raise HTTPException(503, '每日一练题库尚未导入，请先运行 import_relax.py')
    previous = latest(c)
    if previous and not next_round:
        return previous['id']
    day = today()
    if next_round:
        if not previous:
            raise HTTPException(409, '请先开始第一轮每日一练')
        if previous['start_day'] > day:
            return previous['id']
        if previous['end_day'] > day:
            raise HTTPException(409, '本轮题目尚未全部开放，暂时不能开启下一轮')
        day = (iso_day(day) + timedelta(days=1)).isoformat()
    round_id, seed = uuid.uuid4().hex, secrets.token_hex(16)
    items = schedule(seed, day)
    c.execute('INSERT INTO practice_rounds(id,start_day,end_day,book_version,seed,algorithm,created_at) VALUES(?,?,?,?,?,?,?)',
              (round_id, day, items[-1]['day'], BOOK['sha256'], seed, ALGORITHM, now()))
    c.executemany('INSERT INTO practice_items(round_id,day,position,paper_id,number) VALUES(?,?,?,?,?)',
                  [(round_id, i['day'], i['position'], i['paper_id'], i['number']) for i in items])
    return round_id


def round_row(c, round_id):
    row = c.execute('SELECT * FROM practice_rounds WHERE id=?', (round_id,)).fetchone()
    if row is None:
        raise HTTPException(404, '这轮每日一练不存在')
    return row


def item(c, round_id, day, position):
    iso_day(day)
    round_row(c, round_id)
    if day > today():
        raise HTTPException(404, '这一天的题目尚未开放')
    row = c.execute('SELECT * FROM practice_items WHERE round_id=? AND day=? AND position=?',
                    (round_id, day, position)).fetchone()
    if row is None:
        raise HTTPException(404, '这道题不在指定日期的练习中')
    return row


def mark_position(c, round_id, day, position):
    item(c, round_id, day, position)
    c.execute('UPDATE practice_rounds SET last_day=?,last_position=?,last_viewed_at=? WHERE id=?',
              (day, position, now(), round_id))


def solution(paper_id, number):
    answer = ANSWERS['papers'].get(paper_id, {}).get(str(number))
    if not answer:
        raise HTTPException(503, '这道题的答案尚未导入')
    return answer


def submitted(c, round_id, day):
    return c.execute('SELECT submitted_at FROM practice_submissions WHERE round_id=? AND day=?',
                     (round_id, day)).fetchone()


def choose(c, round_id, day, position, choice):
    row = item(c, round_id, day, position)
    if submitted(c, round_id, day):
        raise HTTPException(409, '这组练习已经交卷，答案已锁定')
    slots = solution(row['paper_id'], row['number'])['slots']
    if choice is not None and (len(choice) != slots or not set(choice) <= set('ABCD_') or set(choice) == {'_'}):
        raise HTTPException(400, '请按题目空数选择 A、B、C、D')
    if choice is None:
        c.execute('DELETE FROM practice_choices WHERE round_id=? AND day=? AND position=?', (round_id, day, position))
    else:
        c.execute('''INSERT INTO practice_choices VALUES(?,?,?,?,?)
          ON CONFLICT(round_id,day,position) DO UPDATE SET choice=excluded.choice,selected_at=excluded.selected_at
          WHERE practice_choices.choice!=excluded.choice''', (round_id, day, position, choice, now()))
    mark_position(c, round_id, day, position)


def submit(c, round_id, day):
    payload = day_payload(c, round_id, day)
    if payload['submitted']:
        return False
    if payload['completed'] != payload['total']:
        raise HTTPException(409, f"还有 {payload['total'] - payload['completed']} 道题未完成，请全部作答后交卷")
    at = now()
    mistake_folder = None
    for row in payload['items']:
        answer = solution(row['paper_id'], row['number'])['answer']
        result = 'correct' if row['choice'] == answer else 'wrong'
        c.execute('UPDATE practice_items SET result=?,answered_at=? WHERE round_id=? AND day=? AND position=?',
                  (result, at, round_id, day, row['position']))
        if result == 'wrong':
            if mistake_folder is None:
                folder = c.execute("SELECT id FROM folders WHERE subject='408' AND name='每日一练错题'").fetchone()
                mistake_folder = folder['id'] if folder else str(uuid.uuid4())
                if not folder:
                    c.execute('INSERT INTO folders(id,name,created_at,subject) VALUES(?,?,?,?)',
                              (mistake_folder, '每日一练错题', at, '408'))
            c.execute('INSERT OR IGNORE INTO memberships(folder_id,paper_id,number) VALUES(?,?,?)',
                      (mistake_folder, row['paper_id'], row['number']))
    c.execute('INSERT INTO practice_submissions VALUES(?,?,?)', (round_id, day, at))
    return True


def day_payload(c, round_id, day):
    r = round_row(c, round_id)
    iso_day(day)
    if day > today():
        raise HTTPException(404, '这一天的题目尚未开放')
    rows = c.execute('''SELECT i.*,ch.choice,ch.selected_at FROM practice_items i
        LEFT JOIN practice_choices ch USING(round_id,day,position)
        WHERE i.round_id=? AND i.day=? ORDER BY i.position''',
                     (round_id, day)).fetchall()
    if not rows:
        raise HTTPException(404, '这一天没有安排练习')
    items = []
    submission = submitted(c, round_id, day)
    collection = c.execute('''SELECT f.id,COUNT(*) AS collected FROM folders f
        JOIN memberships m ON m.folder_id=f.id
        JOIN practice_items i ON i.paper_id=m.paper_id AND i.number=m.number
        WHERE f.subject='408' AND f.name='每日一练错题'
        AND i.round_id=? AND i.day=? AND i.result='wrong' GROUP BY f.id''',
        (round_id, day)).fetchone() if submission else None
    for row in rows:
        p = PAPERS[row['paper_id']]
        q = p['questions'][row['number'] - 1]
        answer = solution(p['id'], row['number'])
        visible = dict(row)
        if not submission:
            visible.update(result=None, answered_at=None)
        else:
            visible.update(correct_answer=answer['answer'], analysis_page=answer['page'],
                analysis_end_page=answer['end_page'],
                analysis_url=f'/api/daily-practice/rounds/{round_id}/days/{day}/items/{row["position"]}/analysis.pdf#page={answer["page"]}')
        items.append({**visible, 'slots': answer['slots'], 'field': p['field'], 'field_label': p['field_label'],
                      'chapter': p['chapter'], 'title': p['title'], 'image': q['image'],
                      'book_pages': [s['book_page'] for s in q['segments']],
                      'pdf_page': q['segments'][0]['page']})
    return dict(round_id=round_id, day=day, start_day=r['start_day'], end_day=r['end_day'],
                submitted=bool(submission), submitted_at=submission['submitted_at'] if submission else None,
                mistake_folder_id=collection['id'] if collection else None,
                collected_wrong=collection['collected'] if collection else 0,
                items=items, total=len(items), completed=sum(bool(i['choice']) and '_' not in i['choice'] for i in items),
                correct=sum(i['result'] == 'correct' for i in items) if submission else None,
                wrong=sum(i['result'] == 'wrong' for i in items) if submission else None)


def overview(c, round_id=None):
    day = today()
    rounds = [dict(r) for r in c.execute('SELECT * FROM practice_rounds ORDER BY start_day DESC')]
    totals = Counter()
    for p in PAPERS.values():
        totals[p['field']] += p['question_count']
    basic = dict(today=day, ready=bool(PAPERS), book_title=BOOK.get('title', 'Relax 1000题'),
                 total_questions=sum(totals.values()), rounds=[{k: r[k] for k in ('id', 'start_day', 'end_day')} for r in rounds],
                 fields=[dict(field=f, label=label, total=totals[f]) for f, label in FIELDS.items()])
    if not rounds:
        return {**basic, 'started': False}
    selected = round_row(c, round_id) if round_id else next((r for r in rounds if r['start_day'] <= day), rounds[0])
    selected = dict(selected)
    history = [dict(r) for r in c.execute('''SELECT i.day,COUNT(*) AS total,
        SUM(ch.choice IS NOT NULL AND instr(ch.choice,'_')=0) AS completed,
        CASE WHEN s.submitted_at IS NOT NULL THEN SUM(i.result='correct') END AS correct,
        CASE WHEN s.submitted_at IS NOT NULL THEN SUM(i.result='wrong') END AS wrong,
        s.submitted_at IS NOT NULL AS submitted
        FROM practice_items i LEFT JOIN practice_choices ch USING(round_id,day,position)
        LEFT JOIN practice_submissions s USING(round_id,day)
        WHERE i.round_id=? AND i.day<=? GROUP BY i.day ORDER BY i.day DESC''', (selected['id'], day))]
    issued, completed = Counter(), Counter()
    for row in c.execute('''SELECT paper_id,result,ch.choice FROM practice_items
        LEFT JOIN practice_choices ch USING(round_id,day,position) WHERE round_id=? AND day<=?''', (selected['id'], day)):
        f = PAPERS[row['paper_id']]['field']
        issued[f] += 1
        completed[f] += bool(row['choice'] and '_' not in row['choice']) or row['result'] is not None
    selected_day = min(day, selected['end_day']) if selected['start_day'] <= day else None
    cursor = None
    if selected['last_day'] and selected['last_day'] <= day:
        cursor = dict(day=selected['last_day'], position=selected['last_position'])
    summary = {k: selected[k] for k in ('id', 'start_day', 'end_day')}
    summary.update(total=sum(totals.values()), released=sum(issued.values()), completed=sum(completed.values()),
                   remaining=sum(totals.values()) - sum(issued.values()), last_position=cursor)
    fields = [dict(field=f, label=label, total=totals[f], released=issued[f], completed=completed[f],
                   remaining=totals[f] - issued[f]) for f, label in FIELDS.items()]
    return {**basic, 'started': True, 'round': summary, 'fields': fields, 'history': history,
            'selected_day': selected_day,
            'day': day_payload(c, selected['id'], selected_day) if selected_day else None,
            'can_start_next': rounds[0]['end_day'] <= day,
            'upcoming': next(({k: r[k] for k in ('id', 'start_day', 'end_day')} for r in rounds if r['start_day'] > day), None)}


def export(c):
    return [{**dict(r), 'items': [dict(i) for i in c.execute(
        '''SELECT day,position,paper_id,number,result,answered_at,ch.choice,ch.selected_at FROM practice_items
        LEFT JOIN practice_choices ch USING(round_id,day,position) WHERE round_id=? ORDER BY day,position''', (r['id'],))],
        'submissions': [dict(s) for s in c.execute('SELECT day,submitted_at FROM practice_submissions WHERE round_id=? ORDER BY day', (r['id'],))]}
        for r in c.execute('SELECT * FROM practice_rounds ORDER BY start_day')]


def validate_backup(records):
    ids, ranges = set(), []
    for r in records:
        if r.id in ids:
            raise HTTPException(400, '备份包含重复的练习轮次')
        ids.add(r.id)
        start_day, end_day = iso_day(r.start_day), iso_day(r.end_day)
        if start_day > iso_day(today()) + timedelta(days=1):
            raise HTTPException(400, '练习开始日期不能晚于明天')
        if r.book_version != BOOK['sha256']:
            raise HTTPException(400, '每日一练题册版本不匹配，请保留对应的题库')
        timestamp(r.created_at)
        expected = schedule(r.seed, r.start_day)
        actual = [dict(day=i.day, position=i.position, paper_id=i.paper_id, number=i.number) for i in r.items]
        if actual != expected or not expected or r.end_day != expected[-1]['day']:
            raise HTTPException(400, '每日一练排期不完整、题目重复或不符合本轮排题规则')
        for i in r.items:
            if bool(i.answered_at) != (i.result is not None):
                raise HTTPException(400, '每日一练的作答记录不完整')
            if i.answered_at:
                at = timestamp(i.answered_at)
                answered_day = at.astimezone(timezone(timedelta(hours=8))).date().isoformat()
                if i.day > today() or not i.day <= answered_day <= today():
                    raise HTTPException(400, '未开放的练习不能有作答记录，作答日期也不能早于开放日期')
            if bool(i.selected_at) != (i.choice is not None):
                raise HTTPException(400, '每日一练的选项记录不完整')
            if i.choice is not None:
                if len(i.choice) != solution(i.paper_id, i.number)['slots'] or set(i.choice) == {'_'}:
                    raise HTTPException(400, '每日一练选项与题目空数不匹配')
                selected_day = timestamp(i.selected_at).astimezone(timezone(timedelta(hours=8))).date().isoformat()
                if not i.day <= selected_day <= today():
                    raise HTTPException(400, '每日一练选项保存日期无效')
        if len({s.day for s in r.submissions}) != len(r.submissions):
            raise HTTPException(400, '每日一练包含重复交卷记录')
        for s in r.submissions:
            submitted_time = timestamp(s.submitted_at)
            submitted_day = submitted_time.astimezone(timezone(timedelta(hours=8))).date().isoformat()
            items = [i for i in r.items if i.day == s.day]
            if not items or not s.day <= submitted_day <= today():
                raise HTTPException(400, '每日一练交卷日期无效')
            for i in items:
                if not i.choice or '_' in i.choice or timestamp(i.selected_at) > submitted_time:
                    raise HTTPException(400, '已交卷练习必须包含完整选项')
                expected_result = 'correct' if i.choice == solution(i.paper_id, i.number)['answer'] else 'wrong'
                if i.result != expected_result or i.answered_at != s.submitted_at:
                    raise HTTPException(400, '每日一练判分与选项不一致')
        cursor = (r.last_day, r.last_position, r.last_viewed_at)
        if any(v is not None for v in cursor):
            if not all(v is not None for v in cursor) or r.last_day > today() or not any(
                    i.day == r.last_day and i.position == r.last_position for i in r.items):
                raise HTTPException(400, '每日一练阅读位置无效')
            viewed = timestamp(r.last_viewed_at).astimezone(timezone(timedelta(hours=8))).date().isoformat()
            if not r.last_day <= viewed <= today():
                raise HTTPException(400, '每日一练阅读时间无效')
        ranges.append((start_day, end_day))
    ranges.sort()
    if any(a[1] >= b[0] for a, b in zip(ranges, ranges[1:])):
        raise HTTPException(400, '练习轮次的日期重叠')


def check_restore_conflicts(c, records):
    # Entire matching rounds are replaced; unrelated, non-overlapping rounds survive.
    replacing = {r.id for r in records}
    ranges = [(r.start_day, r.end_day) for r in records]
    ranges += [(r['start_day'], r['end_day']) for r in c.execute('SELECT * FROM practice_rounds') if r['id'] not in replacing]
    ranges.sort()
    if any(a[1] >= b[0] for a, b in zip(ranges, ranges[1:])):
        raise HTTPException(409, '备份练习轮次与本机其他轮次日期重叠，请使用同一轮次的完整备份')


def restore(c, records):
    # Delete all affected rounds first, allowing a valid batch to change start dates atomically.
    for r in records:
        c.execute('DELETE FROM practice_rounds WHERE id=?', (r.id,))
    for r in records:
        c.execute('INSERT INTO practice_rounds VALUES(?,?,?,?,?,?,?,?,?,?)',
                  (r.id, r.start_day, r.end_day, r.book_version, r.seed, r.algorithm, r.created_at,
                   r.last_day, r.last_position, r.last_viewed_at))
        c.executemany('INSERT INTO practice_items VALUES(?,?,?,?,?,?,?)',
                      [(r.id, i.day, i.position, i.paper_id, i.number, i.result, i.answered_at) for i in r.items])
        c.executemany('INSERT INTO practice_choices VALUES(?,?,?,?,?)',
                      [(r.id, i.day, i.position, i.choice, i.selected_at) for i in r.items if i.choice is not None])
        c.executemany('INSERT INTO practice_submissions VALUES(?,?,?)',
                      [(r.id, s.day, s.submitted_at) for s in r.submissions])
