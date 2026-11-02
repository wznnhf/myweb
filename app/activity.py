"""Durable learning footprints, independent of later corrections to a result.

One question/card counts once per subject, section and Beijing calendar day.
Reading, collection, notes, and automatic scheduling do not create footprints.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

SHANGHAI = timezone(timedelta(hours=8))
Area = Literal['library', 'mistakes', 'daily_review', 'daily_practice', 'knowledge']
QuestionArea = Literal['library', 'mistakes', 'daily_review', 'daily_practice']
Scope = Literal['all', 'library', 'mistakes', 'daily_review', 'daily_practice', 'knowledge']
LABELS = dict(library='试卷练习', mistakes='错题复习', daily_review='每日回顾', daily_practice='每日一练', knowledge='考点回忆')
SCHEMA = '''CREATE TABLE IF NOT EXISTS study_activity(
 subject TEXT NOT NULL CHECK(subject IN ('math','408')),
 area TEXT NOT NULL CHECK(area IN ('library','mistakes','daily_review','daily_practice','knowledge')),
 day TEXT NOT NULL, item_id TEXT NOT NULL, performed_at TEXT NOT NULL,
 PRIMARY KEY(subject,area,day,item_id)
);
CREATE INDEX IF NOT EXISTS study_activity_dates ON study_activity(subject,day);'''


class ActivityRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')
    subject: Literal['math', '408']
    area: Area
    day: str
    item_id: str = Field(min_length=1, max_length=200)
    performed_at: str


def today():
    return datetime.now(SHANGHAI).date()


def parse_time(value):
    at = datetime.fromisoformat(value)
    if at.tzinfo is None:
        raise ValueError('A timezone is required')
    return at


def record(c, subject, area, item_id, performed_at):
    at = parse_time(performed_at)
    day = at.astimezone(SHANGHAI).date().isoformat()
    c.execute('INSERT OR IGNORE INTO study_activity VALUES(?,?,?,?,?)',
              (subject, area, day, item_id, at.astimezone(timezone.utc).isoformat()))


def question(c, papers, pid, number, area, at):
    record(c, papers[pid]['subject'], area, f'q:{pid}:{number}', at)


def backfill(c, papers):
    """Only reconstruct dated evidence; an old state/note timestamp is ambiguous."""
    for table, area in [('daily_items', 'daily_review'), ('practice_items', 'daily_practice')]:
        for row in c.execute(f'SELECT paper_id,number,answered_at FROM {table} WHERE result IS NOT NULL AND answered_at IS NOT NULL').fetchall():
            if row['paper_id'] not in papers:
                continue
            try:
                question(c, papers, row['paper_id'], row['number'], area, row['answered_at'])
            except (ValueError, TypeError, OverflowError):
                continue
    for row in c.execute('SELECT card_id,reviewed_at FROM knowledge_reviews').fetchall():
        try:
            record(c, '408', 'knowledge', 'k:' + row['card_id'], row['reviewed_at'])
        except (ValueError, TypeError, OverflowError):
            continue


def level(count):
    return 0 if not count else 1 if count < 5 else 2 if count < 10 else 3 if count < 20 else 4


def calendar(c, subject='math', area='all', year=None):
    as_of = today()
    end = as_of
    if year is None:
        start = end - timedelta(days=364)
    else:
        if not 1 <= year <= end.year:
            raise HTTPException(400, '请选择今年或过去的年份')
        start, end = date(year, 1, 1), date(year, 12, 31)
    query = 'SELECT day,item_id,area FROM study_activity WHERE subject=? AND day BETWEEN ? AND ?'
    values = [subject, start.isoformat(), min(end, as_of).isoformat()]
    if area != 'all':
        query += ' AND area=?'
        values.append(area)
    distinct, groups = defaultdict(set), defaultdict(lambda: defaultdict(set))
    for row in c.execute(query, values):
        distinct[row['day']].add(row['item_id'])
        groups[row['day']][row['area']].add(row['item_id'])
    days, cursor = [], start
    while cursor <= end:
        key = cursor.isoformat()
        count = len(distinct[key])
        days.append(dict(day=key, count=count, level=level(count), future=cursor > as_of,
                         areas=[dict(area=a, label=LABELS[a], count=len(items)) for a, items in sorted(groups[key].items())]))
        cursor += timedelta(days=1)
    active = {d['day'] for d in days if d['count']}
    longest, run = 0, 0
    for d in days:
        run = run + 1 if d['count'] else 0
        longest = max(longest, run)
    current, cursor = 0, as_of
    if cursor.isoformat() not in active:
        cursor -= timedelta(days=1)  # Yesterday's streak remains available until today ends.
    while start <= cursor <= end and cursor.isoformat() in active:
        current += 1
        cursor -= timedelta(days=1)
    earliest = c.execute('SELECT MIN(day) FROM study_activity WHERE subject=?', (subject,)).fetchone()[0]
    first_year = int(earliest[:4]) if earliest else as_of.year
    return dict(subject=subject, area=area, label='全部学习' if area == 'all' else LABELS[area], year=year,
                today=as_of.isoformat(), start=start.isoformat(), end=end.isoformat(), days=days,
                years=list(range(as_of.year, first_year - 1, -1)),
                total=sum(d['count'] for d in days), active_days=len(active), current_streak=current,
                longest_streak=longest, today_count=len(distinct.get(as_of.isoformat(), set())))


def export(c):
    return [dict(r) for r in c.execute('SELECT * FROM study_activity ORDER BY day,subject,area,item_id')]


def validate(records, papers, cards):
    keys = set()
    for r in records:
        try:
            day = date.fromisoformat(r.day)
            at = parse_time(r.performed_at)
            if day.isoformat() != r.day or day > today() or at.astimezone(SHANGHAI).date() != day:
                raise ValueError('日期不一致或晚于今天')
            if r.area == 'knowledge':
                if r.subject != '408' or not r.item_id.startswith('k:') or r.item_id[2:] not in cards:
                    raise ValueError('考点不存在')
            else:
                prefix, pid, number = r.item_id.split(':')
                paper = papers[pid]
                if prefix != 'q' or str(int(number)) != number or not 1 <= int(number) <= paper['question_count'] or paper['subject'] != r.subject:
                    raise ValueError('题目或科目不一致')
                if r.area == 'daily_practice' and paper.get('source_kind') != 'exercise_book':
                    raise ValueError('每日一练题源不匹配')
            key = (r.subject, r.area, r.day, r.item_id)
            if key in keys:
                raise ValueError('重复的打卡记录')
            keys.add(key)
        except (ValueError, TypeError, KeyError, OverflowError):
            raise HTTPException(400, '学习打卡记录的日期、科目或题目无效，或存在重复记录')


def restore(c, records):
    # Footprints reflect actual work. Merge history without erasing newer local work.
    for r in records:
        record(c, r.subject, r.area, r.item_id, r.performed_at)
