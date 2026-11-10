import unittest
import pandas as pd
from analysis import analyze_csv
from config import DEFAULT_SETTINGS
from signals import DEFAULT_REGISTRY
from track_conditions import make_record,record_key
from export import build_target_csv,format_target_frame
from formatting import format_analysis_frame


def frame(surface='ダ',distance=1700):
    return pd.DataFrame([['福1','未勝利',surface,str(distance),str(fr),str(n),'',f'試験馬{n}',a,a,t,s,70,6,10,
                          f'2026110703030101{n:02d}',f'20230000{n:02d}','騎手',3,'父','']
                         for n,(fr,a,t,s) in enumerate([(1,110,200,60),(4,110,200,60),(5,90,180,50)],1)])


def tokyo_frame(s_values=(60, 59, 50)):
    return pd.DataFrame([['東1','1勝クラス','ダ','1600',str(fr),str(n),'',f'東京試験馬{n}',
                          100,100,180,s,65,6,10,
                          f'2026110705010101{n:02d}',f'20230010{n:02d}','騎手',3,'父','']
                         for n,(fr,s) in enumerate(zip((1,2,3),s_values),1)])


class WebGoingTests(unittest.TestCase):
    def test_tokyo_d1600_s_single_boundaries_and_going(self):
        key=record_key('20261107','東京','ダ')
        for value in (None,'良','稍重','重','不良'):
            records={} if value is None else {key:make_record(*key,value)}
            batch=analyze_csv(tokyo_frame(),{},{},track_conditions=records)
            expected={'tokyo_d1600_s_win'} if value in ('稍重','重','不良') else set()
            self.assertEqual({m.key for m in batch.recommendations[0].specials},expected)
            self.assertNotIn('tokyo_d1600_s_win',
                             {m.key for m in batch.recommendations[1].specials})
        for values in ((59.99,59,50),(60,60,50)):
            batch=analyze_csv(tokyo_frame(values),{},{},
                              track_conditions={key:make_record(*key,'重')})
            matches=['tokyo_d1600_s_win' in {m.key for m in part.specials}
                     for part in batch.recommendations.values()]
            self.assertEqual(matches,[False,False,False] if values[0] < 60 else [True,True,False])

    def test_turf_ties_frames(self):
        batch=analyze_csv(frame('芝',1200),{},{})
        for n in (0,1):
            self.assertEqual({m.key for m in batch.recommendations[n].specials},
                             {'fukushima_t1200_s','fukushima_t1200_tua'})
        self.assertEqual(batch.recommendations[2].specials,())
    def test_going_all_states_and_scoping(self):
        for value in (None,'良','稍重','重','不良'):
            key=record_key('20261107','福島','ダ');records={} if value is None else {key:make_record(*key,value)}
            batch=analyze_csv(frame(),{},{},track_conditions=records)
            for n in (0,1):
                expected={'fukushima_d1700_arms','fukushima_d1700_arms2'} if value in ('稍重','重','不良') else set()
                self.assertEqual({m.key for m in batch.recommendations[n].specials},expected)
            self.assertEqual(batch.recommendations[2].specials,())
        key=record_key('20261108','福島','ダ')
        batch=analyze_csv(frame(),{},{},track_conditions={key:make_record(*key,'重')})
        self.assertEqual(batch.recommendations[0].specials,())
    def test_export_and_html_after_state_reversal(self):
        key=record_key('20261107','福島','ダ')
        for value in ('重','良'):
            batch=analyze_csv(frame(),{},{},track_conditions={key:make_record(*key,value)})
            csv=build_target_csv(format_target_frame(batch.frame))
            self.assertEqual('福島ダ1700湿馬場arms特注' in csv,value=='重')
            shown=format_analysis_frame(batch.frame,batch.notes)
            self.assertEqual('福島ダ1700湿馬場arms特注' in shown.iloc[0]['総合評価・コース相性判定'],value=='重')
            for idx,parts in batch.recommendations.items():
                self.assertEqual(batch.frame.iloc[idx]['score'],parts.legacy.score)
    def test_no_new_value_thresholds(self):
        row=dict(venue='福島',surface='芝',distance=1200,frame=4,S_rank=1,TUA_rank=1,S=10,TUA=20)
        self.assertEqual(len(DEFAULT_REGISTRY.evaluate(row)),2)
        row['frame']=5
        self.assertEqual(DEFAULT_REGISTRY.evaluate(row),())


if __name__=='__main__':unittest.main()
