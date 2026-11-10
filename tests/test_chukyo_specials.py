"""Shared acceptance tests copied unchanged to the Web test suite."""
from pathlib import Path
from dataclasses import replace
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd

WEB = Path(__file__).resolve().parent.name == 'tests'
RULES = {
    'chukyo_t2200': ('芝',2200,'★中京芝2200特注★',110,(1,)),
    'chukyo_t1600': ('芝',1600,'★中京芝1600特注★',110,(1,2,3)),
    'chukyo_d1900': ('ダ',1900,'★中京ダ1900特注★',None,(1,)),
    'chukyo_d1400': ('ダ',1400,'★中京ダ1400特注★',120,(1,2)),
}


def evaluate(context):
    if WEB:
        from signals import DEFAULT_REGISTRY
        matches=DEFAULT_REGISTRY.evaluate(context)
    else:
        from special_rules import evaluate_pre_specials
        matches=evaluate_pre_specials(context)
    return {m.key:m.comment for m in matches if m.key in RULES}


def facts(key):
    surface,distance,_,threshold,_=RULES[key]
    return dict(venue='中京',surface=surface,distance=distance,frame=4,
                arms2=threshold or 1,arms2_rank=1,TUA_rank=1,track_condition='良')


def raw_frame(key):
    surface,distance,*_=RULES[key]
    return pd.DataFrame([
        ['名1','1勝クラス',surface,str(distance),str(fr),str(n),'',f'試験馬{n}',
         50,a,t,40,50,1,10,f'2026110707040101{n:02d}',f'20230000{n:02d}','騎手',3,'父','']
        for n,(fr,a,t) in enumerate(zip((1,4,2,5,1),(130,120,110,110,100),(20,20,19,18,17)),1)
    ])


class ChukyoSpecialTests(unittest.TestCase):
    def test_exact_names_and_zero_points(self):
        if WEB:
            from config import DEFAULT_SETTINGS
            rules=DEFAULT_SETTINGS.special_rules
            points=lambda r:r.score
        else:
            from special_rules import PRE_SPECIAL_RULES
            rules=PRE_SPECIAL_RULES
            points=lambda r:r.legacy_points
        found={r.key:r for r in rules if r.key in RULES}
        self.assertEqual(set(found),set(RULES))
        for key,r in found.items():
            self.assertEqual(r.comment,RULES[key][2])
            self.assertEqual(points(r),0)

    def test_all_frame_and_rank_boundaries(self):
        for key,(_,_,label,_,ranks) in RULES.items():
            for frame in range(1,9):
                for rank in range(0,6):
                    row=dict(facts(key),frame=frame)
                    row['TUA_rank' if key=='chukyo_d1900' else 'arms2_rank']=rank
                    expected=rank in ranks and (key=='chukyo_d1900' or frame<=4)
                    self.assertEqual(key in evaluate(row),expected,(key,frame,rank))

    def test_index_thresholds_and_no_tua_lower_limit(self):
        for key,(_,_,_,threshold,_) in RULES.items():
            if threshold is None:
                for value in (1,100,200):
                    self.assertIn(key,evaluate(dict(facts(key),TUA=value)))
                continue
            for delta in (-0.01,0,0.01):
                self.assertEqual(key in evaluate(dict(facts(key),arms2=threshold+delta)),delta>=0)
            self.assertNotIn(key,evaluate({k:v for k,v in facts(key).items() if k!='arms2'}))

    def test_going_good_only_for_d1900(self):
        for key in RULES:
            for going in (None,'良','稍重','重','不良'):
                self.assertEqual(key in evaluate(dict(facts(key),track_condition=going)),
                                 key!='chukyo_d1900' or going=='良')
            row={k:v for k,v in facts(key).items() if k!='track_condition'}
            self.assertEqual(key in evaluate(row),key!='chukyo_d1900')

    def test_wrong_course_or_missing_required_context(self):
        for key in RULES:
            row=facts(key)
            for change in ({'venue':'東京'},{'distance':999},{'surface':'ダ' if row['surface']=='芝' else '芝'}):
                self.assertNotIn(key,evaluate(dict(row,**change)))
            for field in ('venue','distance','surface'):
                self.assertNotIn(key,evaluate({k:v for k,v in row.items() if k!=field}))

    def test_pipeline_ranks_comments_scores_and_exports(self):
        from track_conditions import make_record,record_key
        for key,(_,_,label,_,_) in RULES.items():
            records={}
            if key=='chukyo_d1900':
                k=record_key('20261107','中京','ダ');records[k]=make_record(*k,'良')
            raw=raw_frame(key)
            expected={'chukyo_t2200':[True,False,False,False,False],
                      'chukyo_t1600':[True,True,True,False,False],
                      'chukyo_d1900':[True,True,False,False,False],
                      'chukyo_d1400':[True,True,False,False,False]}[key]
            if WEB:
                from analysis import analyze_csv
                from config import DEFAULT_SETTINGS
                from formatting import format_analysis_frame
                from export import build_target_csv,format_target_frame
                batch=analyze_csv(raw,{}, {'試験馬1':'既存コメント'},track_conditions=records)
                baseline=analyze_csv(raw,{}, {},track_conditions=records,settings=replace(
                    DEFAULT_SETTINGS,special_rules=tuple(r for r in DEFAULT_SETTINGS.special_rules if r.key not in RULES)))
                comments=batch.frame['総合評価・コース相性判定'].tolist()
                self.assertEqual(batch.frame['score'].tolist(),baseline.frame['score'].tolist())
                self.assertIn(label.strip('★'),build_target_csv(format_target_frame(batch.frame)))
                self.assertIn(label,format_analysis_frame(batch.frame,batch.notes).iloc[0]['総合評価・コース相性判定'])
                self.assertEqual([n['ranks']['arms2'] for n in batch.notes.values()],[1,2,3,3,5])
            else:
                import horse_app as desktop
                from qt_data_bridge import QtDataBridge
                from qt_export_service import export_target_csv,export_html
                bridge=QtDataBridge(course_stats={},qualified_jockeys=set(),frame_colors={})
                bridge.track_conditions=records
                rows=bridge.evaluate_frame(raw,external_comments={'試験馬1':'既存コメント'})
                original=desktop.evaluate_pre_specials
                with patch.object(desktop,'evaluate_pre_specials',side_effect=lambda r:tuple(x for x in original(r) if x.key not in RULES)):
                    baseline=bridge.evaluate_frame(raw)
                self.assertEqual([r['score'] for r in rows],[r['score'] for r in baseline])
                comments=[r['comment'] for r in rows]
                self.assertTrue(rows[0]['special'])
                self.assertEqual([r['ranks']['arms2'] for r in rows],[1,2,3,3,5])
                with tempfile.TemporaryDirectory() as tmp:
                    csv=Path(tmp)/'result.csv';html=Path(tmp)/'result.html'
                    export_target_csv(rows,str(csv),bridge);export_html(rows,str(html),bridge)
                    self.assertIn(label.strip('★'),csv.read_text(encoding='cp932'))
                    self.assertIn(label,html.read_text(encoding='utf-8-sig'))
            self.assertEqual([label in comment for comment in comments],expected,key)
            self.assertIn('既存コメント',comments[0])

    def test_d1900_going_change_removes_special(self):
        from track_conditions import make_record,record_key
        key='chukyo_d1900';label=RULES[key][2];k=record_key('20261107','中京','ダ')
        for value in ('良','重',None,'良'):
            records={} if value is None else {k:make_record(*k,value)}
            if WEB:
                from analysis import analyze_csv
                comment=analyze_csv(raw_frame(key),{},{},track_conditions=records).frame.iloc[0]['総合評価・コース相性判定']
            else:
                from qt_data_bridge import QtDataBridge
                bridge=QtDataBridge(course_stats={},qualified_jockeys=set(),frame_colors={});bridge.track_conditions=records
                comment=bridge.evaluate_frame(raw_frame(key))[0]['comment']
            self.assertEqual(label in comment,value=='良')


if __name__=='__main__':unittest.main()
