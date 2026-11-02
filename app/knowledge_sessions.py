"""Durable, deduplicated study queues; scoring reuses knowledge.py's FSRS ledger."""
import random
import uuid
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field
import knowledge as k

SCHEMA='''
CREATE TABLE IF NOT EXISTS knowledge_sessions(
 id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, field TEXT, chapter_id TEXT,
 mode TEXT NOT NULL, limit_count INTEGER NOT NULL, created_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'active', cursor INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS knowledge_active_session ON knowledge_sessions(status) WHERE status='active';
CREATE TABLE IF NOT EXISTS knowledge_session_items(
 session_id TEXT NOT NULL REFERENCES knowledge_sessions(id) ON DELETE CASCADE,
 position INTEGER NOT NULL,card_id TEXT NOT NULL,draw_id TEXT,
 PRIMARY KEY(session_id,position),UNIQUE(session_id,card_id)
);
'''
class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class StartRequest(Strict):
    request_id:str=Field(min_length=1,max_length=100)
    field:Literal['ds','co','os','net']|None=None
    chapter_id:str|None=Field(default=None,max_length=100)
    mode:Literal['mixed','due','new','chapter']='mixed'
    limit:int=Field(default=20,ge=1,le=100,strict=True)
class PositionRequest(Strict):position:int=Field(ge=1,le=100,strict=True)
class StoredItem(Strict):
    position:int=Field(ge=1,le=100,strict=True)
    card_id:str
    draw_id:str|None=None
class StoredSession(Strict):
    id:str=Field(min_length=1,max_length=100)
    request_id:str=Field(min_length=1,max_length=100)
    field:Literal['ds','co','os','net']|None=None
    chapter_id:str|None=None
    mode:Literal['mixed','due','new','chapter']
    limit_count:int=Field(ge=1,le=100,strict=True)
    created_at:str
    status:Literal['active','completed','ended']
    cursor:int=Field(ge=1,le=100,strict=True)
    items:list[StoredItem]=Field(min_length=1,max_length=100)

def rows(c,sid):
    return c.execute('''SELECT i.*,d.status AS draw_status,d.mode AS draw_mode,r.rating,r.undone
      FROM knowledge_session_items i LEFT JOIN knowledge_draws d ON d.id=i.draw_id
      LEFT JOIN knowledge_reviews r ON r.id=i.draw_id WHERE session_id=? ORDER BY position''',(sid,)).fetchall()
def done(item):return item['draw_status']=='scored' and item['rating'] is not None and not item['undone']
def get(c,sid,at=None):
    at=at or k.now();header=c.execute('SELECT * FROM knowledge_sessions WHERE id=?',(sid,)).fetchone()
    if not header:raise HTTPException(404,'这组复习不存在。')
    items=[];current=None
    for row in rows(c,sid):
        card=k.CARDS[row['card_id']]
        items.append(dict(position=row['position'],card_id=card['id'],title=card['title'],field=card['field'],chapter=card['chapter'],chapter_id=card['chapter_id'],rating=row['rating'] if done(row) else None,mode=row['draw_mode']))
        if row['position']==header['cursor'] and row['draw_id']:
            draw=c.execute('SELECT * FROM knowledge_draws WHERE id=?',(row['draw_id'],)).fetchone()
            if draw and draw['status'] in ('pending','scored'):current=k.draw_payload(c,draw,at)
    complete=sum(i['rating'] is not None for i in items)
    return dict(**dict(header),items=items,total=len(items),completed=complete,remaining=len(items)-complete,current=current,
                counts=[sum(i['rating']==r for i in items) for r in range(1,5)])
def summary(c):
    row=c.execute("SELECT id FROM knowledge_sessions WHERE status='active' LIMIT 1").fetchone()
    if not row:return None
    value=get(c,row['id']);return {key:value[key] for key in ['id','field','chapter_id','mode','cursor','total','completed','remaining']}
def start(c,body,at=None):
    at=at or k.now()
    if body.chapter_id and not any(ch['id']==body.chapter_id for s in k.SUBJECTS.values() if not body.field or s['id']==body.field for ch in s['chapters']):raise HTTPException(400,'章节与科目不匹配。')
    if body.mode=='chapter' and not body.chapter_id:raise HTTPException(400,'请选择要练习的章节。')
    existing=c.execute('SELECT * FROM knowledge_sessions WHERE request_id=?',(body.request_id,)).fetchone()
    if existing:
        if (existing['field'],existing['chapter_id'],existing['mode'],existing['limit_count'])!=(body.field,body.chapter_id,body.mode,body.limit):raise HTTPException(409,'这次开始标识已用于另一组练习。')
        return get(c,existing['id'],at)
    active=summary(c)
    if active:raise HTTPException(409,'还有一组未结束的复习，请继续该组，或先结束后再选择新范围。')
    candidates=[]
    for card in k.CARDS.values():
        if body.field and body.field!=card['field'] or body.chapter_id and body.chapter_id!=card['chapter_id']:continue
        m=k.memory(k.state(c,card['id']),at)
        if body.mode=='due' and m['status']!='due' or body.mode=='new' and m['status']!='new' or body.mode=='mixed' and m['status']=='scheduled':continue
        candidates.append((card,m))
    if not candidates:raise HTTPException(409,'这个范围目前没有可复习的卡片，可选择其他范围或按章节练习。')
    # Interleave subjects/chapters and preserve urgency, with no repeats in a set.
    random.SystemRandom().shuffle(candidates)
    candidates.sort(key=lambda x:(0 if x[1]['status']=='due' else 1 if x[1]['status']=='new' else 2,x[1]['due'] or ''))
    def spread(pairs):
        groups={}
        for pair in pairs:groups.setdefault((pair[0]['field'],pair[0]['chapter_id']),[]).append(pair)
        ordered=[]
        while any(groups.values()):
            for group in groups.values():
                if group:ordered.append(group.pop(0))
        return ordered
    if body.mode=='new':candidates=spread(candidates)
    elif body.mode=='mixed':
        due=[pair for pair in candidates if pair[1]['status']=='due']
        fresh=spread([pair for pair in candidates if pair[1]['status']=='new'])
        candidates=[]
        while due or fresh:
            if due:
                candidates.extend(due[:4]);del due[:4]
            if fresh:candidates.append(fresh.pop(0))
    selected=candidates[:body.limit];sid=str(uuid.uuid4())
    c.execute('INSERT INTO knowledge_sessions(id,request_id,field,chapter_id,mode,limit_count,created_at) VALUES(?,?,?,?,?,?,?)',(sid,body.request_id,body.field,body.chapter_id,body.mode,body.limit,k.stamp(at)))
    c.executemany('INSERT INTO knowledge_session_items(session_id,position,card_id) VALUES(?,?,?)',[(sid,i,card['id']) for i,(card,m) in enumerate(selected,1)])
    return get(c,sid,at)
def position(c,sid,pos,at=None):
    at=at or k.now();session=get(c,sid,at)
    row=c.execute('SELECT * FROM knowledge_session_items WHERE session_id=? AND position=?',(sid,pos)).fetchone()
    if not row:raise HTTPException(404,'该位置不在这组复习内。')
    draw=c.execute('SELECT * FROM knowledge_draws WHERE id=?',(row['draw_id'],)).fetchone() if row['draw_id'] else None
    if not draw or draw['status'] not in ('pending','scored'):
        if session['status']!='active':raise HTTPException(409,'本组已结束，请从首页开始新一组。')
        draw=c.execute("SELECT * FROM knowledge_draws WHERE card_id=? AND status='pending'",(row['card_id'],)).fetchone()
        if not draw:
            card=k.CARDS[row['card_id']];saved=k.state(c,card['id']);m=k.memory(saved,at)
            kind='practice' if m['status']=='scheduled' else 'new' if m['status']=='new' else 'due'
            c.execute('INSERT OR IGNORE INTO knowledge_states(card_id,seen_at) VALUES(?,?)',(card['id'],k.stamp(at)))
            did=str(uuid.uuid4())
            c.execute('INSERT INTO knowledge_draws(id,request_id,card_id,field,mode,kind,expected_revision,created_at) VALUES(?,?,?,?,?,?,?,?)',(did,'session:'+sid+':'+str(pos)+':'+str(saved['revision']),card['id'],card['field'],'practice' if kind=='practice' else 'review',kind,saved['revision'],k.stamp(at)))
            draw=c.execute('SELECT * FROM knowledge_draws WHERE id=?',(did,)).fetchone()
        c.execute('UPDATE knowledge_session_items SET draw_id=? WHERE session_id=? AND position=?',(draw['id'],sid,pos))
    c.execute('UPDATE knowledge_sessions SET cursor=? WHERE id=?',(pos,sid))
    return get(c,sid,at)
def update(c,draw_id):
    for row in c.execute("SELECT s.id,s.status FROM knowledge_sessions s JOIN knowledge_session_items i ON s.id=i.session_id WHERE i.draw_id=?",(draw_id,)).fetchall():
        if row['status']=='active' and all(done(i) for i in rows(c,row['id'])):c.execute("UPDATE knowledge_sessions SET status='completed' WHERE id=?",(row['id'],))
        elif row['status']=='completed' and not all(done(i) for i in rows(c,row['id'])):
            status='ended' if c.execute("SELECT 1 FROM knowledge_sessions WHERE status='active'").fetchone() else 'active'
            c.execute('UPDATE knowledge_sessions SET status=? WHERE id=?',(status,row['id']))
def end(c,sid):
    get(c,sid);c.execute("UPDATE knowledge_sessions SET status='ended' WHERE id=? AND status='active'",(sid,));return get(c,sid)
def export(c):
    out=[]
    for row in c.execute('SELECT * FROM knowledge_sessions ORDER BY rowid'):
        out.append(dict(**dict(row),items=[dict(i) for i in c.execute('SELECT position,card_id,draw_id FROM knowledge_session_items WHERE session_id=? ORDER BY position',(row['id'],))]))
    return out
def validate(records,draws):
    ids=set();requests=set();active=0
    for s in records:
        if s.id in ids or s.request_id in requests:raise ValueError('重复的连续复习标识')
        ids.add(s.id);requests.add(s.request_id);k.parse(s.created_at)
        if s.status=='active':active+=1
        if active>1:raise ValueError('存在多组进行中的连续复习')
        if [i.position for i in s.items]!=list(range(1,len(s.items)+1)) or not 1<=s.cursor<=len(s.items) or len(s.items)>s.limit_count:raise ValueError('复习队列位置无效')
        if len({i.card_id for i in s.items})!=len(s.items):raise ValueError('复习队列有重复卡片')
        for i in s.items:
            card=k.CARDS.get(i.card_id)
            if not card or s.field and card['field']!=s.field or s.chapter_id and card['chapter_id']!=s.chapter_id:raise ValueError('复习队列超出指定范围')
            d=draws.get(i.draw_id)
            if i.draw_id and (not d or d.card_id!=i.card_id):raise ValueError('复习队列与学习记录不一致')
            if s.status=='completed' and (not d or d.status!='scored'):raise ValueError('已完成队列包含未完成卡片')
def restore(c,records):
    # An older backup can replace draw records without erasing a local queue.
    for s in c.execute('SELECT id,status FROM knowledge_sessions').fetchall():
        broken=c.execute('SELECT 1 FROM knowledge_session_items i LEFT JOIN knowledge_draws d ON d.id=i.draw_id WHERE i.session_id=? AND i.draw_id IS NOT NULL AND d.id IS NULL',(s['id'],)).fetchone()
        if broken:
            c.execute("UPDATE knowledge_sessions SET status='ended' WHERE id=?",(s['id'],))
            c.execute('UPDATE knowledge_session_items SET draw_id=NULL WHERE session_id=? AND draw_id NOT IN (SELECT id FROM knowledge_draws)',(s['id'],))
    if any(s.status=='active' for s in records):c.execute("UPDATE knowledge_sessions SET status='ended' WHERE status='active'")
    for s in records:
        c.execute('DELETE FROM knowledge_sessions WHERE id=?',(s.id,))
        header=s.model_dump(exclude={'items'})
        c.execute('INSERT INTO knowledge_sessions('+','.join(header)+') VALUES('+','.join('?' for _ in header)+')',tuple(header.values()))
        c.executemany('INSERT INTO knowledge_session_items VALUES(?,?,?,?)',[(s.id,i.position,i.card_id,i.draw_id) for i in s.items])
