"""Book import, scheduling and integration tests use only the suite's temporary DB."""
import copy
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from test_app import server

p = server.daily_practice


class PracticeTests(unittest.TestCase):
    def setUp(self):
        self.clear()
        self.client = TestClient(server.app)
        self.day = '2026-10-26'
        self.date_patch = patch.object(p, 'today', side_effect=lambda: self.day)
        self.time_patch = patch.object(p, 'now', side_effect=lambda: self.day + 'T12:00:00+08:00')
        self.date_patch.start()
        self.time_patch.start()
        self.activity_patch=patch.object(server.activity,'today',side_effect=lambda:date.fromisoformat(self.day))
        self.activity_patch.start()

    def clear(self):
        with server.db() as c:
            for table in ['study_activity', 'practice_items', 'practice_rounds', 'daily_items', 'daily_batches',
                          'memberships', 'states', 'folders', 'settings']:
                c.execute('DELETE FROM ' + table)

    def tearDown(self):
        self.date_patch.stop()
        self.time_patch.stop()
        self.activity_patch.stop()
        self.clear()

    def start(self):
        r = self.client.post('/api/daily-practice/start')
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def day_url(self, rid, day=None):
        return f'/api/daily-practice/rounds/{rid}/days/{day or self.day}'

    def test_imported_assets_identity_and_originals(self):
        self.assertEqual(len(p.PAPERS), 24)
        totals = Counter()
        sources = set()
        for paper in p.PAPERS.values():
            totals[paper['field']] += paper['question_count']
            sources.add(paper['source'])
            self.assertEqual([q['number'] for q in paper['questions']], list(range(1, paper['question_count'] + 1)))
            for q in paper['questions']:
                path = server.ROOT / 'data/questions' / paper['id'] / f'{q["number"]}.png'
                with Image.open(path) as im:
                    self.assertEqual(im.size, (q['width'], q['height']))
                    im.verify()
                self.assertGreater(path.stat().st_size, 1000)
                for s in q['segments']:
                    x0, y0, x1, y1 = s['box']
                    self.assertTrue(0 <= x0 < x1 <= 595.25 and 70 <= y0 < y1 <= 790)
                    self.assertEqual(s['book_page'], s['page'] - 4)
        self.assertEqual(totals, dict(ds=411, co=373, os=417, cn=375))
        self.assertEqual(len(sources), 1)
        source = server.ROOT.parent / sources.pop()
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), p.BOOK['sha256'])
        self.assertEqual(self.client.get('/api/papers/' + next(iter(p.PAPERS)) + '/pdf').status_code, 200)
        lib = self.client.get('/api/library?subject=408').json()
        self.assertEqual(len(lib['papers']), 18)
        self.assertEqual(len(lib['exercise_books']), 24)
        self.assertEqual(self.client.get('/api/library?subject=math').json()['exercise_books'], [])

    def test_whole_round_unique_complete_balanced_and_tail(self):
        for seed in ['0' * 32, 'a' * 32, 'f' * 32]:
            items = p.schedule(seed, self.day)
            self.assertEqual(items, p.schedule(seed, self.day))
            refs = {(i['paper_id'], i['number']) for i in items}
            self.assertEqual(len(items), 1576)
            self.assertEqual(len(refs), 1576)
            counts = Counter(i['day'] for i in items)
            values = [counts[d] for d in sorted(counts)]
            self.assertEqual(values, [40] * 37 + [28, 20, 20, 20, 8])
            for offset in range(37):
                day = (date.fromisoformat(self.day) + timedelta(days=offset)).isoformat()
                self.assertEqual(Counter(p.PAPERS[i['paper_id']]['field'] for i in items if i['day'] == day),
                                 dict(ds=10, co=10, os=10, cn=10))
            # At every prefix within each subject, cumulative allocation stays within one question of its quota.
            used, seen = Counter(), Counter()
            totals = Counter()
            for paper in p.PAPERS.values():
                totals[paper['field']] += paper['question_count']
            for i in items:
                field = p.PAPERS[i['paper_id']]['field']
                used[i['paper_id']] += 1
                seen[field] += 1
                for paper in p.PAPERS.values():
                    if paper['field'] == field:
                        self.assertLess(abs(used[paper['id']] - seen[field] * paper['question_count'] / totals[field]), 1)

    def test_cross_page_diagrams_beginning_above_72_points_are_preserved(self):
        # These continuation pages start with raster figures at y=70.92, before any text.
        for field, chapter, number, page, bottom in [('cn', 3, 89, 223, 275.64), ('cn', 4, 13, 227, 156.0)]:
            paper = next(paper for paper in p.PAPERS.values() if paper['field'] == field and paper['chapter_order'] == chapter)
            segment = next(s for s in paper['questions'][number-1]['segments'] if s['page'] == page)
            self.assertLessEqual(segment['box'][1], 70.92)
            self.assertGreaterEqual(segment['box'][3], bottom)

    def test_concurrent_start_refresh_and_reopen_are_idempotent(self):
        self.assertFalse(self.client.get('/api/daily-practice').json()['started'])
        with ThreadPoolExecutor(4) as pool:
            responses = list(pool.map(lambda _: TestClient(server.app).post('/api/daily-practice/start'), range(4)))
        self.assertTrue(all(r.status_code == 200 for r in responses))
        ids = {r.json()['round']['id'] for r in responses}
        self.assertEqual(len(ids), 1)
        first = responses[0].json()
        self.assertEqual(TestClient(server.app).get('/api/daily-practice').json()['day'], first['day'])
        self.assertEqual(self.start()['round']['id'], first['round']['id'])
        with server.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM practice_items').fetchone()[0], 1576)

    def test_calendar_skip_days_future_protection_and_history_answers(self):
        data = self.start()
        rid = data['round']['id']
        before = data['day']
        future = self.day_url(rid, '2026-10-27')
        self.assertEqual(self.client.get(future).status_code, 404)
        self.assertEqual(self.client.put(future + '/items/1', json={'choice': 'A'}).status_code, 404)
        self.day = '2026-11-02'
        current = self.client.get('/api/daily-practice').json()
        self.assertEqual(len(current['history']), 8)
        self.assertEqual(current['round']['released'], 320)
        self.assertEqual(self.client.get(self.day_url(rid, before['day'])).json(), before)
        old = self.day_url(rid, before['day']) + '/items/1'
        marked = self.client.put(old, json={'choice': 'B'})
        self.assertEqual(marked.status_code, 200)
        self.assertIsNone(marked.json()['wrong'])
        self.assertEqual(marked.json()['completed'], 1)
        self.assertEqual(self.client.post('/api/backup/preview', json=self.client.get('/api/backup').json()).status_code, 200)
        current_refs = {(i['paper_id'], i['number']) for i in current['day']['items']}
        self.assertFalse(current_refs & {(i['paper_id'], i['number']) for i in before['items']})
        self.assertEqual(self.client.get(self.day_url(rid, '2026-10-25')).status_code, 404)
        self.assertEqual(self.client.get(self.day_url(rid, '2026-1-2')).status_code, 400)
        self.assertEqual(self.client.put(old, json={'choice': 'invalid'}).status_code, 422)

    def fill(self, rid, day=None):
        url = self.day_url(rid, day)
        data = self.client.get(url).json()
        for i in data['items']:
            key = p.solution(i['paper_id'], i['number'])['answer']
            response = self.client.put(url + f"/items/{i['position']}", json={'choice': key})
            self.assertEqual(response.status_code, 200, response.text)
        return url

    def test_choices_are_private_until_complete_and_explicitly_submitted(self):
        data = self.start(); rid = data['round']['id']; url = self.day_url(rid)
        i = data['day']['items'][0]; qurl = f"/api/questions/{i['paper_id']}/{i['number']}"
        key = p.solution(i['paper_id'], i['number'])['answer']
        wrong = ('B' if key[0] == 'A' else 'A') + key[1:]
        self.client.patch(qurl, json={'note': '跨页题复盘 $O(n)$', 'revision': 0})
        self.assertEqual(self.client.post(url + '/submit').status_code, 409)
        self.assertEqual(self.client.get(url + '/items/1/analysis.pdf').status_code, 403)
        self.assertEqual(self.client.put(url+'/items/1', json={'result': 'correct'}).status_code, 422)
        first = self.client.put(url+'/items/1', json={'choice': wrong}).json()
        self.assertEqual(first['completed'], 1)
        self.assertIsNone(first['correct']); self.assertIsNone(first['wrong'])
        self.assertFalse(first['submitted'])
        self.assertTrue(all(i['result'] is None and 'correct_answer' not in i and 'analysis_url' not in i for i in first['items']))
        self.assertEqual(self.client.get(qurl).json()['status'], 'unmarked')
        self.assertEqual(self.client.get('/api/library?subject=408').json()['memberships'], [])
        again = self.client.put(url+'/items/1', json={'choice': wrong}).json()
        self.assertEqual(again['items'][0]['selected_at'], first['items'][0]['selected_at'])
        self.assertEqual(TestClient(server.app).get(url).json(), again)
        self.client.put(url+'/items/1', json={'choice': None})
        self.assertEqual(self.client.get(url).json()['completed'], 0)
        self.fill(rid)
        self.client.put(url+'/items/1', json={'choice': wrong})
        before = self.client.get('/api/daily-practice').json()
        self.assertIsNone(before['history'][0]['correct'])
        self.assertIsNone(before['day']['correct'])
        self.assertEqual(before['day']['completed'], 40)
        with ThreadPoolExecutor(3) as pool:
            responses=list(pool.map(lambda _: TestClient(server.app).post(url+'/submit'), range(3)))
        self.assertTrue(all(r.status_code == 200 for r in responses))
        final=responses[0].json()
        self.assertEqual((final['completed'], final['correct'], final['wrong']), (40,39,1))
        self.assertTrue(all(r.json() == final for r in responses))
        self.assertEqual(final['items'][0]['correct_answer'], key)
        self.assertEqual(self.client.get(qurl).json()['status'], 'review')
        self.assertIn('跨页题', self.client.get(qurl).json()['note'])
        self.assertEqual(self.client.put(url+'/items/1', json={'choice': key}).status_code, 409)
        self.assertEqual(self.client.get(url+'/items/1/analysis.pdf').status_code, 200)
        library=self.client.get('/api/library?subject=408').json()
        f=next(f['id'] for f in library['folders'] if f['name']=='每日一练错题')
        self.assertEqual(final['mistake_folder_id'],f)
        self.assertEqual(final['collected_wrong'],1)
        self.assertEqual(library['memberships'],[{'folder_id':f,'paper_id':i['paper_id'],'number':i['number']}])
        self.assertEqual(self.client.post('/api/daily-review?subject=408').json()['items'][0]['paper_id'],i['paper_id'])
        self.assertEqual(self.client.put(f'/api/daily-practice/rounds/{rid}/position',json={'day':self.day,'position':4}).status_code,200)
        self.assertEqual(self.client.get('/api/daily-practice').json()['round']['last_position'],{'day':self.day,'position':4})
        self.assertEqual(self.client.get('/api/library?subject=math').json()['states'],[])

    def test_auto_collect_reuses_folder_preserves_notes_and_other_memberships(self):
        data=self.start();rid=data['round']['id'];url=self.fill(rid)
        automatic=self.client.post('/api/folders',json={'subject':'408','name':'每日一练错题'}).json()['id']
        other=self.client.post('/api/folders',json={'subject':'408','name':'重点复盘'}).json()['id']
        math=self.client.post('/api/folders',json={'subject':'math','name':'每日一练错题'}).json()['id']
        wrong_items=data['day']['items'][:3]
        for i in wrong_items:
            qurl=f"/api/questions/{i['paper_id']}/{i['number']}"
            with patch.object(server,'now',side_effect=p.now):
                self.client.patch(qurl,json={'note':'保留错因与公式 $O(n)$','revision':0,'status':'mastered'})
            self.client.put(f'/api/folders/{other}/membership',json={'paper_id':i['paper_id'],'number':i['number'],'selected':True})
            key=p.solution(i['paper_id'],i['number'])['answer']
            self.client.put(url+f"/items/{i['position']}",json={'choice':('B' if key[0]=='A' else 'A')+key[1:]})
        first=wrong_items[0]
        self.client.put(f'/api/folders/{automatic}/membership',json={'paper_id':first['paper_id'],'number':first['number'],'selected':True})
        result=self.client.post(url+'/submit').json()
        self.assertEqual((result['wrong'],result['collected_wrong']),(3,3))
        self.assertEqual(result['mistake_folder_id'],automatic)
        for i in wrong_items:
            state=self.client.get(f"/api/questions/{i['paper_id']}/{i['number']}").json()
            self.assertEqual(state['note'],'保留错因与公式 $O(n)$')
            self.assertEqual(state['revision'],1)
            self.assertEqual(state['status'],'review')
            self.assertCountEqual(state['folder_ids'],[automatic,other])
        library=self.client.get('/api/library?subject=408').json()
        self.assertEqual(len(library['folders']),2)
        self.assertEqual(len(library['memberships']),6)
        self.assertEqual(self.client.get('/api/library?subject=math').json()['memberships'],[])
        self.assertNotIn(math,[m['folder_id'] for m in library['memberships']])
        self.assertEqual(TestClient(server.app).get(url).json(),result)
        backup=self.client.get('/api/backup').json()
        restored=self.client.post('/api/backup/restore',json=backup)
        self.assertEqual(restored.status_code,200,restored.text)
        self.assertEqual(self.client.get('/api/library?subject=408').json()['memberships'],library['memberships'])

    def test_all_correct_does_not_create_a_mistake_folder(self):
        data=self.start();url=self.fill(data['round']['id'])
        result=self.client.post(url+'/submit').json()
        self.assertEqual(result['wrong'],0)
        self.assertEqual(result['collected_wrong'],0)
        self.assertIsNone(result['mistake_folder_id'])
        library=self.client.get('/api/library?subject=408').json()
        self.assertEqual(library['folders'],[])
        self.assertEqual(library['memberships'],[])

    def test_collection_failure_rolls_back_the_entire_submission(self):
        data=self.start();rid=data['round']['id'];url=self.fill(rid)
        i=data['day']['items'][0];key=p.solution(i['paper_id'],i['number'])['answer']
        self.client.put(url+'/items/1',json={'choice':('B' if key[0]=='A' else 'A')+key[1:]})
        with server.db() as c:
            c.execute("CREATE TRIGGER fail_collection BEFORE INSERT ON memberships BEGIN SELECT RAISE(ABORT,'collection failed'); END")
        try:
            response=TestClient(server.app,raise_server_exceptions=False).post(url+'/submit')
            self.assertEqual(response.status_code,500)
            with server.db() as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM practice_submissions').fetchone()[0],0)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM practice_items WHERE result IS NOT NULL').fetchone()[0],0)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM folders').fetchone()[0],0)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM memberships').fetchone()[0],0)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM states').fetchone()[0],0)
        finally:
            with server.db() as c:c.execute('DROP TRIGGER fail_collection')
        self.assertEqual(self.client.post(url+'/submit').json()['collected_wrong'],1)

    def test_answer_book_identity_multiblanks_and_detail_corrections(self):
        self.assertEqual(p.ANSWERS['total'],1576)
        self.assertEqual(p.ANSWERS['question_book_sha256'],p.BOOK['sha256'])
        source=server.ROOT/p.ANSWERS['source']
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),p.ANSWERS['sha256'])
        self.assertEqual(len(p.ANSWERS['conflicts']),3)
        self.assertEqual([(c['number'],c['detailed']) for c in p.ANSWERS['conflicts']],[(7,'C'),(68,'C'),(44,'A')])
        cases=[('ds',2,12,'CD'),('ds',6,46,'CB'),('ds',7,53,'DC'),('ds',7,55,'DA'),('cn',1,37,'CDA')]
        for field,chapter,number,expected in cases:
            paper=next(q for q in p.PAPERS.values() if q['field']==field and q['chapter_order']==chapter)
            self.assertEqual(p.solution(paper['id'],number)['answer'],expected)
        for paper in p.PAPERS.values():
            self.assertEqual(len(p.ANSWERS['papers'][paper['id']]),paper['question_count'])
            for n in range(1,paper['question_count']+1):
                answer=p.solution(paper['id'],n)
                self.assertTrue(1<=answer['page']<=answer['end_page']<=312)

    def test_multiblank_partial_save_and_tail_submission(self):
        data=self.start();rid=data['round']['id']
        with server.db() as c:
            row=next(r for r in c.execute('SELECT * FROM practice_items WHERE round_id=?',(rid,))
                if p.solution(r['paper_id'],r['number'])['slots']>1)
        self.day=row['day'];url=self.day_url(rid)
        endpoint=url+f"/items/{row['position']}";key=p.solution(row['paper_id'],row['number'])['answer']
        self.assertEqual(self.client.put(endpoint,json={'choice':'A'}).status_code,400)
        partial=key[0]+'_'*(len(key)-1)
        saved=self.client.put(endpoint,json={'choice':partial}).json()
        self.assertEqual(saved['completed'],0)
        self.assertEqual(TestClient(server.app).get(url).json()['items'][row['position']-1]['choice'],partial)
        self.assertEqual(self.client.post(url+'/submit').status_code,409)
        self.fill(rid);self.assertEqual(self.client.post(url+'/submit').json()['wrong'],0)
        backup=self.client.get('/api/backup').json()
        self.assertEqual(self.client.post('/api/backup/restore',json=backup).status_code,200)
        self.assertEqual(self.client.get('/api/backup').json()['daily_practice'],backup['daily_practice'])
        bad=copy.deepcopy(backup);bad['daily_practice'][0]['items'][0]['choice']='D'
        self.assertEqual(self.client.post('/api/backup/restore',json=bad).status_code,400)
        self.day=data['round']['end_day'];tail=self.fill(rid)
        result=self.client.post(tail+'/submit').json()
        self.assertEqual((result['total'],result['correct'],result['wrong']),(8,8,0))

    def test_tail_round_transition_and_old_rounds_remain_accessible(self):
        data = self.start()
        rid = data['round']['id']
        self.assertEqual(self.client.post('/api/daily-practice/next-round').status_code, 409)
        self.day = data['round']['end_day']
        current = self.client.get('/api/daily-practice').json()
        self.assertEqual(current['day']['total'], 8)
        self.assertEqual(current['round']['remaining'], 0)
        with ThreadPoolExecutor(3) as pool:
            results = list(pool.map(lambda _: self.client.post('/api/daily-practice/next-round'), range(3)))
        self.assertTrue(all(r.status_code == 200 for r in results))
        ids = {r.json()['round']['id'] for r in results}
        self.assertEqual(len(ids), 1)
        new = results[0].json()
        self.assertIsNone(new['day'])
        self.assertEqual(new['round']['start_day'], '2026-12-07')
        self.assertEqual(self.client.get(self.day_url(rid, '2026-10-26')).status_code, 200)
        self.assertEqual(self.client.get('/api/daily-practice').json()['round']['id'], rid)
        self.day = '2026-12-07'
        self.assertEqual(self.client.get('/api/daily-practice').json()['round']['id'], next(iter(ids)))
        self.assertEqual(self.client.get('/api/daily-practice?round_id=' + rid).json()['day']['total'], 8)

    def test_backup_roundtrip_legacy_preservation_and_atomic_rejection(self):
        data = self.start()
        rid = data['round']['id']
        self.client.put(self.day_url(rid) + '/items/1', json={'choice': 'B'})
        backup = self.client.get('/api/backup').json()
        self.assertEqual(backup['version'], 9)
        self.client.put(self.day_url(rid) + '/items/1', json={'choice': 'A'})
        response = self.client.post('/api/backup/restore', json=backup)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get('/api/backup').json()['daily_practice'], backup['daily_practice'])
        for version in range(1, 6):
            old = copy.deepcopy(backup)
            old['version'] = version
            old.pop('daily_practice')
            if version < 5:
                old.pop('knowledge')
            self.assertEqual(self.client.post('/api/backup/restore', json=old).status_code, 200)
            self.assertEqual(self.client.get('/api/backup').json()['daily_practice'], backup['daily_practice'])
        before = self.client.get('/api/backup').json()
        for mutation in ['duplicate', 'missing', 'future_answer', 'seed', 'version', 'cursor', 'missing_field', 'overlap']:
            bad = copy.deepcopy(before)
            r = bad['daily_practice'][0]
            if mutation == 'duplicate': r['items'][1].update(paper_id=r['items'][0]['paper_id'], number=r['items'][0]['number'])
            if mutation == 'missing': r['items'].pop()
            if mutation == 'future_answer': r['items'][-1].update(result='wrong', answered_at=self.day + 'T12:00:00+08:00')
            if mutation == 'seed': r['seed'] = 'a' * 32
            if mutation == 'version': r['book_version'] = 'f' * 64
            if mutation == 'cursor': r['last_day'] = r['end_day']
            if mutation == 'missing_field': bad.pop('daily_practice')
            if mutation == 'overlap': bad['daily_practice'].append({**copy.deepcopy(r), 'id': 'b' * 32})
            response = self.client.post('/api/backup/restore', json=bad)
            self.assertEqual(response.status_code, 400, (mutation, response.text))
            self.assertEqual(self.client.get('/api/backup').json()['daily_practice'], before['daily_practice'])
        # A different round identity may not silently replace an overlapping local round.
        foreign = copy.deepcopy(before)
        foreign['daily_practice'][0]['id'] = 'c' * 32
        self.assertEqual(self.client.post('/api/backup/preview', json=foreign).status_code, 409)
        self.assertEqual(self.client.post('/api/backup/restore', json=foreign).status_code, 409)

    def test_round_restores_from_empty_and_preserves_future_schedule(self):
        data = self.start()
        backup = self.client.get('/api/backup').json()
        with server.db() as c:
            c.execute('DELETE FROM practice_rounds')
        self.assertEqual(self.client.post('/api/backup/restore', json=backup).status_code, 200)
        self.day = '2026-11-05'
        view = self.client.get('/api/daily-practice').json()
        self.assertEqual(len(view['history']), 11)
        with server.db() as c:
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM practice_items WHERE round_id=?', (data['round']['id'],)).fetchone()[0], 1576)

    def test_v8_manual_records_remain_intact_and_v9_requires_choices(self):
        data=self.start();rid=data['round']['id']
        with server.db() as c:
            c.execute("UPDATE practice_items SET result='wrong',answered_at=? WHERE round_id=? AND day=? AND position=1",
                      (p.now(),rid,self.day))
        legacy=self.client.get('/api/backup').json();legacy['version']=8
        for r in legacy['daily_practice']:
            r.pop('submissions')
            for i in r['items']:
                i.pop('choice');i.pop('selected_at')
        self.assertEqual(self.client.post('/api/backup/restore',json=legacy).status_code,200)
        with server.db() as c:
            self.assertEqual(p.item(c,rid,self.day,1)['result'],'wrong')
        current=self.client.get('/api/backup').json()
        self.assertEqual(current['version'],9)
        bad=copy.deepcopy(current);bad['daily_practice'][0]['items'][0].pop('choice')
        self.assertEqual(self.client.post('/api/backup/restore',json=bad).status_code,400)
        bad=copy.deepcopy(current);bad['daily_practice'][0].pop('submissions')
        self.assertEqual(self.client.post('/api/backup/restore',json=bad).status_code,400)
        self.assertEqual(self.client.get('/api/backup').json()['daily_practice'],current['daily_practice'])

    def test_beijing_midnight(self):
        self.date_patch.stop()
        class Clock(datetime):
            at = datetime(2026, 10, 26, 15, 59, 59, tzinfo=timezone.utc)
            @classmethod
            def now(cls, tz=None):
                return cls.at.astimezone(tz)
        with patch.object(p, 'datetime', Clock):
            self.assertEqual(p.today(), '2026-10-26')
            Clock.at += timedelta(seconds=1)
            self.assertEqual(p.today(), '2026-10-27')
        self.date_patch.start()


if __name__ == '__main__':
    unittest.main(verbosity=2)
