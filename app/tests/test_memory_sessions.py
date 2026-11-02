"""Continuous review, chapter scope, restore and source integrity on the isolated DB."""
import copy,uuid,unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient
from test_app import server
k=server.knowledge
class MemorySessions(unittest.TestCase):
 def setUp(self):
  self.client=TestClient(server.app)
  with server.db() as c:
   for t in ['session_items','sessions','reviews','draws','states','goals']:c.execute('DELETE FROM knowledge_'+t)
   c.execute("DELETE FROM study_activity WHERE area='knowledge'")
  self.at=datetime(2026,10,27,3,0,tzinfo=timezone.utc)
  self.clock=patch.object(k,'now',lambda:self.at);self.clock.start()
 def tearDown(self):
  self.clock.stop()
  with server.db() as c:
   for t in ['session_items','sessions','reviews','draws','states','goals']:c.execute('DELETE FROM knowledge_'+t)
   c.execute("DELETE FROM study_activity WHERE area='knowledge'")
 def start(self,**kw):
  body=dict(request_id=str(uuid.uuid4()),limit=10,**kw)
  r=self.client.post('/api/knowledge/sessions',json=body);self.assertEqual(r.status_code,200,r.text);return r.json()
 def pos(self,s,p):
  r=self.client.put('/api/knowledge/sessions/'+s['id']+'/position',json={'position':p});self.assertEqual(r.status_code,200,r.text);return r.json()
 def score(self,d,rating=3):
  self.assertEqual(self.client.post('/api/knowledge/draws/'+d['id']+'/reveal').status_code,200)
  r=self.client.post('/api/knowledge/draws/'+d['id']+'/score',json={'rating':rating,'revision':d['revision'],'request_id':'score:'+d['id']});self.assertEqual(r.status_code,200,r.text);return r.json()
 def test_sources_and_active_catalog_are_only_140_pdf_cards(self):
  cats=self.client.get('/api/knowledge/catalog').json()['cards'];self.assertEqual(len(cats),140)
  self.assertTrue(all(c['id'].startswith('mc-') for c in cats))
  self.assertNotIn('core',cats[0]);self.assertNotIn('explanation',cats[0])
  for f in k.SUBJECTS:self.assertTrue(self.client.get('/api/knowledge/source/'+f).content.startswith(b'%PDF'))
  for cid in list(k.ARCHIVED_CARDS)[:2]:self.assertEqual(self.client.get('/api/knowledge/cards/'+cid).status_code,404)
  for c in k.CARDS.values():
   keys=[]
   def walk(ns):
    for n in ns:
     if n.get('tag')=='blank':keys.append(n['key']);self.assertTrue(n['text'])
     walk(n.get('children',[]))
   walk(c['core']);self.assertEqual(len(keys),len(set(keys)));self.assertEqual(len(keys),c['blank_count'])
 def test_start_is_idempotent_concurrent_and_unique(self):
  body={'request_id':'same','field':'ds','limit':10}
  with ThreadPoolExecutor(2) as pool:values=list(pool.map(lambda _:self.client.post('/api/knowledge/sessions',json=body),range(2)))
  self.assertTrue(all(r.status_code==200 for r in values));a,b=[r.json() for r in values];self.assertEqual(a['id'],b['id'])
  self.assertEqual(len(set(i['card_id'] for i in a['items'])),10)
  self.assertEqual(self.client.post('/api/knowledge/sessions',json={**body,'limit':20}).status_code,409)
  self.assertEqual(self.client.post('/api/knowledge/sessions',json={**body,'request_id':'new'}).status_code,409)
 def test_chapter_scope_is_exact_and_reload_keeps_cursor(self):
  ch=k.SUBJECTS['net']['chapters'][0]['id'];s=self.start(field='net',chapter_id=ch,mode='chapter')
  self.assertTrue(all(i['chapter_id']==ch for i in s['items']))
  second=self.pos(s,2);self.assertEqual(second['cursor'],2)
  self.assertNotIn('explanation',second['current']['card'])
  self.assertTrue(second['current']['card']['core'])
  self.assertEqual(self.pos(s,2)['current']['id'],second['current']['id'])
  self.assertEqual(self.client.get('/api/knowledge/overview').json()['active_session']['cursor'],2)
 def test_wrong_scope_and_empty_due_do_not_create_queues(self):
  self.assertEqual(self.client.post('/api/knowledge/sessions',json={'request_id':'x','mode':'chapter'}).status_code,400)
  self.assertEqual(self.client.post('/api/knowledge/sessions',json={'request_id':'x','field':'ds','chapter_id':k.SUBJECTS['os']['chapters'][0]['id']}).status_code,400)
  self.assertEqual(self.client.post('/api/knowledge/sessions',json={'request_id':'x','mode':'due'}).status_code,409)
  self.assertIsNone(self.client.get('/api/knowledge/overview').json()['active_session'])
 def test_multiple_unscored_cards_resume_and_finish_once(self):
  s=self.start(field='ds');a=self.pos(s,1);b=self.pos(s,2)
  self.assertNotEqual(a['current']['id'],b['current']['id'])
  self.assertEqual(self.pos(s,1)['current']['id'],a['current']['id'])
  for i in s['items']:
   draw=self.pos(s,i['position'])['current'];self.score(draw)
   duplicate=self.client.post('/api/knowledge/draws/'+draw['id']+'/score',json={'rating':3,'revision':draw['revision'],'request_id':'score:'+draw['id']});self.assertEqual(duplicate.status_code,200)
  result=self.client.get('/api/knowledge/sessions/'+s['id']).json()
  self.assertEqual(result['status'],'completed');self.assertEqual(result['completed'],10);self.assertEqual(result['counts'],[0,0,10,0])
  self.assertIsNone(self.client.get('/api/knowledge/overview').json()['active_session'])
  with server.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM knowledge_reviews').fetchone()[0],10)
 def test_chapter_early_practice_preserves_fsrs(self):
  card=next(iter(k.CARDS.values()));s=self.start(field=card['field'],chapter_id=card['chapter_id'],mode='chapter')
  d=self.pos(s,1)['current'];self.score(d,4)
  before=self.client.get('/api/knowledge/cards/'+d['card_id']).json()
  self.client.post('/api/knowledge/sessions/'+s['id']+'/end')
  s2=self.start(field=card['field'],chapter_id=card['chapter_id'],mode='chapter')
  p=next(i['position'] for i in s2['items'] if i['card_id']==d['card_id']);d2=self.pos(s2,p)['current'];self.assertEqual(d2['mode'],'practice');self.score(d2,1)
  after=self.client.get('/api/knowledge/cards/'+d['card_id']).json()
  self.assertEqual(before['due'],after['due']);self.assertEqual(before['total'],after['total'])
 def test_backup_roundtrip_includes_queue_and_guards_corruption(self):
  s=self.start(field='os');self.score(self.pos(s,1)['current']);self.pos(s,2)
  backup=self.client.get('/api/backup').json();self.assertEqual(backup['version'],9)
  self.assertEqual(self.client.post('/api/backup/preview',json=backup).status_code,200)
  bad=copy.deepcopy(backup);bad['knowledge']['sessions'][0]['items'][1]['card_id']=bad['knowledge']['sessions'][0]['items'][0]['card_id']
  self.assertEqual(self.client.post('/api/backup/preview',json=bad).status_code,400)
  self.assertEqual(self.client.post('/api/backup/restore',json=backup).status_code,200)
  restored=self.client.get('/api/knowledge/sessions/'+s['id']).json();self.assertEqual(restored['cursor'],2);self.assertEqual(restored['completed'],1);self.assertEqual(restored['current']['card_id'],s['items'][1]['card_id'])
 def test_old_backup_preserves_local_new_queue_and_archives_outline(self):
  s=self.start(field='co');self.pos(s,1)
  backup=self.client.get('/api/backup').json();backup['version']=7;backup['knowledge']['sessions']=[]
  old=next(iter(k.ARCHIVED_CARDS.values()));oldtime=k.stamp(self.at)
  backup['knowledge'].update(catalog_version=k.LEGACY_CATALOG['version'],source_sha256=k.LEGACY_CATALOG['source_sha256'],states=[{'card_id':old['id'],'fsrs':None,'revision':0,'seen_at':oldtime}],draws=[],reviews=[])
  self.assertEqual(self.client.post('/api/backup/restore',json=backup).status_code,200)
  self.assertEqual(self.client.get('/api/knowledge/overview').json()['active_session']['id'],s['id'])
  self.assertEqual(self.client.get('/api/knowledge/catalog').json()['cards'][0]['source_kind'],'codebrick_pdf')
