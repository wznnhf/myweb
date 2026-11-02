"""Daily-review regression scenarios. All records use the existing isolated test DB."""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from test_app import server
from fastapi.testclient import TestClient

class DailyReviewTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(server.app)
        self.pid=next(iter(server.PAPERS))
        with server.db() as c:
            for table in ('study_activity','daily_items','daily_batches','memberships','states','folders','settings'):
                c.execute('DELETE FROM '+table)
            c.execute("INSERT INTO folders(id,name,created_at) VALUES('test-folder','每日回顾测试','2026-10-01')")
        self.clock=patch('daily_review.today',return_value='2026-10-12')
        self.day=self.clock.start();self.addCleanup(self.clock.stop)

    def collect(self,amount):
        with server.db() as c:
            for n in range(1,amount+1):
                server.ensure_state(c,self.pid,n)
                c.execute('INSERT OR IGNORE INTO memberships VALUES(?,?,?)',('test-folder',self.pid,n))

    def generate(self):
        response=self.client.post('/api/daily-review')
        self.assertEqual(response.status_code,200)
        return response.json()

    def test_empty_and_small_pool(self):
        self.assertFalse(self.generate()['generated'])
        self.collect(3)
        first=self.generate();self.assertEqual(first['total'],3)
        self.assertEqual(len({(q['paper_id'],q['number']) for q in first['items']}),3)
        self.collect(10)
        self.assertEqual(self.generate()['items'],first['items'])

    def test_concurrent_open_is_idempotent_and_next_session_avoids_repeat(self):
        self.collect(12)
        with ThreadPoolExecutor(3) as pool: sets=list(pool.map(lambda _:self.generate(),range(3)))
        self.assertEqual(sets[0]['items'],sets[1]['items']);self.assertEqual(sets[1]['items'],sets[2]['items'])
        self.assertTrue(all(q['drawn_count']==1 for q in sets[0]['items']))
        self.day.return_value='2026-10-15'
        following=self.generate()
        self.assertFalse({q['number'] for q in sets[0]['items']}&{q['number'] for q in following['items']})

    def test_fallback_only_repeats_as_many_as_needed(self):
        self.collect(7);first=self.generate();self.day.return_value='2026-10-13';second=self.generate()
        self.assertEqual(second['repeated_previous'],3)
        self.assertEqual(len({q['number'] for q in first['items']}&{q['number'] for q in second['items']}),3)

    def test_result_edits_never_inflate_counts_and_persist(self):
        self.collect(5);self.generate()
        url='/api/daily-review/2026-10-12/items/1'
        for _ in range(3):r=self.client.put(url,json={'result':'wrong'})
        item=r.json()['items'][0];self.assertEqual(item['wrong_count'],1);self.assertEqual(item['drawn_count'],1)
        r=self.client.put(url,json={'result':'correct'});item=r.json()['items'][0]
        self.assertEqual(item['wrong_count'],0);self.assertEqual(item['correct_count'],1)
        saved=TestClient(server.app).get('/api/daily-review').json()
        self.assertEqual(saved['completed'],1)
        q=self.client.get(f'/api/questions/{item["paper_id"]}/{item["number"]}').json()
        self.assertEqual(q['status'],'mastered')
        self.day.return_value='2026-10-13'
        self.assertEqual(self.client.put(url,json={'result':'wrong'}).status_code,409)

    def test_weight_prioritizes_fewer_draws_and_more_errors(self):
        import daily_review
        class FixedRandom:
            def random(self):return .5
        refs=[('p',1),('p',2),('p',3)]
        stats={refs[0]:dict(drawn_count=2,wrong_count=0),refs[1]:dict(drawn_count=2,wrong_count=2),refs[2]:dict(drawn_count=0,wrong_count=0)}
        self.assertEqual(daily_review.weighted_pick(refs,3,stats,FixedRandom()),[refs[2],refs[1],refs[0]])

    def test_backups_preserve_history_and_support_old_format(self):
        self.collect(5);self.generate()
        self.client.put('/api/daily-review/2026-10-12/items/1',json={'result':'wrong'})
        backup=self.client.get('/api/backup').json();self.assertEqual(backup['version'],9)
        self.client.put('/api/daily-review/2026-10-12/items/1',json={'result':'correct'})
        self.assertEqual(self.client.post('/api/backup/restore',json=backup).status_code,200)
        self.assertEqual(self.client.get('/api/daily-review').json()['wrong'],1)
        old=copy.deepcopy(backup);old['version']=1;del old['daily_reviews'];old.pop('knowledge')
        self.assertEqual(self.client.post('/api/backup/restore',json=old).status_code,200)
        self.assertEqual(self.client.get('/api/daily-review').json()['wrong'],1)
        bad=copy.deepcopy(backup);bad['daily_reviews'][0]['items'].append(bad['daily_reviews'][0]['items'][0])
        self.assertEqual(self.client.post('/api/backup/restore',json=bad).status_code,422)

if __name__=='__main__':unittest.main(verbosity=2)
