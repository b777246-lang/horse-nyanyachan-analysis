import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, Mock
from track_conditions import (JST, make_record, going_for, record_key, targets_from_frame)
from jra_track_condition import (select_records, venue_pages, course_slot, fetch_jra_track_conditions)


class TrackTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,7,10,0,tzinfo=JST)
        self.day='20261107';self.key=record_key(self.day,'福島','ダ')
    def test_manual_scoped_and_unknown(self):
        records={self.key:make_record(self.day,'福島','ダ','稍重',now=self.now)}
        self.assertEqual(going_for(records,*self.key),'稍重')
        for k in [('20261108','福島','ダ'),(self.day,'東京','ダ'),(self.day,'福島','芝')]:
            self.assertIsNone(going_for(records,*k))
        self.assertIsNone(going_for({},*self.key))
    def test_official_expiry_and_next_day(self):
        records={self.key:make_record(self.day,'福島','ダ','重',source='jra',now=self.now)}
        self.assertEqual(going_for(records,*self.key,now=self.now+timedelta(minutes=14)),'重')
        for t in [self.now-timedelta(seconds=1),self.now+timedelta(minutes=16),self.now+timedelta(days=1)]:
            self.assertIsNone(going_for(records,*self.key,now=t))
    def test_record_identity_cannot_be_forged_by_key(self):
        records={self.key:make_record(self.day,'東京','ダ','重',now=self.now)}
        self.assertIsNone(going_for(records,*self.key))
    def test_invalid_value_not_guessed(self):
        for v in ['不明','やや重','1',None]:
            with self.assertRaises(ValueError):make_record(self.day,'福島','ダ',v)
    def test_official_slots_dates_and_surfaces(self):
        payload={'kaisai_info':[dict(sort='C',kaisai_ymd=self.day,ba_s='良',ba_d='不良')]}
        records=select_records(payload,'C',self.day,'福島',now=self.now)
        self.assertEqual([(r['surface'],r['value']) for r in records],[('芝','良'),('ダ','不良')])
        for slot,day in [('A',self.day),('C','20261106')]:
            with self.assertRaises(ValueError):select_records(payload,slot,day,'福島',now=self.now)
    def test_empty_duplicate_and_invalid_official_response(self):
        row=dict(sort='C',kaisai_ymd=self.day,ba_s='良',ba_d='稍重')
        for payload in [{},{'kaisai_info':[]},{'kaisai_info':[row,row]},
                        {'kaisai_info':[dict(row,ba_d='不明')]},
                        {'kaisai_info':[dict(row,kaisai_ymd='20261106')]}]:
            with self.assertRaises(ValueError):select_records(payload,'C',self.day,'福島',now=self.now)
    def test_past_request_never_networks(self):
        with patch('jra_track_condition.requests.Session') as session:
            with self.assertRaises(ValueError):fetch_jra_track_conditions('20261106','福島',now=self.now)
            session.assert_not_called()
    def test_actual_page_shape(self):
        html='<div class="kaisai_tab"><a href="index.html">東京競馬場</a><a href="index3.html">福島競馬場</a></div><div id="baba" data-current-course="C"></div>'
        self.assertEqual(venue_pages(html)['福島'],'https://www.jra.go.jp/keiba/baba/index3.html')
        self.assertEqual(course_slot(html),'C')
    def test_fetch_uses_current_page_mapping_and_post(self):
        html='<div class="kaisai_tab"><a href="index2.html">福島競馬場</a></div>'
        responses=[Mock(content=html.encode('cp932')),Mock(content=b'<div id="baba" data-current-course="B"></div>'),
                   Mock(content='{"kaisai_info":[{"sort":"B","kaisai_ymd":"20261107","ba_s":"良","ba_d":"重"}]}'.encode('cp932'))]
        with patch('jra_track_condition._request',side_effect=responses) as request:
            records=fetch_jra_track_conditions(self.day,'福島',now=self.now)
            self.assertEqual(records[1]['value'],'重')
            self.assertEqual(request.call_args_list[1].args[2],'https://www.jra.go.jp/keiba/baba/index2.html')
            self.assertEqual(request.call_args_list[2].kwargs['data'],{'CNAME':'pw01iwtS3/CD'})
    def test_targets_use_ids_not_filename(self):
        import pandas as pd
        row=['福1','未勝利','ダ','1700','4','1','','試験馬',100,100,200,60,70,6,10,'202611070303010101','2023000001','騎手','3','父','']
        self.assertEqual(targets_from_frame(pd.DataFrame([row])),[(self.day,'福島')])
        row[15]=''
        self.assertEqual(targets_from_frame(pd.DataFrame([row])),[])


if __name__=='__main__':unittest.main()
