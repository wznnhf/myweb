from __future__ import annotations
import json, os, sqlite3, uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
import daily_review
import activity
from activity import ActivityRecord
import daily_practice
from daily_practice import RoundRecord as PracticeRoundRecord
import knowledge
import knowledge_sessions
from knowledge import KnowledgeBackup
import note_images
from migrate_subjects import migrate

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('CUOTI_DATA_DIR',ROOT/'data'))
DATA.mkdir(parents=True,exist_ok=True)
CATALOG=json.loads((ROOT/'data/catalog.json').read_text())
PAPERS={p['id']:p for p in CATALOG['papers']}
PAPERS.update(daily_practice.PAPERS)
for p in PAPERS.values():
    p.setdefault('subject','math')
    p['question_count']=len(p['questions'])
SUBJECT=Literal['math','408']
TOTAL_QUESTIONS=sum(p['question_count'] for p in PAPERS.values())
STATUS=Literal['unmarked','review','mastered']

def now(): return datetime.now(timezone.utc).isoformat()
@contextmanager
def db():
    con=sqlite3.connect(DATA/'study.sqlite3',timeout=15)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback(); raise
    finally: con.close()

with db() as c:
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS states(paper_id TEXT NOT NULL, number INTEGER NOT NULL,
      note TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'unmarked',
      revision INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
      PRIMARY KEY(paper_id,number));
    CREATE TABLE IF NOT EXISTS folders(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS memberships(folder_id TEXT NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
      paper_id TEXT NOT NULL,number INTEGER NOT NULL,PRIMARY KEY(folder_id,paper_id,number));
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    ''')

with db() as c:
    c.executescript(daily_review.SCHEMA)
    c.executescript(daily_practice.SCHEMA)
    c.executescript(note_images.SCHEMA)
    c.executescript(knowledge.SCHEMA)
    c.executescript(knowledge_sessions.SCHEMA)
    c.executescript(activity.SCHEMA)

migrate(DATA/'study.sqlite3')
with db() as c:activity.backfill(c,PAPERS)

app=FastAPI(title='拾题 · 本地试卷与错题本',docs_url=None,redoc_url=None,openapi_url=None)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver'])
@app.middleware('http')
async def local_access(request:Request,call_next):
    if request.method in ('POST','PUT','PATCH','DELETE'):
        origin=request.headers.get('origin')
        if request.headers.get('sec-fetch-site')=='cross-site' or (origin and origin.rstrip('/')!=str(request.base_url).rstrip('/')):
            return JSONResponse({'detail':'只接受本网页发起的修改'},status_code=403)
        limit=note_images.MAX_BACKUP_BYTES if request.url.path.startswith('/api/backup/') else 20*1024*1024
        if len(await request.body())>limit:
            return JSONResponse({'detail':f'请求不能超过 {limit//1024//1024} MB'},status_code=413)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    if request.url.path.startswith('/api'):response.headers['Cache-Control']='no-store'
    return response

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Ref(Strict):
    paper_id:str
    number:int=Field(ge=1)
class Edit(Strict):
    note:str|None=Field(default=None,max_length=100000)
    revision:int|None=Field(default=None,ge=0)
    status:STATUS|None=None
    activity_area:activity.QuestionArea='library'
class Name(Strict):
    name:str=Field(min_length=1,max_length=60)
class FolderName(Name):
    subject:SUBJECT='math'
class Membership(Ref):
    selected:bool
class StateRecord(Ref):
    note:str=Field(max_length=100000)
    status:STATUS
    revision:int=Field(default=0,ge=0)
    updated_at:str=''
class FolderRecord(Strict):
    subject:SUBJECT='math'
    id:str=Field(min_length=1,max_length=64)
    name:str=Field(min_length=1,max_length=60)
    created_at:str=''
class MemberRecord(Ref):
    folder_id:str
class DailyAnswer(Strict):
    result:Literal['correct','wrong']|None
class DailyItemRecord(Ref):
    position:int=Field(ge=1,le=5)
    result:Literal['correct','wrong']|None=None
    answered_at:str|None=None
class DailyBatchRecord(Strict):
    subject:SUBJECT='math'
    day:str
    created_at:str
    pool_size:int=Field(ge=1,le=TOTAL_QUESTIONS)
    repeated_previous:int=Field(ge=0,le=5)
    items:list[DailyItemRecord]=Field(min_length=1,max_length=5)
class ImageRecord(Strict):
    id:str=Field(pattern=r'^[a-f0-9]{64}$')
    data:str=Field(max_length=14*1024*1024)
class Backup(Strict):
    format:Literal['cuoti-backup']
    version:Literal[1,2,3,4,5,6,7,8,9]
    exported_at:str
    states:list[StateRecord]=Field(max_length=TOTAL_QUESTIONS)
    folders:list[FolderRecord]=Field(max_length=10000)
    memberships:list[MemberRecord]=Field(max_length=100000)
    last_read:Ref|None=None
    last_reads:dict[SUBJECT,Ref]=Field(default_factory=dict)
    daily_reviews:list[DailyBatchRecord]=Field(default_factory=list,max_length=40000)
    images:list[ImageRecord]=Field(default_factory=list,max_length=10000)
    knowledge:KnowledgeBackup|None=None
    daily_practice:list[PracticeRoundRecord]=Field(default_factory=list,max_length=1000)
    activity:list[ActivityRecord]=Field(default_factory=list,max_length=1000000)

def check_ref(pid,n):
    if pid not in PAPERS or not 1<=n<=PAPERS[pid]['question_count']: raise HTTPException(404,'题目不存在')
def ensure_state(c,pid,n):
    c.execute('INSERT OR IGNORE INTO states(paper_id,number,updated_at) VALUES(?,?,?)',(pid,n,now()))
def state(c,pid,n):
    row=c.execute('SELECT * FROM states WHERE paper_id=? AND number=?',(pid,n)).fetchone()
    s=dict(row) if row else dict(paper_id=pid,number=n,note='',status='unmarked',revision=0,updated_at='')
    s['folder_ids']=[r[0] for r in c.execute('SELECT folder_id FROM memberships WHERE paper_id=? AND number=?',(pid,n))]
    return s

def export(c):
    last=c.execute("SELECT value FROM settings WHERE key='last_read:math'").fetchone()
    states=[dict(r) for r in c.execute('SELECT * FROM states')]
    return dict(format='cuoti-backup',version=9,activity=activity.export(c),daily_practice=daily_practice.export(c),knowledge=knowledge.export(c),images=note_images.export_images(c,states),last_reads={r[0].split(':',1)[1]:json.loads(r[1]) for r in c.execute("SELECT key,value FROM settings WHERE key LIKE 'last_read:%'")},exported_at=now(),daily_reviews=daily_review.export_history(c),
                states=states,
                folders=[dict(r) for r in c.execute('SELECT * FROM folders')],
                memberships=[dict(r) for r in c.execute('SELECT * FROM memberships')],
                last_read=json.loads(last[0]) if last else None)

@app.get('/api/library')
def library(subject:SUBJECT='math'):
    papers={pid:p for pid,p in PAPERS.items() if p['subject']==subject}
    with db() as c:
        states=[dict(r) for r in c.execute("SELECT paper_id,number,status,revision,note != '' AS has_note FROM states") if r['paper_id'] in papers]
        memberships=[dict(r) for r in c.execute('SELECT * FROM memberships') if r['paper_id'] in papers]
        folders=[dict(r) for r in c.execute('SELECT f.*,COUNT(m.number) AS count FROM folders f LEFT JOIN memberships m ON m.folder_id=f.id WHERE f.subject=? GROUP BY f.id ORDER BY f.created_at,f.id',(subject,))]
        last=c.execute("SELECT value FROM settings WHERE key=?",('last_read:'+subject,)).fetchone()
    summaries=[{k:v for k,v in p.items() if k not in ('questions','source','sha256')} for p in papers.values()]
    return dict(subject=subject,papers=[p for p in summaries if p.get('source_kind')!='exercise_book'],
                exercise_books=[p for p in summaries if p.get('source_kind')=='exercise_book'],
                states=states,memberships=memberships,folders=folders,last_read=json.loads(last[0]) if last else None)

@app.get('/api/daily-practice')
def practice_overview(round_id:str|None=None):
    with db() as c:return daily_practice.overview(c,round_id)

@app.get('/api/activity')
def activity_calendar(subject:SUBJECT='math',area:activity.Scope='all',year:int|None=None):
    with db() as c:return activity.calendar(c,subject,area,year)

@app.post('/api/daily-practice/start')
def practice_start():
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        rid=daily_practice.start(c)
        return daily_practice.overview(c,rid)

@app.post('/api/daily-practice/next-round')
def practice_next():
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        rid=daily_practice.start(c,next_round=True)
        return daily_practice.overview(c,rid)

@app.get('/api/daily-practice/rounds/{rid}/days/{day}')
def practice_day(rid:str,day:str):
    with db() as c:return daily_practice.day_payload(c,rid,day)

@app.put('/api/daily-practice/rounds/{rid}/position')
def practice_position(rid:str,body:daily_practice.Position):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        daily_practice.mark_position(c,rid,body.day,body.position)
    return dict(ok=True)

@app.put('/api/daily-practice/rounds/{rid}/days/{day}/items/{position}')
def practice_answer(rid:str,day:str,position:int,body:daily_practice.Answer):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        daily_practice.choose(c,rid,day,position,body.choice)
        row=daily_practice.item(c,rid,day,position)
        if body.choice and '_' not in body.choice:
            activity.question(c,PAPERS,row['paper_id'],row['number'],'daily_practice',daily_practice.now())
        return daily_practice.day_payload(c,rid,day)

@app.post('/api/daily-practice/rounds/{rid}/days/{day}/submit')
def practice_submit(rid:str,day:str):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        changed=daily_practice.submit(c,rid,day)
        payload=daily_practice.day_payload(c,rid,day)
        if changed:
            for row in payload['items']:
                ensure_state(c,row['paper_id'],row['number'])
                c.execute('UPDATE states SET status=?,updated_at=? WHERE paper_id=? AND number=?',
                    ('mastered' if row['result']=='correct' else 'review',payload['submitted_at'],row['paper_id'],row['number']))
        return payload

@app.get('/api/daily-practice/rounds/{rid}/days/{day}/items/{position}/analysis.pdf')
def practice_analysis(rid:str,day:str,position:int):
    with db() as c:
        daily_practice.item(c,rid,day,position)
        if not daily_practice.submitted(c,rid,day):
            raise HTTPException(403,'整组交卷后开放解析')
    return FileResponse(ROOT/daily_practice.ANSWERS['source'],media_type='application/pdf',
                        headers={'Cache-Control':'no-store'})

@app.get('/api/daily-review')
def get_daily_review(subject:SUBJECT='math'):
    with db() as c:return daily_review.payload(c,daily_review.today(),PAPERS,subject)

@app.post('/api/daily-review')
def generate_daily_review(subject:SUBJECT='math'):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        day=daily_review.today()
        daily_review.generate(c,day,now(),subject)
        return daily_review.payload(c,day,PAPERS,subject)

@app.put('/api/daily-review/{day}/items/{position}')
def answer_daily_review(day:str,position:int,body:DailyAnswer,subject:SUBJECT='math'):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if day!=daily_review.today():raise HTTPException(409,'日期已变化，请返回每日回顾，打开今天的题目。')
        row=c.execute('SELECT * FROM daily_items WHERE day=? AND subject=? AND position=?',(day,subject,position)).fetchone()
        if not row:raise HTTPException(404,'这道题不在今天的回顾列表中')
        if row['result']!=body.result:
            c.execute('UPDATE daily_items SET result=?,answered_at=? WHERE day=? AND subject=? AND position=?',
                      (body.result,now() if body.result else None,day,subject,position))
            if body.result is not None:
                ensure_state(c,row['paper_id'],row['number'])
                c.execute('UPDATE states SET status=?,updated_at=? WHERE paper_id=? AND number=?',
                          ('mastered' if body.result=='correct' else 'review',now(),row['paper_id'],row['number']))
        if body.result is not None:activity.question(c,PAPERS,row['paper_id'],row['number'],'daily_review',now())
        return daily_review.payload(c,day,PAPERS,subject)

@app.get('/api/papers/{pid}')
def paper(pid:str):
    if pid not in PAPERS: raise HTTPException(404,'试卷不存在')
    return PAPERS[pid]
@app.get('/api/questions/{pid}/{n}')
def question(pid:str,n:int):
    check_ref(pid,n)
    with db() as c:return {**PAPERS[pid]['questions'][n-1],**state(c,pid,n)}
@app.patch('/api/questions/{pid}/{n}')
def edit_question(pid:str,n:int,edit:Edit):
    check_ref(pid,n)
    if edit.activity_area=='daily_practice' and PAPERS[pid].get('source_kind')!='exercise_book':raise HTTPException(400,'每日一练只使用题册中的题目')
    with db() as c:
        c.execute('BEGIN IMMEDIATE');ensure_state(c,pid,n)
        before=state(c,pid,n)
        if edit.note is not None:
            if edit.revision!=before['revision']:
                raise HTTPException(409,'笔记已在其他页面更新，请先复制当前草稿，再重新加载核对。')
            c.execute('UPDATE states SET note=?,revision=revision+1,updated_at=? WHERE paper_id=? AND number=?',(edit.note,now(),pid,n))
        if edit.status is not None:c.execute('UPDATE states SET status=?,updated_at=? WHERE paper_id=? AND number=?',(edit.status,now(),pid,n))
        if edit.status in ('review','mastered'):activity.question(c,PAPERS,pid,n,edit.activity_area,now())
        return state(c,pid,n)

@app.post('/api/questions/{pid}/{n}/images')
async def upload_note_image(pid:str,n:int,request:Request):
    check_ref(pid,n)
    data=await request.body()
    image_id,media_type=note_images.inspect_image(data)
    with db() as c:
        c.execute('INSERT OR IGNORE INTO note_images VALUES(?,?,?)',(image_id,media_type,data))
    return dict(url='/api/note-images/'+image_id)

@app.get('/api/note-images/{image_id}')
def get_note_image(image_id:str):
    with db() as c:
        row=c.execute('SELECT media_type,data FROM note_images WHERE id=?',(image_id,)).fetchone()
    if not row:raise HTTPException(404,'笔记图片不存在')
    return Response(row['data'],media_type=row['media_type'])

@app.post('/api/folders')
def create_folder(body:FolderName):
    name=body.name.strip()
    if not name:raise HTTPException(400,'文件夹名称不能为空')
    with db() as c:
        try:
            fid=str(uuid.uuid4());c.execute('INSERT INTO folders(id,name,created_at,subject) VALUES(?,?,?,?)',(fid,name,now(),body.subject))
        except sqlite3.IntegrityError:raise HTTPException(409,'已有同名文件夹')
    return dict(id=fid,name=name)
@app.patch('/api/folders/{fid}')
def rename_folder(fid:str,body:Name):
    name=body.name.strip()
    if not name:raise HTTPException(400,'文件夹名称不能为空')
    with db() as c:
        try:r=c.execute('UPDATE folders SET name=? WHERE id=?',(name,fid))
        except sqlite3.IntegrityError:raise HTTPException(409,'已有同名文件夹')
        if not r.rowcount:raise HTTPException(404,'文件夹不存在')
    return {'ok':True}
@app.delete('/api/folders/{fid}')
def delete_folder(fid:str):
    with db() as c:c.execute('DELETE FROM folders WHERE id=?',(fid,))
    return {'ok':True}
@app.put('/api/folders/{fid}/membership')
def membership(fid:str,body:Membership):
    check_ref(body.paper_id,body.number)
    with db() as c:
        folder=c.execute('SELECT subject FROM folders WHERE id=?',(fid,)).fetchone()
        if not folder:raise HTTPException(404,'文件夹不存在')
        if folder['subject']!=PAPERS[body.paper_id]['subject']:raise HTTPException(400,'数学和 408 的错题夹不能混用')
        if body.selected:
            ensure_state(c,body.paper_id,body.number)
            c.execute('INSERT OR IGNORE INTO memberships VALUES(?,?,?)',(fid,body.paper_id,body.number))
            c.execute("UPDATE states SET status='review',updated_at=? WHERE paper_id=? AND number=? AND status='unmarked'",(now(),body.paper_id,body.number))
        else:c.execute('DELETE FROM memberships WHERE folder_id=? AND paper_id=? AND number=?',(fid,body.paper_id,body.number))
        return state(c,body.paper_id,body.number)
@app.put('/api/last-read')
def last_read(body:Ref):
    check_ref(body.paper_id,body.number)
    with db() as c:c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)",('last_read:'+PAPERS[body.paper_id]['subject'],body.model_dump_json()))
    return {'ok':True}
@app.get('/api/backup')
def backup():
    with db() as c:
        c.execute('BEGIN')  # One snapshot, even if another tab submits a score.
        content=export(c)
    return JSONResponse(content,headers={'Content-Disposition':'attachment; filename="cuoti-backup.json"'})

def validate_backup(body:Backup):
    if body.version>=7:
        if 'activity' not in body.model_fields_set:raise HTTPException(400,'新版备份缺少学习打卡记录')
        activity.validate(body.activity,PAPERS,knowledge.ALL_CARDS)
    if body.version>=8 and (body.knowledge is None or 'sessions' not in body.knowledge.model_fields_set):raise HTTPException(400,'新版备份缺少连续复习队列')
    if body.version>=5:
        if body.knowledge is None:raise HTTPException(400,'新版备份缺少考点学习记录')
        knowledge.validate_backup(body.knowledge)
    elif body.knowledge is not None:
        raise HTTPException(400,'备份版本与考点学习记录不匹配')
    if body.version>=6:
        if 'daily_practice' not in body.model_fields_set:raise HTTPException(400,'新版备份缺少每日一练记录')
        if body.version>=9:
            for round_record in body.daily_practice:
                if 'submissions' not in round_record.model_fields_set or any(
                    not {'choice','selected_at'} <= item.model_fields_set for item in round_record.items):
                    raise HTTPException(400,'新版备份缺少选项或交卷记录')
        daily_practice.validate_backup(body.daily_practice)
    elif body.daily_practice:
        raise HTTPException(400,'备份版本与每日一练记录不匹配')
    images=note_images.validate_images(body.images,[s.model_dump() for s in body.states],body.version)
    if body.version>=2 and 'daily_reviews' not in body.model_fields_set:
        raise HTTPException(400,'新版备份缺少每日回顾记录')
    if body.version==1 and body.daily_reviews:
        raise HTTPException(400,'备份版本与每日回顾数据不匹配')
    days=[]
    for batch in body.daily_reviews:
        try: parsed=date.fromisoformat(batch.day)
        except ValueError:raise HTTPException(400,'回顾日期格式不正确')
        if parsed.isoformat()!=batch.day or batch.day>daily_review.today():raise HTTPException(400,'回顾日期无效或晚于今天')
        days.append((batch.day,batch.subject))
        positions=[i.position for i in batch.items]
        refs={(i.paper_id,i.number) for i in batch.items}
        if sorted(positions)!=list(range(1,len(batch.items)+1)) or len(refs)!=len(batch.items):
            raise HTTPException(400,'每日回顾的题目重复或顺序不完整')
        if len(batch.items)>batch.pool_size or batch.repeated_previous>len(batch.items):
            raise HTTPException(400,'每日回顾的数量记录不一致')
        for item in batch.items:
            if item.paper_id not in PAPERS or not 1<=item.number<=PAPERS[item.paper_id]['question_count'] or PAPERS[item.paper_id]['subject']!=batch.subject:raise HTTPException(400,'每日回顾包含不属于这批试卷的题目')
            if bool(item.answered_at)!=(item.result is not None):raise HTTPException(400,'每日回顾的作答记录不完整')
    if len(set(days))!=len(days):raise HTTPException(400,'备份包含重复的回顾日期')
    fids=[f.id for f in body.folders];names=[(f.subject,f.name.strip()) for f in body.folders]
    refs=[(s.paper_id,s.number) for s in body.states]
    if len(set(fids))!=len(fids) or len(set(names))!=len(names) or not all(name for _,name in names) or len(set(refs))!=len(refs):
        raise HTTPException(400,'备份包含重复或空白记录')
    for r in [*body.states,*body.memberships,*body.last_reads.values(),*([body.last_read] if body.last_read else [])]:
        if r.paper_id not in PAPERS or not 1<=r.number<=PAPERS[r.paper_id]['question_count']:raise HTTPException(400,'备份包含不属于这批试卷的题目')
    for subject,ref in body.last_reads.items():
        if PAPERS[ref.paper_id]['subject']!=subject:raise HTTPException(400,'阅读进度的科目不匹配')
    for m in body.memberships:
        if m.folder_id not in fids:raise HTTPException(400,'备份中的文件夹关联不完整')
        if next(f.subject for f in body.folders if f.id==m.folder_id)!=PAPERS[m.paper_id]['subject']:raise HTTPException(400,'备份中的错题夹科目不匹配')
        if (m.paper_id,m.number) not in refs:raise HTTPException(400,'备份中的题目记录不完整')
    if len({(m.folder_id,m.paper_id,m.number) for m in body.memberships})!=len(body.memberships):raise HTTPException(400,'备份包含重复收藏')
    return images

@app.post('/api/backup/preview')
def preview_backup(body:Backup):
    validate_backup(body)
    with db() as c:
        existing={(r[0],r[1]) for r in c.execute('SELECT paper_id,number FROM states')}
        if body.knowledge:knowledge.check_restore_conflicts(c,body.knowledge)
        daily_practice.check_restore_conflicts(c,body.daily_practice)
    return dict(activity_records=len(body.activity) if body.version>=7 else 0,practice_rounds=len(body.daily_practice),practice_answers=sum(i.result is not None or i.choice is not None for r in body.daily_practice for i in r.items),knowledge_cards=len(body.knowledge.states) if body.knowledge else 0,knowledge_reviews=len(body.knowledge.reviews) if body.knowledge else 0,knowledge_sessions=len(body.knowledge.sessions) if body.knowledge else 0,images=len(body.images),review_days=len(body.daily_reviews),questions=len(body.states),folders=len(body.folders),memberships=len(body.memberships),overwrites=sum((s.paper_id,s.number) in existing for s in body.states))
@app.post('/api/backup/restore')
def restore(body:Backup):
    images=validate_backup(body)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if body.knowledge:knowledge.check_restore_conflicts(c,body.knowledge)
        daily_practice.check_restore_conflicts(c,body.daily_practice)
        backup_dir=DATA/'backups';backup_dir.mkdir(exist_ok=True)
        save=backup_dir/f'before-restore-{datetime.now().strftime("%Y%m%d-%H%M%S-%f")}.json'
        save.write_text(json.dumps(export(c),ensure_ascii=False,indent=2))
        for image_id,(media_type,data) in images.items():
            c.execute('INSERT OR IGNORE INTO note_images VALUES(?,?,?)',(image_id,media_type,data))
        # Map by ID first, then by name; preserve unrelated local folders.
        mapping={}
        for f in body.folders:
            row=c.execute('SELECT id FROM folders WHERE subject=? AND (id=? OR name=?) ORDER BY id=? DESC',(f.subject,f.id,f.name.strip(),f.id)).fetchone()
            fid=row[0] if row else (str(uuid.uuid4()) if c.execute('SELECT 1 FROM folders WHERE id=?',(f.id,)).fetchone() else f.id)
            if not row:c.execute('INSERT INTO folders(id,name,created_at,subject) VALUES(?,?,?,?)',(fid,f.name.strip(),f.created_at or now(),f.subject))
            mapping[f.id]=fid
        for s in body.states:
            ensure_state(c,s.paper_id,s.number)
            c.execute('UPDATE states SET note=?,status=?,revision=revision+1,updated_at=? WHERE paper_id=? AND number=?',(s.note,s.status,now(),s.paper_id,s.number))
            c.execute('DELETE FROM memberships WHERE paper_id=? AND number=?',(s.paper_id,s.number))
        for m in body.memberships:c.execute('INSERT OR IGNORE INTO memberships VALUES(?,?,?)',(mapping[m.folder_id],m.paper_id,m.number))
        # Version 1 imports leave daily history untouched. Version 2 replaces matching
        # days as a whole to retain the five-question invariant, preserving other days.
        for batch in body.daily_reviews:
            c.execute('DELETE FROM daily_batches WHERE day=? AND subject=?',(batch.day,batch.subject))
            c.execute('INSERT INTO daily_batches VALUES(?,?,?,?,?)',
                      (batch.day,batch.created_at,batch.pool_size,batch.repeated_previous,batch.subject))
            for item in batch.items:
                c.execute('INSERT INTO daily_items VALUES(?,?,?,?,?,?,?)',
                          (batch.day,item.position,item.paper_id,item.number,item.result,item.answered_at,batch.subject))
        readings=dict(body.last_reads)
        if body.last_read:readings.setdefault(PAPERS[body.last_read.paper_id]['subject'],body.last_read)
        for subject,ref in readings.items():c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('last_read:'+subject,ref.model_dump_json()))
        if body.knowledge:knowledge.restore(c,body.knowledge)
        daily_practice.restore(c,body.daily_practice)
        if body.version>=7:activity.restore(c,body.activity)
        activity.backfill(c,PAPERS)
    return dict(ok=True,safety_backup=save.name)

@app.get('/api/knowledge/overview')
def knowledge_overview():
    with db() as c:return knowledge.overview(c)

@app.get('/api/knowledge/catalog')
def knowledge_catalog(field:knowledge.FieldName|None=None,chapter:str|None=None,q:str='',status:Literal['new','due','scheduled']|None=None):
    with db() as c:return knowledge.catalog(c,field,chapter,q,status)

@app.get('/api/knowledge/cards/{card_id}')
def knowledge_detail(card_id:str):
    with db() as c:return knowledge.detail(c,card_id)

@app.post('/api/knowledge/draw')
def knowledge_draw(body:knowledge.DrawRequest):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        return knowledge.draw(c,body)

@app.post('/api/knowledge/draws/{draw_id}/reveal')
def knowledge_reveal(draw_id:str):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        return knowledge.reveal(c,draw_id)

@app.post('/api/knowledge/draws/{draw_id}/score')
def knowledge_score(draw_id:str,body:knowledge.ScoreRequest):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        result=knowledge.score(c,draw_id,body)
        row=c.execute('SELECT card_id,reviewed_at FROM knowledge_reviews WHERE id=?',(draw_id,)).fetchone()
        activity.record(c,'408','knowledge','k:'+row['card_id'],row['reviewed_at'])
        return result

@app.post('/api/knowledge/reviews/{review_id}/undo')
def knowledge_undo(review_id:str,body:knowledge.RevisionRequest):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        return knowledge.undo(c,review_id,body.revision)

@app.put('/api/knowledge/goals/{field}')
def knowledge_goal(field:knowledge.FieldName,body:knowledge.GoalRequest):
    with db() as c:
        c.execute('INSERT OR REPLACE INTO knowledge_goals VALUES(?,?)',(field,body.target))
        return knowledge.overview(c)

@app.get('/api/knowledge/outline')
def knowledge_outline():
    return FileResponse(ROOT/'data/knowledge/outline-2027.pdf',media_type='application/pdf')

@app.post('/api/knowledge/sessions')
def knowledge_start_session(body:knowledge_sessions.StartRequest):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        return knowledge_sessions.start(c,body)

@app.get('/api/knowledge/sessions/{session_id}')
def knowledge_get_session(session_id:str):
    with db() as c:return knowledge_sessions.get(c,session_id)

@app.put('/api/knowledge/sessions/{session_id}/position')
def knowledge_session_position(session_id:str,body:knowledge_sessions.PositionRequest):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        return knowledge_sessions.position(c,session_id,body.position)

@app.post('/api/knowledge/sessions/{session_id}/end')
def knowledge_end_session(session_id:str):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        return knowledge_sessions.end(c,session_id)

@app.get('/api/knowledge/source/{field}')
def knowledge_source(field:knowledge.FieldName):
    return FileResponse(ROOT/'data/knowledge/sources'/f'{field}.pdf',media_type='application/pdf')

@app.get('/api/knowledge/export/{kind}')
def knowledge_export(kind:Literal['cards','coverage']):
    import csv,io
    out=io.StringIO();writer=csv.writer(out)
    writer.writerow(['科目','章节','标题','源资料考频','卡片类型','结论','PDF页码'])
    for card in knowledge.CARDS.values():writer.writerow([knowledge.SUBJECTS[card['field']]['title'],card['chapter'],card['title'],card['frequency'],card['card_type'],'\n'.join(card['answer']),','.join(map(str,card['pdf_pages']))])
    return Response(('\ufeff'+out.getvalue()).encode('utf-8'),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="408-memory-cards.csv"'})

@app.get('/api/papers/{pid}/pdf')
def pdf(pid:str):
    if pid not in PAPERS:raise HTTPException(404,'试卷不存在')
    path=ROOT.parent/PAPERS[pid]['source']
    if not path.exists():raise HTTPException(404,'原卷文件已移动，请放回原位置')
    return FileResponse(path,media_type='application/pdf')
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
app.mount('/assets/questions',StaticFiles(directory=ROOT/'data/questions'),name='questions')
@app.get('/')
@app.get('/papers/{pid}/questions/{n}')
@app.get('/daily-review')
@app.get('/daily-practice')
@app.get('/knowledge-draw')
@app.get('/mistakes')
@app.get('/mistakes/{fid}')
def frontend():return FileResponse(ROOT/'static/index.html')
