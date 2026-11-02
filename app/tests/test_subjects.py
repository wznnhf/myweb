"""Subject boundaries, high question numbers, legacy migration and backup roundtrips."""
import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
from test_app import server
from fastapi.testclient import TestClient
from migrate_subjects import migrate

class SubjectTests(unittest.TestCase):
 def setUp(self):
  self.client=TestClient(server.app)
  with server.db() as c:
   for table in ['study_activity','daily_items','daily_batches','memberships','states','folders','settings']:c.execute('DELETE FROM '+table)
  self.math=next(p['id'] for p in server.PAPERS.values() if p['subject']=='math')
  self.cs=next(p['id'] for p in server.PAPERS.values() if p['subject']=='408')
 def make_folder(self,subject):
  r=self.client.post('/api/folders',json={'name':'重点复习','subject':subject});self.assertEqual(r.status_code,200);return r.json()['id']
 def collect(self,folder,pid,n):
  return self.client.put(f'/api/folders/{folder}/membership',json={'paper_id':pid,'number':n,'selected':True})
 def test_subject_catalogs_and_assets(self):
  for subject,count,total in [('math',90,1980),('408',18,846)]:
   ps=self.client.get('/api/library',params={'subject':subject}).json()['papers']
   self.assertEqual(len(ps),count);self.assertEqual(sum(p['question_count'] for p in ps),total)
   self.assertTrue(all(p['subject']==subject for p in ps))
   for p in ps:
    detail=self.client.get('/api/papers/'+p['id']).json()
    self.assertEqual([q['number'] for q in detail['questions']],list(range(1,p['question_count']+1)))
    self.assertTrue((server.ROOT.parent/detail['source']).exists())
    for q in detail['questions']:
     file=server.ROOT/'data/questions'/p['id']/f'{q["number"]}.png'
     self.assertTrue(file.exists());self.assertGreater(file.stat().st_size,1000)
  self.assertEqual(self.client.get(f'/api/questions/{self.math}/23').status_code,404)
  self.assertEqual(self.client.get(f'/api/questions/{self.cs}/47').status_code,200)
  self.assertEqual(self.client.get(f'/api/questions/{self.cs}/48').status_code,404)
 def test_folders_notes_reading_and_daily_are_independent(self):
  fm,fc=self.make_folder('math'),self.make_folder('408')
  self.assertEqual(self.collect(fm,self.cs,47).status_code,400)
  self.assertEqual(self.collect(fc,self.math,1).status_code,400)
  for subject,f,p,n in [('math',fm,self.math,1),('408',fc,self.cs,47)]:
   self.assertEqual(self.collect(f,p,n).status_code,200)
   self.assertEqual(self.client.patch(f'/api/questions/{p}/{n}',json={'note':subject+' 笔记','revision':0}).status_code,200)
   self.client.put('/api/last-read',json={'paper_id':p,'number':n})
   lib=self.client.get('/api/library',params={'subject':subject}).json()
   self.assertEqual([row['id'] for row in lib['folders']],[f])
   self.assertEqual([row['paper_id'] for row in lib['states']],[p])
   self.assertEqual(lib['last_read'],{'paper_id':p,'number':n})
   daily=self.client.post('/api/daily-review',params={'subject':subject}).json()
   self.assertEqual(daily['total'],1);self.assertEqual(daily['items'][0]['paper_id'],p)
  day=daily['day']
  self.client.put(f'/api/daily-review/{day}/items/1?subject=408',json={'result':'wrong'})
  math=self.client.get('/api/daily-review?subject=math').json()
  cs=self.client.get('/api/daily-review?subject=408').json()
  self.assertEqual(math['completed'],0);self.assertEqual(cs['wrong'],1)
  self.assertEqual(math['history'][0]['total'],1);self.assertEqual(cs['history'][0]['total'],1)
  before=self.client.get('/api/backup').json();self.assertEqual(len(before['daily_reviews']),2)
  self.assertEqual(len(before['last_reads']),2)
  with server.db() as c:
   for table in ['study_activity','daily_items','daily_batches','memberships','states','folders','settings']:c.execute('DELETE FROM '+table)
  self.assertEqual(self.client.post('/api/backup/restore',json=before).status_code,200)
  after=self.client.get('/api/backup').json()
  for field in ['folders','memberships','daily_reviews','last_reads']:self.assertEqual(before[field],after[field])
  bad=copy.deepcopy(before);bad['daily_reviews'][0]['subject']='408' if bad['daily_reviews'][0]['subject']=='math' else 'math'
  self.assertEqual(self.client.post('/api/backup/restore',json=bad).status_code,400)
  bad=copy.deepcopy(before);bad['states'][0]['number']=999
  self.assertEqual(self.client.post('/api/backup/restore',json=bad).status_code,400)
  bad=copy.deepcopy(before);bad['folders'][0]['subject']='408'
  self.assertEqual(self.client.post('/api/backup/restore',json=bad).status_code,400)
 def test_legacy_v2_without_subject_fields(self):
  f=self.make_folder('math');self.collect(f,self.math,1)
  self.client.post('/api/daily-review')
  backup=self.client.get('/api/backup').json();backup['version']=2;backup.pop('last_reads');backup.pop('knowledge')
  for row in backup['folders']+backup['daily_reviews']:row.pop('subject')
  self.assertEqual(self.client.post('/api/backup/restore',json=backup).status_code,200)
  self.assertEqual(self.client.get('/api/daily-review').json()['total'],1)
  self.assertFalse(self.client.get('/api/daily-review?subject=408').json()['generated'])
 def test_legacy_database_migration_preserves_and_is_idempotent(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'study.sqlite3';c=sqlite3.connect(path)
   c.executescript('''CREATE TABLE folders(id TEXT PRIMARY KEY,name TEXT UNIQUE,created_at TEXT);
    CREATE TABLE memberships(folder_id TEXT REFERENCES folders(id) ON DELETE CASCADE,paper_id TEXT,number INTEGER);
    CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);''')
   c.executescript(server.daily_review.SCHEMA)
   c.execute("INSERT INTO folders VALUES('f','原数学收藏','today')")
   c.execute("INSERT INTO memberships VALUES('f','p',22)")
   c.execute("INSERT INTO daily_batches VALUES('2026-10-11','now',1,0)")
   c.execute("INSERT INTO daily_items VALUES('2026-10-11',1,'p',22,'wrong','now')")
   c.execute("INSERT INTO settings VALUES('last_read',?)",(json.dumps(dict(paper_id='p',number=22)),))
   c.commit();c.close();migrate(path);migrate(path)
   c=sqlite3.connect(path)
   self.assertEqual(c.execute('SELECT * FROM memberships').fetchall(),[('f','p',22)])
   self.assertEqual(c.execute('SELECT subject,result,number FROM daily_items').fetchall(),[('math','wrong',22)])
   self.assertEqual(c.execute("SELECT value FROM settings WHERE key='last_read:math'").fetchone()[0],json.dumps(dict(paper_id='p',number=22)))
   self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[]);c.close()
   self.assertEqual(len(list((Path(td)/'backups').glob('*.sqlite3'))),1)

if __name__=='__main__':unittest.main(verbosity=2)
