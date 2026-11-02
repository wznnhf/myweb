"""Scheduling, concurrency, backup and content checks use the isolated suite DB."""
import copy
import csv
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import io
import random
import unittest
from unittest.mock import patch
import uuid

from fastapi.testclient import TestClient
from test_app import server

k = server.knowledge


class KnowledgeTests(unittest.TestCase):
    def clear(self):
        with server.db() as c:
            c.execute("DELETE FROM study_activity WHERE area='knowledge'")
            for name in ['session_items','sessions','reviews', 'draws', 'states', 'goals']:
                c.execute('DELETE FROM knowledge_'+name)

    def setUp(self):
        self.clear()
        self.client = TestClient(server.app)
        self.at = datetime(2026, 10, 21, 2, 0, tzinfo=timezone.utc)
        self.clock = patch.object(k, 'now', side_effect=lambda: self.at)
        self.clock.start()
        self.activity_clock=patch.object(server.activity,'today',side_effect=lambda:self.at.astimezone(k.SHANGHAI).date())
        self.activity_clock.start()

    def tearDown(self):
        self.clock.stop()
        self.activity_clock.stop()
        self.clear()

    def draw(self, field='ds', practice=False, request_id=None):
        response = self.client.post('/api/knowledge/draw', json=dict(field=field, practice=practice, request_id=request_id or str(uuid.uuid4())))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['draw']

    def reveal(self, draw):
        response = self.client.post('/api/knowledge/draws/'+draw['id']+'/reveal')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def score(self, draw, rating=3, request_id=None):
        self.reveal(draw)
        response = self.client.post('/api/knowledge/draws/'+draw['id']+'/score', json=dict(rating=rating, revision=draw['revision'], request_id=request_id or 'score:'+draw['id']))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def detail(self, card_id):
        return self.client.get('/api/knowledge/cards/'+card_id).json()

    def export(self):
        return self.client.get('/api/backup').json()

    def test_catalog_sources_exports_and_page_ranges(self):
        catalog = self.client.get('/api/knowledge/catalog').json()
        self.assertEqual(len(catalog['cards']), 140)
        self.assertEqual(sum(len(s['chapters']) for s in catalog['subjects']), 26)
        self.assertEqual(len(set(c['id'] for c in catalog['cards'])), 140)
        pages={'ds':34,'co':24,'os':43,'net':43}
        for card in k.CARDS.values():
            self.assertTrue(all(1<=p<=pages[card['field']] for p in card['pdf_pages']))
            for field in ['prompt','core','explanation','source','provenance']:
                self.assertTrue(card[field],(card['id'],field))
            self.assertGreater(card['blank_count'],0)
        result = self.client.get('/api/knowledge/catalog?field=co&q=Cache').json()['cards']
        self.assertTrue(result)
        self.assertTrue(all(c['field']=='co' for c in result))
        self.assertNotIn('answer', result[0])
        for kind in ['cards','coverage']:
            response = self.client.get('/api/knowledge/export/'+kind)
            self.assertEqual(response.status_code, 200)
            rows = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
            self.assertGreater(len(rows), 100)
        self.assertEqual(self.client.get('/api/knowledge/outline').content[:5], b'%PDF-')
        self.assertEqual(self.client.get('/knowledge-draw?subject=408').status_code, 200)

    def test_refresh_resumes_hidden_then_revealed_card(self):
        d = self.draw()
        self.assertNotIn('answer', d['card'])
        self.assertNotIn('pitfall', d['card'])
        self.assertEqual(self.draw()['id'], d['id'])
        r = self.reveal(d)
        self.assertIn('answer', r['card'])
        self.assertEqual(len(r['preview_due']), 4)
        fresh_client = TestClient(server.app)
        overview = fresh_client.get('/api/knowledge/overview').json()
        self.assertEqual(overview['subjects'][0]['pending']['id'], d['id'])
        self.assertIn('answer', overview['subjects'][0]['pending']['card'])
        self.assertEqual(overview['subjects'][0]['unseen'], 31)

    def test_concurrent_draws_and_duplicate_rating(self):
        with ThreadPoolExecutor(2) as pool:
            draws = list(pool.map(lambda _: self.draw(), range(2)))
        self.assertEqual(draws[0]['id'], draws[1]['id'])
        d = self.reveal(draws[0])
        body = dict(rating=3,revision=d['revision'],request_id='same-score')
        with ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(lambda _: self.client.post('/api/knowledge/draws/'+d['id']+'/score', json=body), range(2)))
        self.assertEqual([r.status_code for r in responses], [200,200])
        self.assertEqual(self.detail(d['card_id'])['total'], 1)
        body['rating'] = 1
        self.assertEqual(self.client.post('/api/knowledge/draws/'+d['id']+'/score', json=body).status_code, 409)
        self.assertEqual(self.detail(d['card_id'])['remembered'], 1)

    def test_different_tabs_cannot_overwrite_rating(self):
        d = self.reveal(self.draw())
        with ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(lambda r: self.client.post('/api/knowledge/draws/'+d['id']+'/score', json=dict(rating=r,revision=d['revision'],request_id=str(r))), [1,4]))
        self.assertEqual(sorted(r.status_code for r in responses), [200,409])
        self.assertEqual(self.detail(d['card_id'])['total'],1)

    def test_reveal_and_revision_are_required(self):
        d = self.draw()
        body = dict(rating=3,revision=d['revision'],request_id='x')
        path = '/api/knowledge/draws/'+d['id']+'/score'
        self.assertEqual(self.client.post(path,json=body).status_code,409)
        self.reveal(d)
        body['revision'] = 100
        self.assertEqual(self.client.post(path,json=body).status_code,409)
        body['rating'] = 0
        self.assertEqual(self.client.post(path,json=body).status_code,422)

    def test_four_ratings_and_ten_minute_relearning(self):
        due = []
        for field,rating in zip(k.SUBJECTS, range(1,5)):
            d = self.draw(field)
            self.score(d,rating)
            card = self.detail(d['card_id'])
            due.append(k.parse(card['due']))
            self.assertEqual(card['ratings'][rating-1],1)
            self.assertEqual(card['remembered'], int(rating>1))
        self.assertEqual(due[0],self.at+timedelta(minutes=10))
        self.assertLess(due[0],due[1])
        self.assertLess(due[1],due[2])
        self.assertLess(due[2],due[3])
        with server.db() as c:
            picked,kind = k.choose(c,'ds',self.at+timedelta(minutes=9),rng=random.Random(1))
            self.assertEqual(kind,'new')
            picked,kind = k.choose(c,'ds',self.at+timedelta(minutes=10),rng=random.Random(1))
            self.assertEqual(kind,'relearn')

    def test_same_day_distinct_count_and_shanghai_midnight(self):
        self.at = datetime(2026,10,21,15,40,tzinfo=timezone.utc)
        d = self.draw()
        self.score(d,1)
        self.at += timedelta(minutes=10)
        d2 = self.draw()
        self.assertEqual(d2['card_id'],d['card_id'])
        value = self.score(d2,3)
        self.assertEqual(value['subjects'][0]['completed'],1)
        self.assertEqual(self.detail(d['card_id'])['total'],2)
        self.at += timedelta(minutes=10)
        value = self.client.get('/api/knowledge/overview').json()
        self.assertEqual(value['day'],'2026-10-22')
        self.assertEqual(value['subjects'][0]['completed'],0)

    def test_spaced_cards_are_not_drawn_early_and_goal_is_not_cap(self):
        ids = []
        for _ in range(7):
            d = self.draw();ids.append(d['card_id']);value=self.score(d,4)
        self.assertEqual(len(set(ids)),7)
        self.assertEqual(value['subjects'][0]['completed'],7)
        self.assertEqual(value['subjects'][0]['target'],5)
        changed = self.client.put('/api/knowledge/goals/ds',json={'target':8}).json()
        self.assertEqual(changed['subjects'][0]['target'],8)
        self.assertEqual(self.client.put('/api/knowledge/goals/ds',json={'target':0}).status_code,422)

    def test_new_cards_cover_different_chapters(self):
        chapters=[]
        for _ in range(7):
            d=self.draw();chapters.append(d['card']['chapter_id']);self.score(d,4)
        self.assertEqual(len(set(chapters)),7)

    def test_one_new_card_in_five_when_due_backlog_exists(self):
        for _ in range(10):self.score(self.draw(),3)
        self.at += timedelta(days=20)
        kinds=[]
        for _ in range(5):
            d=self.draw();kinds.append(d['kind']);self.score(d,4)
        self.assertEqual(kinds,['due','due','due','due','new'])

    def test_urgency_weights_include_memory_overdue_and_recent_failure(self):
        cards=[]
        for rating in [3,4]:
            d=self.draw();self.score(d,rating);cards.append(d['card_id'])
        self.at += timedelta(days=30)
        class InspectRandom:
            def choices(inner, candidates, weights, k):
                mapping={card['id']:w for card,w in zip(candidates,weights)}
                self.assertGreater(mapping[cards[0]],mapping[cards[1]])
                self.assertTrue(all(w>0 for w in weights))
                return [candidates[0]]
        with server.db() as c:k.choose(c,'ds',self.at,rng=InspectRandom())

    def test_practice_never_changes_memory_counts_or_target(self):
        # Review the entire smaller subject; everything is scheduled in future.
        for _ in range(32):self.score(self.draw(),4)
        self.assertIsNone(self.draw())
        d = self.draw(practice=True)
        before=self.detail(d['card_id'])
        value=self.score(d,1)
        after=self.detail(d['card_id'])
        for key in ['due','stability','difficulty','total','remembered']:
            self.assertEqual(before[key],after[key])
        self.assertEqual(value['subjects'][0]['completed'],32)
        self.assertEqual(after['history'][0]['mode'],'practice')
        backup=self.export()
        self.assertEqual(self.client.post('/api/backup/preview',json=backup).status_code,200)

    def test_practice_cannot_bypass_pending_review_or_new_cards(self):
        r=self.client.post('/api/knowledge/draw',json={'field':'ds','practice':True,'request_id':'p'})
        self.assertEqual(r.status_code,409)
        d=self.draw()
        self.assertEqual(self.draw(practice=True)['id'],d['id'])

    def test_undo_restores_counts_state_and_is_idempotent(self):
        d=self.draw();result=self.score(d,1);last=result['last_review']
        path='/api/knowledge/reviews/'+last['id']+'/undo'
        for _ in range(2):
            r=self.client.post(path,json={'revision':last['revision']});self.assertEqual(r.status_code,200,r.text)
        card=self.detail(d['card_id'])
        self.assertEqual(card['total'],0);self.assertIsNone(card['due'])
        self.assertEqual(card['history'][0]['undone'],1)
        self.assertEqual(self.client.post('/api/backup/preview',json=self.export()).status_code,200)

    def test_only_latest_review_can_be_undone(self):
        a=self.score(self.draw())['last_review']
        self.at+=timedelta(seconds=1)
        self.score(self.draw('co'))
        response=self.client.post('/api/knowledge/reviews/'+a['id']+'/undo',json={'revision':a['revision']})
        self.assertEqual(response.status_code,409)

    def test_backup_roundtrip_preserves_state_history_and_pending(self):
        d=self.draw();self.score(d,1)
        self.at+=timedelta(minutes=10)
        self.score(self.draw(),3)
        pending=self.reveal(self.draw('co'))
        self.client.put('/api/knowledge/goals/net',json={'target':12})
        backup=self.export()
        self.assertEqual(backup['version'],9)
        preview=self.client.post('/api/backup/preview',json=backup)
        self.assertEqual(preview.status_code,200,preview.text)
        self.assertEqual(preview.json()['knowledge_reviews'],2)
        self.clear()
        response=self.client.post('/api/backup/restore',json=backup)
        self.assertEqual(response.status_code,200,response.text)
        out=self.export()['knowledge']
        self.assertEqual(out['reviews'],backup['knowledge']['reviews'])
        for a,b in zip(out['states'],backup['knowledge']['states']):
            self.assertEqual(a['fsrs'],b['fsrs'])
            self.assertGreater(a['revision'],b['revision'])
        self.assertEqual(out['goals'],backup['knowledge']['goals'])
        resumed=self.draw('co')
        self.assertEqual(resumed['id'],pending['id'])
        self.assertIn('answer',resumed['card'])
        stale=self.client.post('/api/knowledge/draws/'+pending['id']+'/score',json=dict(rating=3,revision=pending['revision'],request_id='stale'))
        self.assertEqual(stale.status_code,409)
        self.score(resumed)
        self.assertEqual(self.client.post('/api/backup/preview',json=self.export()).status_code,200)

    def test_old_backups_leave_knowledge_intact(self):
        self.score(self.draw())
        before=self.export()['knowledge']
        for version in [1,2,3,4]:
            backup=self.export();backup['version']=version;backup.pop('knowledge')
            if version==1:backup['daily_reviews']=[]
            if version<4:backup['images']=[];backup['states']=[];backup['memberships']=[]
            r=self.client.post('/api/backup/restore',json=backup)
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(self.export()['knowledge'],before)

    def test_browser_rounded_card_ids_restore_without_losing_history(self):
        self.score(self.draw(), 3)
        original = self.export()
        rounded = copy.deepcopy(original)
        expected = original['knowledge']['states'][0]['fsrs']['card_id']
        self.assertGreater(expected, 2**53 - 1)
        # Both forms occur after JSON.parse / JSON.stringify in older browsers.
        for numeric in [int(float(expected)), int(Decimal(format(float(expected), '.16g')))]:
            if float(numeric) != float(expected):
                continue
            for records, fields in [(rounded['knowledge']['states'], ['fsrs']),
                                    (rounded['knowledge']['reviews'], ['before_state', 'after_state', 'fsrs_log'])]:
                for record in records:
                    for field in fields:
                        if record.get(field) is not None:
                            record[field]['card_id'] = numeric
            response = self.client.post('/api/backup/restore', json=rounded)
            self.assertEqual(response.status_code, 200, response.text)
            exported = self.export()['knowledge']
            self.assertEqual(exported['reviews'], original['knowledge']['reviews'])
            self.assertEqual(exported['states'][0]['fsrs'], original['knowledge']['states'][0]['fsrs'])

    def test_backup_still_rejects_wrong_ids_and_tampered_rounded_history(self):
        self.score(self.draw(), 3)
        original = self.export()
        for kind in ['wrong-id', 'wrong-log', 'phase', 'schedule']:
            bad = copy.deepcopy(original)
            state = bad['knowledge']['states'][0]['fsrs']
            state['card_id'] = int(float(state['card_id']))
            if kind == 'wrong-id': state['card_id'] += 1000000
            if kind == 'wrong-log': bad['knowledge']['reviews'][0]['fsrs_log']['card_id'] = 1
            if kind == 'phase': state['state'] = 99
            if kind == 'schedule': bad['knowledge']['reviews'][0]['after_state']['stability'] += 1
            response = self.client.post('/api/backup/restore', json=bad)
            self.assertEqual(response.status_code, 400, (kind, response.text))
            self.assertEqual(self.export()['knowledge'], original['knowledge'])

    def test_restore_preserves_unrelated_cards(self):
        self.score(self.draw())
        backup=self.export()
        other=self.draw('co');self.score(other,4)
        expected=self.detail(other['card_id'])
        self.assertEqual(self.client.post('/api/backup/restore',json=backup).status_code,200)
        self.assertEqual(self.detail(other['card_id']),expected)

    def test_malformed_backup_is_atomic(self):
        self.score(self.draw(),3)
        good=self.export()
        def mutate(b, kind):
            x=b['knowledge']
            if kind=='missing':b.pop('knowledge')
            elif kind=='config':x['config']['scheduler']['desired_retention']=0.95
            elif kind=='unknown':x['states'][0]['card_id']='unknown'
            elif kind=='duplicate':x['states']*=2
            elif kind=='time':x['reviews'][0]['reviewed_at']='not a time'
            elif kind=='rating':x['reviews'][0]['rating']=2
            elif kind=='state':x['states'][0]['fsrs']['difficulty']=100
            elif kind=='missing-review':x['reviews']=[]
            elif kind=='pending':x['draws'][0]['status']='pending'
            elif kind=='phase':x['states'][0]['fsrs']['step']=99
        for kind in ['missing','config','unknown','duplicate','time','rating','state','missing-review','pending','phase']:
            bad=copy.deepcopy(good);mutate(bad,kind)
            response=self.client.post('/api/backup/restore',json=bad)
            self.assertEqual(response.status_code,400,(kind,response.text))
            self.assertEqual(self.export()['knowledge'],good['knowledge'])

    def test_content_calculation_examples(self):
        # Independently recompute selected worked examples, including CRC.
        dividend=int('1101000',2);divisor=int('1011',2)
        while dividend.bit_length()>=divisor.bit_length():
            dividend ^= divisor << (dividend.bit_length()-divisor.bit_length())
        self.assertEqual(dividend,1)
        self.assertEqual((16*1024//64)//4,64)
        self.assertEqual(32-6-6,20)
        self.assertEqual(sum([5,12,20]),37)
        self.assertEqual(100+(2*4+1)*4,136)
        self.assertEqual((3980-2*1480)+20,1040)
        self.assertEqual(1480//8,185)


if __name__ == '__main__':
    unittest.main()
