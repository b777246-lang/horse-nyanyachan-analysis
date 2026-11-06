import unittest
from datetime import datetime,time,timedelta
from unittest.mock import Mock
from track_conditions import JST,make_record,record_key
from track_condition_schedule import run_scheduled,schedule_slot


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,7,9,30,tzinfo=JST)
        self.state=dict(going_auto_enabled=True)
        self.targets=[('20261107','福島'),('20261107','京都'),('20261106','東京')]
    def fetcher(self,now):
        return Mock(side_effect=lambda d,v:[make_record(d,v,s,'重',source='jra',now=now) for s in ('芝','ダ')])
    def test_time_boundaries(self):
        for hour,minute,expected in [(7,59,None),(8,0,0),(8,14,0),(8,15,15),(16,30,30),(16,31,None)]:
            slot=schedule_slot(self.now.replace(hour=hour,minute=minute),time(8),time(16,30))
            self.assertEqual(slot.minute if slot else None,expected)
        self.assertIsNone(schedule_slot(self.now,time(16),time(8)))
        self.assertEqual(schedule_slot(self.now.replace(hour=16,minute=30,second=45),time(8),time(16,30)).minute,30)
    def test_all_today_venues_and_no_repeat_until_next_slot(self):
        fetch=self.fetcher(self.now)
        self.assertTrue(run_scheduled(self.state,self.targets,fetch,now=self.now))
        self.assertEqual(fetch.call_count,2)
        self.assertFalse(run_scheduled(self.state,self.targets,fetch,now=self.now+timedelta(minutes=14)))
        later=self.now+timedelta(minutes=15);fetch=self.fetcher(later)
        self.assertTrue(run_scheduled(self.state,self.targets,fetch,now=later))
        self.assertEqual(fetch.call_count,2)
    def test_fixed_schedule_29_slots_and_ignores_old_settings(self):
        self.state.update(going_auto_start=time(8),going_auto_end=time(20))
        targets=[self.targets[0]]
        before=self.now.replace(hour=9,minute=29)
        fetch=Mock()
        run_scheduled(self.state,targets,fetch,now=before)
        fetch.assert_not_called()
        times=[]
        for minute in range(421):
            now=self.now+timedelta(minutes=minute)
            def retrieve(d,v):
                times.append(now)
                return [make_record(d,v,s,'重',source='jra',now=now) for s in ('芝','ダ')]
            run_scheduled(self.state,targets,retrieve,now=now)
        self.assertEqual(len(times),29)
        self.assertEqual(times[0].strftime('%H:%M'),'09:30')
        self.assertEqual(times[-1].strftime('%H:%M'),'16:30')
        run_scheduled(self.state,targets,fetch,now=self.now.replace(hour=16,minute=31))
        fetch.assert_not_called()
    def test_no_network_disabled_outside_window_or_other_date(self):
        fetch=Mock()
        self.state['going_auto_enabled']=False
        run_scheduled(self.state,self.targets,fetch,now=self.now)
        self.state['going_auto_enabled']=True
        run_scheduled(self.state,self.targets,fetch,now=self.now.replace(hour=18))
        run_scheduled(self.state,[('20261106','東京')],fetch,now=self.now)
        fetch.assert_not_called()
    def test_failure_clears_previous_values_and_waits_next_slot(self):
        key=record_key('20261107','福島','ダ')
        self.state['track_conditions']={key:make_record(*key,'重',now=self.now)}
        fetch=Mock(side_effect=ValueError('未公表'))
        self.assertTrue(run_scheduled(self.state,[self.targets[0]],fetch,now=self.now))
        self.assertNotIn(key,self.state['track_conditions'])
        run_scheduled(self.state,[self.targets[0]],fetch,now=self.now+timedelta(seconds=30))
        self.assertEqual(fetch.call_count,1)
        self.assertIn('未公表',self.state['going_auto_status'])
    def test_resume_only_latest_slot_no_catchup_burst(self):
        fetch=self.fetcher(self.now)
        run_scheduled(self.state,[self.targets[0]],fetch,now=self.now)
        later=self.now+timedelta(hours=2,minutes=7);fetch=self.fetcher(later)
        run_scheduled(self.state,[self.targets[0]],fetch,now=later)
        self.assertEqual(fetch.call_count,1)
    def test_recent_manual_fetch_not_repeated(self):
        self.state['track_conditions']={record_key('20261107','福島',s):make_record('20261107','福島',s,'良',source='jra',now=self.now) for s in ('芝','ダ')}
        fetch=Mock();run_scheduled(self.state,[self.targets[0]],fetch,now=self.now+timedelta(minutes=2));fetch.assert_not_called()
    def test_bad_partial_or_wrong_date_response_not_published(self):
        for records in [[],[make_record('20261107','福島','芝','良',source='jra',now=self.now)],
                        [make_record('20261106','福島',s,'良',source='jra',now=self.now) for s in ('芝','ダ')]]:
            state=dict(self.state)
            run_scheduled(state,[self.targets[0]],Mock(return_value=records),now=self.now)
            self.assertEqual(state['track_conditions'],{})
            self.assertIn('取得失敗',state['going_auto_status'])
    def test_expiry_outside_schedule_still_requests_reanalysis(self):
        key=record_key('20261107','福島','ダ')
        self.state['track_conditions']={key:make_record(*key,'重',source='jra',now=self.now)}
        fetch=Mock()
        self.assertTrue(run_scheduled(self.state,self.targets,fetch,now=self.now.replace(hour=17)))
        fetch.assert_not_called()


if __name__=='__main__':unittest.main()
