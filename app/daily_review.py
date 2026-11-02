"""Persistent daily review, with weighted sampling and a previous-session cooldown."""
import math
import random
from datetime import datetime, timedelta, timezone

SHANGHAI = timezone(timedelta(hours=8))
RESULT_LABELS = {'correct': '做对', 'wrong': '做错', None: '未作答'}

SCHEMA = '''
CREATE TABLE IF NOT EXISTS daily_batches(
  day TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  pool_size INTEGER NOT NULL,
  repeated_previous INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS daily_items(
  day TEXT NOT NULL REFERENCES daily_batches(day) ON DELETE CASCADE,
  position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 5),
  paper_id TEXT NOT NULL,
  number INTEGER NOT NULL CHECK(number BETWEEN 1 AND 22),
  result TEXT CHECK(result IN ('correct','wrong')),
  answered_at TEXT,
  PRIMARY KEY(day,position),
  UNIQUE(day,paper_id,number)
);
CREATE INDEX IF NOT EXISTS daily_question_history ON daily_items(paper_id,number,day);
'''

def today():
    return datetime.now(SHANGHAI).date().isoformat()

def statistics(c):
    return {(r['paper_id'],r['number']):dict(r) for r in c.execute('''
      SELECT paper_id,number,COUNT(*) AS drawn_count,
        SUM(CASE WHEN result='wrong' THEN 1 ELSE 0 END) AS wrong_count,
        SUM(CASE WHEN result='correct' THEN 1 ELSE 0 END) AS correct_count,
        MAX(day) AS last_drawn FROM daily_items GROUP BY paper_id,number
    ''')}

def weighted_pick(candidates, count, stats, rng=None):
    """Weighted sampling without replacement. Randomness only breaks selection, not persistence."""
    rng = rng or random.SystemRandom()
    ranked=[]
    for ref in candidates:
        s=stats.get(ref,{})
        weight=(1+2*s.get('wrong_count',0))/(1+s.get('drawn_count',0))**2
        score=-math.log(max(rng.random(),1e-15))/weight
        ranked.append((score,ref))
    return [ref for _,ref in sorted(ranked)[:count]]

def generate(c, day, timestamp, subject='math'):
    # Caller holds BEGIN IMMEDIATE, so concurrent tabs create exactly one set.
    if c.execute('SELECT 1 FROM daily_batches WHERE day=? AND subject=?',(day,subject)).fetchone():return
    pool=[(r[0],r[1]) for r in c.execute('SELECT DISTINCT m.paper_id,m.number FROM memberships m JOIN folders f ON m.folder_id=f.id WHERE f.subject=? ORDER BY m.paper_id,m.number',(subject,))]
    if not pool:return  # Let newly collected questions become eligible later today.
    previous=c.execute('SELECT MAX(day) FROM daily_batches WHERE day<? AND subject=?',(day,subject)).fetchone()[0]
    recent={(r[0],r[1]) for r in c.execute('SELECT paper_id,number FROM daily_items WHERE day=? AND subject=?',(previous,subject))} if previous else set()
    fresh=[ref for ref in pool if ref not in recent]
    stats=statistics(c)
    selected=weighted_pick(fresh,min(5,len(fresh)),stats)
    repeated=weighted_pick([ref for ref in pool if ref in recent],min(5,len(pool))-len(selected),stats)
    selected+=repeated
    random.SystemRandom().shuffle(selected)
    c.execute('INSERT INTO daily_batches VALUES(?,?,?,?,?)',(day,timestamp,len(pool),len(repeated),subject))
    for position,(pid,n) in enumerate(selected,1):
        c.execute('INSERT INTO daily_items(day,position,paper_id,number,subject) VALUES(?,?,?,?,?)',(day,position,pid,n,subject))

def payload(c, day, papers, subject='math'):
    batch=c.execute('SELECT * FROM daily_batches WHERE day=? AND subject=?',(day,subject)).fetchone()
    stats=statistics(c)
    items=[]
    for row in c.execute('SELECT * FROM daily_items WHERE day=? AND subject=? ORDER BY position',(day,subject)):
        item=dict(row);p=papers[item['paper_id']];q=p['questions'][item['number']-1]
        items.append({**item,'title':p['title'],'difficulty':p['difficulty'],'image':q['image'],
                      'type':q['type'],**stats[(item['paper_id'],item['number'])]})
    history=[dict(r) for r in c.execute('''
      SELECT b.day,COUNT(i.position) AS total,
        SUM(CASE WHEN i.result IS NOT NULL THEN 1 ELSE 0 END) AS completed,
        SUM(CASE WHEN i.result='correct' THEN 1 ELSE 0 END) AS correct,
        SUM(CASE WHEN i.result='wrong' THEN 1 ELSE 0 END) AS wrong
      FROM daily_batches b JOIN daily_items i ON i.day=b.day AND i.subject=b.subject WHERE b.subject=?
      GROUP BY b.day ORDER BY b.day DESC LIMIT 7
    ''',(subject,))]
    return dict(subject=subject,day=day,generated=bool(batch),items=items,total=len(items),
                completed=sum(i['result'] is not None for i in items),
                correct=sum(i['result']=='correct' for i in items),wrong=sum(i['result']=='wrong' for i in items),
                pool_size=batch['pool_size'] if batch else c.execute('SELECT COUNT(*) FROM (SELECT DISTINCT m.paper_id,m.number FROM memberships m JOIN folders f ON f.id=m.folder_id WHERE f.subject=?)',(subject,)).fetchone()[0],
                repeated_previous=batch['repeated_previous'] if batch else 0,history=history)

def export_history(c):
    return [{**dict(batch),'items':[dict(i) for i in c.execute(
        'SELECT position,paper_id,number,result,answered_at FROM daily_items WHERE day=? AND subject=? ORDER BY position',(batch['day'],batch['subject']))]}
        for batch in c.execute('SELECT * FROM daily_batches ORDER BY day')]
