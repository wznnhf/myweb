"""Integration tests use a temporary database, never the user's study records."""
import copy, importlib, json, os, sys, tempfile, unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TMP=tempfile.TemporaryDirectory();os.environ['CUOTI_DATA_DIR']=TMP.name
import server

class StudyTests(unittest.TestCase):
 def setUp(self):
  self.client=TestClient(server.app)
  with server.db() as c:
   for table in ['study_activity','daily_items','daily_batches','memberships','states','folders','settings']:c.execute('DELETE FROM '+table)
  self.pid=next(iter(server.PAPERS));self.path=f'/api/questions/{self.pid}/1'
 def folder(self,name):
  r=self.client.post('/api/folders',json={'name':name});self.assertEqual(r.status_code,200);return r.json()['id']
 def collect(self,f,n=1,selected=True):
  return self.client.put(f'/api/folders/{f}/membership',json={'paper_id':self.pid,'number':n,'selected':selected})
 def test_full_catalog_and_every_asset(self):
  ps=self.client.get('/api/library').json()['papers'];self.assertEqual(len(ps),90)
  for p in ps:
   detail=self.client.get('/api/papers/'+p['id']).json()
   self.assertEqual([q['number'] for q in detail['questions']],list(range(1,23)))
   for q in detail['questions']:
    path=ROOT/'data/questions'/p['id']/f'{q["number"]}.png'
    self.assertTrue(path.exists());self.assertGreater(path.stat().st_size,1000)
   self.assertEqual(self.client.get(f'/api/papers/{p["id"]}/pdf').status_code,200)
  self.assertEqual(sum(bool(q['warning']) for p in server.PAPERS.values() for q in p['questions']),2)
 def test_note_persistence_and_revision_conflicts(self):
  self.assertEqual(self.client.patch(self.path,json={'note':'错因：漏看条件\n下次先圈出条件。','revision':0}).status_code,200)
  r=TestClient(server.app).get(self.path).json();self.assertIn('漏看条件',r['note'])
  self.assertEqual(self.client.patch(self.path,json={'note':'过期页面','revision':0}).status_code,409)
  self.assertEqual(self.client.get(self.path).json()['note'],r['note'])
  with ThreadPoolExecutor(2) as pool:
   codes=list(pool.map(lambda t:self.client.patch(self.path,json={'note':t,'revision':1}).status_code,['草稿A','草稿B']))
  self.assertEqual(sorted(codes),[200,409])
 def test_folders_share_notes_and_state_without_data_loss(self):
  a,b=self.folder('积分'),self.folder('计算失误')
  self.client.patch(self.path,json={'note':'共同笔记','revision':0})
  self.collect(a);self.collect(b);r=self.client.get(self.path).json()
  self.assertEqual(r['status'],'review');self.assertCountEqual(r['folder_ids'],[a,b])
  self.client.patch(self.path,json={'status':'mastered'});self.collect(a,selected=False)
  self.assertEqual(self.client.get(self.path).json()['status'],'mastered')
  self.client.delete('/api/folders/'+b)
  r=self.client.get(self.path).json();self.assertEqual(r['note'],'共同笔记');self.assertEqual(r['folder_ids'],[])
  self.assertEqual(r['status'],'mastered')
 def test_folder_names_and_validation(self):
  fid=self.folder('积分')
  self.assertEqual(self.client.post('/api/folders',json={'name':' 积分 '}).status_code,409)
  self.assertEqual(self.client.post('/api/folders',json={'name':'  '}).status_code,400)
  self.assertEqual(self.client.patch('/api/folders/'+fid,json={'name':'重做'}).status_code,200)
  self.assertEqual(self.client.get('/api/questions/unknown/1').status_code,404)
  self.assertEqual(self.client.patch(self.path,json={'status':'bogus'}).status_code,422)
 def test_backup_restore_overwrite_and_preserve_unrelated(self):
  a=self.folder('积分');self.collect(a)
  self.client.patch(self.path,json={'note':'原始笔记','revision':0})
  self.client.put('/api/last-read',json={'paper_id':self.pid,'number':1})
  backup=self.client.get('/api/backup').json()
  self.client.patch(self.path,json={'note':'恢复前笔记','revision':1})
  self.client.patch(f'/api/questions/{self.pid}/2',json={'note':'无关题目保留','revision':0})
  b=self.folder('后来添加');self.collect(b);self.collect(b,n=2)
  preview=self.client.post('/api/backup/preview',json=backup).json();self.assertEqual(preview['overwrites'],1)
  r=self.client.post('/api/backup/restore',json=backup);self.assertEqual(r.status_code,200)
  restored=self.client.get(self.path).json();self.assertEqual(restored['note'],'原始笔记');self.assertEqual(restored['folder_ids'],[a])
  self.assertEqual(self.client.get(f'/api/questions/{self.pid}/2').json()['note'],'无关题目保留')
  safety=json.loads((Path(TMP.name)/'backups'/r.json()['safety_backup']).read_text())
  self.assertEqual(safety['states'][0]['note'],'恢复前笔记')
  self.assertEqual(self.client.get('/api/library').json()['last_read']['number'],1)
 def test_bad_backup_is_atomic(self):
  self.client.patch(self.path,json={'note':'必须保留','revision':0})
  backup=self.client.get('/api/backup').json();before=copy.deepcopy(backup)
  backup['states'][0]['paper_id']='foreign';self.assertEqual(self.client.post('/api/backup/restore',json=backup).status_code,400)
  self.assertEqual(self.client.get(self.path).json()['note'],'必须保留')
  self.assertEqual(self.client.post('/api/backup/preview',content='{broken',headers={'Content-Type':'application/json'}).status_code,422)
  before['states'].append(before['states'][0]);self.assertEqual(self.client.post('/api/backup/restore',json=before).status_code,400)
 def test_host_and_origin_protection(self):
  self.assertEqual(self.client.post('/api/folders',json={'name':'evil'},headers={'Origin':'https://other.example'}).status_code,403)
  self.assertEqual(self.client.get('/api/library',headers={'Host':'evil.example'}).status_code,400)
  self.assertEqual(self.client.get('/papers/'+self.pid+'/questions/1').status_code,200)

if __name__=='__main__':unittest.main(verbosity=2)
