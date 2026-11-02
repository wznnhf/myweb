"""Learning calendars count actual work, once per question/day, in Beijing time."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import uuid

from fastapi.testclient import TestClient
from test_app import server


class ActivityTests(unittest.TestCase):
    def clear(self):
        with server.db() as c:
            for table in ['study_activity', 'practice_items', 'practice_rounds', 'daily_items', 'daily_batches',
                          'memberships', 'states', 'folders', 'settings', 'knowledge_reviews', 'knowledge_draws', 'knowledge_states']:
                c.execute('DELETE FROM '+table)

    def setUp(self):
        self.clear()
        self.client = TestClient(server.app)
        self.at = datetime(2026, 10, 27, 4, tzinfo=timezone.utc)
        self.patches = [patch.object(server, 'now', side_effect=lambda: self.at.isoformat()),
                        patch.object(server.activity, 'today', side_effect=lambda: self.at.astimezone(server.activity.SHANGHAI).date()),
                        patch.object(server.knowledge, 'now', side_effect=lambda: self.at),
                        patch.object(server.daily_review, 'today', return_value='2026-10-27'),
                        patch.object(server.daily_practice, 'today', return_value='2026-10-27'),
                        patch.object(server.daily_practice, 'now', side_effect=lambda: self.at.isoformat())]
        for p in self.patches:p.start()
        self.math = next(p for p in server.PAPERS.values() if p['subject']=='math')
        self.cs = next(p for p in server.PAPERS.values() if p['subject']=='408')

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.clear()

    def calendar(self, subject='math', area='all', year=None):
        params=dict(subject=subject,area=area)
        if year:params['year']=year
        r=self.client.get('/api/activity',params=params)
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def mark(self, number=1, area='library', status='mastered', paper=None):
        p=paper or self.math
        return self.client.patch(f'/api/questions/{p["id"]}/{number}',json=dict(status=status,activity_area=area))

    def test_read_notes_collection_and_scheduling_do_not_count(self):
        pid=self.math['id'];q=f'/api/questions/{pid}/1'
        self.client.get(q)
        self.client.put('/api/last-read',json=dict(paper_id=pid,number=1))
        self.client.patch(q,json=dict(note='只是整理笔记',revision=0))
        fid=self.client.post('/api/folders',json=dict(name='复习')).json()['id']
        self.client.put(f'/api/folders/{fid}/membership',json=dict(paper_id=pid,number=1,selected=True))
        self.client.post('/api/daily-review')
        self.client.post('/api/daily-practice/start')
        self.assertEqual(self.calendar()['total'],0)
        self.assertEqual(self.calendar('408')['total'],0)

    def test_same_day_dedup_sections_subjects_and_total_union(self):
        self.mark();self.mark(status='review');self.mark()
        self.mark(area='mistakes')
        self.mark(number=2)
        self.mark(paper=self.cs)
        self.assertEqual(self.calendar()['today_count'],2)
        self.assertEqual(self.calendar(area='library')['total'],2)
        self.assertEqual(self.calendar(area='mistakes')['total'],1)
        self.assertEqual(self.calendar('408')['today_count'],1)
        self.mark(status='unmarked')
        self.assertEqual(self.calendar()['today_count'],2)  # Grading corrections do not erase work already done.

    def test_concurrent_repeated_mark_is_one_question(self):
        with ThreadPoolExecutor(4) as pool:
            results=list(pool.map(lambda _:self.mark(),range(8)))
        self.assertTrue(all(r.status_code==200 for r in results))
        self.assertEqual(self.calendar()['total'],1)

    def test_beijing_midnight_and_streaks(self):
        self.at=datetime(2026,10,26,15,59,59,tzinfo=timezone.utc)
        self.mark()
        self.at+=timedelta(seconds=1)
        self.mark()
        data=self.calendar()
        self.assertEqual(data['total'],2)
        self.assertEqual((data['active_days'],data['current_streak'],data['longest_streak']),(2,2,2))
        self.at+=timedelta(days=1)
        self.assertEqual(self.calendar()['current_streak'],2)
        self.at+=timedelta(days=1)
        self.assertEqual(self.calendar()['current_streak'],0)

    def test_leap_year_padding_future_dates_and_color_levels(self):
        data=self.calendar(year=2024)
        self.assertEqual(len(data['days']),366)
        self.assertIn('2024-02-29',[d['day'] for d in data['days']])
        self.assertEqual(len(self.calendar()['days']),365)
        for n in range(1,23):self.mark(n)
        data=self.calendar(year=2026)
        today=next(d for d in data['days'] if d['day']=='2026-10-27')
        self.assertEqual((today['count'],today['level']),(22,4))
        self.assertTrue(next(d for d in data['days'] if d['day']=='2026-10-28')['future'])
        self.assertEqual([server.activity.level(n) for n in [0,1,4,5,9,10,19,20]],[0,1,1,2,2,3,3,4])
        self.assertEqual(self.client.get('/api/activity?year=2027').status_code,400)
        self.assertEqual(self.client.get('/api/activity?area=invalid').status_code,422)

    def test_daily_answers_count_once_without_replacing_historical_work(self):
        fid=self.client.post('/api/folders',json=dict(name='复习')).json()['id']
        self.client.put(f'/api/folders/{fid}/membership',json=dict(paper_id=self.math['id'],number=1,selected=True))
        self.client.post('/api/daily-review')
        url='/api/daily-review/2026-10-27/items/1'
        for result in ['wrong','correct','correct']:
            self.assertEqual(self.client.put(url,json=dict(result=result)).status_code,200)
        self.assertEqual(self.calendar(area='daily_review')['total'],1)
        self.assertEqual(self.calendar(area='library')['total'],0)
        self.client.put(url,json=dict(result=None))
        self.assertEqual(self.calendar(area='daily_review')['total'],1)
        data=self.client.post('/api/daily-practice/start').json()
        rid=data['round']['id'];url=f'/api/daily-practice/rounds/{rid}/days/2026-10-27/items/1'
        slots=data['day']['items'][0]['slots']
        self.client.put(url,json=dict(choice='A'*slots))
        self.client.put(url,json=dict(choice='B'*slots))
        self.assertEqual(self.calendar('408','daily_practice')['total'],1)
        self.at+=timedelta(days=1)
        self.client.put(url,json=dict(choice='A'*slots))
        self.assertEqual(self.calendar('408','daily_practice')['total'],2)

    def test_knowledge_rating_retry_and_undo_do_not_inflate_work(self):
        body=dict(field='ds',practice=False,request_id=str(uuid.uuid4()))
        draw=self.client.post('/api/knowledge/draw',json=body).json()['draw']
        self.client.post('/api/knowledge/draws/'+draw['id']+'/reveal')
        self.assertEqual(self.calendar('408','knowledge')['total'],0)
        url='/api/knowledge/draws/'+draw['id']+'/score'
        score=dict(rating=3,revision=draw['revision'],request_id='score:'+draw['id'])
        self.client.post(url,json=score);result=self.client.post(url,json=score).json()
        self.assertEqual(self.calendar('408','knowledge')['total'],1)
        latest=result['last_review']
        self.client.post('/api/knowledge/reviews/'+latest['id']+'/undo',json=dict(revision=latest['revision']))
        self.assertEqual(self.calendar('408','knowledge')['total'],1)

    def test_backfill_is_idempotent_and_does_not_guess_note_dates(self):
        with server.db() as c:
            c.execute('INSERT INTO daily_batches(day,created_at,pool_size,repeated_previous,subject) VALUES(?,?,?,?,?)',('2026-10-25',self.at.isoformat(),1,0,'math'))
            c.execute('INSERT INTO daily_items(day,position,paper_id,number,result,answered_at,subject) VALUES(?,?,?,?,?,?,?)',('2026-10-25',1,self.math['id'],1,'correct','2026-10-25T16:30:00+00:00','math'))
            server.activity.backfill(c,server.PAPERS);server.activity.backfill(c,server.PAPERS)
        data=self.calendar()
        self.assertEqual(data['total'],1)
        self.assertEqual(next(d['count'] for d in data['days'] if d['day']=='2026-10-26'),1)

    def test_backup_roundtrip_legacy_preservation_and_invalid_atomicity(self):
        self.mark();backup=self.client.get('/api/backup').json()
        self.assertEqual(backup['version'],9)
        self.assertEqual(self.client.post('/api/backup/preview',json=backup).json()['activity_records'],1)
        with server.db() as c:c.execute('DELETE FROM study_activity')
        self.assertEqual(self.client.post('/api/backup/restore',json=backup).status_code,200)
        self.mark(number=2)
        self.client.post('/api/backup/restore',json=backup)
        self.assertEqual(self.calendar()['total'],2)
        old=copy.deepcopy(backup);old['version']=6;old.pop('activity')
        self.assertEqual(self.client.post('/api/backup/restore',json=old).status_code,200)
        self.assertEqual(self.calendar()['total'],2)
        for mutation in ['duplicate','future','subject','unknown','time','missing']:
            bad=copy.deepcopy(backup)
            if mutation=='duplicate':bad['activity'].append(copy.deepcopy(bad['activity'][0]))
            if mutation=='future':bad['activity'][0]['day']='2026-10-28'
            if mutation=='subject':bad['activity'][0]['subject']='408'
            if mutation=='unknown':bad['activity'][0]['item_id']='q:missing:1'
            if mutation=='time':bad['activity'][0]['performed_at']='2026-10-26T00:00:00+00:00'
            if mutation=='missing':bad.pop('activity')
            response=self.client.post('/api/backup/restore',json=bad)
            self.assertEqual(response.status_code,400,(mutation,response.text))
            self.assertEqual(self.calendar()['total'],2)


if __name__=='__main__':unittest.main(verbosity=2)
