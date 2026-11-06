import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

SCRIPT='''
import streamlit as st
import pandas as pd
from track_condition_web import render_track_conditions
from analysis import analyze_csv
row=['福1','未勝利','ダ','1700','4','1','','試験馬',110,120,200,60,70,6,10,
     '202611070303010101','2023000001','騎手',3,'父','']
frame=pd.DataFrame([row])
records=render_track_conditions(st,frame)
batch=analyze_csv(frame,{},{},track_conditions=records)
st.text(batch.frame.iloc[0]['総合評価・コース相性判定'])
'''


class GoingControlTests(unittest.TestCase):
    def test_auto_fetch_reanalyzes_and_manual_apply_stops_auto(self):
        from datetime import datetime,time
        from track_conditions import JST,make_record
        day=datetime.now(JST).strftime('%Y%m%d')
        app=AppTest.from_string(SCRIPT.replace('20261107',day))
        app.session_state['going_auto_start']=time(0)
        app.session_state['going_auto_end']=time(23,59)
        app.run(timeout=30)
        def fetch(d,v):
            return [make_record(d,v,s,'重',source='jra') for s in ('芝','ダ')]
        with patch('track_condition_web.fetch_jra_track_conditions',side_effect=fetch) as mock:
            app.checkbox(key='going_auto_enabled').check().run(timeout=30)
            self.assertEqual(len(app.exception),0)
            self.assertIn('湿馬場arms特注','\n'.join(t.value for t in app.text))
            self.assertEqual(mock.call_count,1)
            app.selectbox(key=f'going_{day}_福島_ダ').set_value('良')
            app.button(key=f'FormSubmitter:going_{day}_福島_manual-手動指定を適用').click().run(timeout=30)
            self.assertEqual(len(app.exception),0)
            self.assertFalse(app.session_state['going_auto_enabled'])
            self.assertNotIn('湿馬場arms特注','\n'.join(t.value for t in app.text))

    def test_manual_change_clear_and_failed_fetch(self):
        app=AppTest.from_string(SCRIPT).run(timeout=30)
        self.assertEqual(len(app.exception),0)
        def text():return '\n'.join(t.value for t in app.text)
        self.assertNotIn('湿馬場arms特注',text())
        app.selectbox(key='going_20261107_福島_ダ').set_value('重')
        app.button(key='FormSubmitter:going_20261107_福島_manual-手動指定を適用').click().run(timeout=30)
        self.assertEqual(len(app.exception),0)
        self.assertIn('湿馬場arms特注',text())
        app.selectbox(key='going_20261107_福島_ダ').set_value('良')
        app.button(key='FormSubmitter:going_20261107_福島_manual-手動指定を適用').click().run(timeout=30)
        self.assertNotIn('湿馬場arms特注',text())
        app.selectbox(key='going_20261107_福島_ダ').set_value('重')
        app.button(key='FormSubmitter:going_20261107_福島_manual-手動指定を適用').click().run(timeout=30)
        with patch('track_condition_web.fetch_jra_track_conditions',side_effect=ValueError('未公表')):
            app.button(key='going_20261107_福島_fetch').click().run(timeout=30)
        self.assertEqual(len(app.exception),0)
        self.assertNotIn('湿馬場arms特注',text())
        self.assertTrue(any('未公表' in w.value for w in app.warning))


if __name__=='__main__':unittest.main()
