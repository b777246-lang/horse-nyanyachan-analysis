"""Run the same acceptance cases against Desktop and Web special pipelines."""
from pathlib import Path
import tempfile
import unittest
import pandas as pd

WEB = Path(__file__).resolve().parent.name == 'tests'
NEW_KEYS = {'fukushima_t1800_win', 'fukushima_t2000'}


def matches(context):
    if WEB:
        from signals import DEFAULT_REGISTRY
        rules = DEFAULT_REGISTRY.evaluate(context)
    else:
        from special_rules import evaluate_pre_specials
        rules = evaluate_pre_specials(context)
    return {r.key: r.comment for r in rules if r.key in NEW_KEYS}


def frame(distance, arms=(90,90,89.99), frames=(1,4,5)):
    return pd.DataFrame([
        ['福1','未勝利','芝',str(distance),str(fr),str(n),'',f'試験馬{n}',a,100,200,50,60,1,10,
         f'2026110703030101{n:02d}',f'20230000{n:02d}','騎手',3,'父','']
        for n,(a,fr) in enumerate(zip(arms,frames),1)
    ])


class MiddleDistanceTests(unittest.TestCase):
    def test_1800_frames_without_value_or_going_limit(self):
        for fr in range(0,10):
            for value in (30,90,110):
                context=dict(venue='福島',surface='芝',distance=1800,frame=fr,arms=value,arms_rank=1)
                expected={'fukushima_t1800_win':'★福島芝1800単勝特注★'} if fr in (1,2,3,4) else {}
                self.assertEqual(matches(context),expected)

    def test_2000_exact_90_and_any_frame(self):
        for fr in range(1,9):
            for value in (89.99,90,90.01):
                context=dict(venue='福島',surface='芝',distance=2000,frame=fr,arms=value,arms_rank=1)
                expected={'fukushima_t2000':'★福島芝2000特注★'} if value>=90 else {}
                self.assertEqual(matches(context),expected)

    def test_wrong_course_rank_and_missing_required_fields(self):
        for distance in (1800,2000):
            base=dict(venue='福島',surface='芝',distance=distance,frame=4,arms=90,arms_rank=1)
            for changes in ({'venue':'京都'},{'surface':'ダ'},{'distance':1600},{'arms_rank':2},{'arms_rank':0}):
                self.assertEqual(matches(dict(base,**changes)),{})
            for field in ('venue','surface','distance','arms_rank'):
                self.assertEqual(matches({k:v for k,v in base.items() if k!=field}),{})
        self.assertEqual(matches(dict(venue='福島',surface='芝',distance=2000,arms_rank=1)),{})

    def test_weather_does_not_filter_either_rule(self):
        for distance in (1800,2000):
            for going in (None,'良','稍重','重','不良'):
                self.assertEqual(len(matches(dict(venue='福島',surface='芝',distance=distance,
                    frame=4,arms=90,arms_rank=1,track_condition=going))),1)

    def test_full_pipeline_ties_comments_and_exports(self):
        for distance,label in [(1800,'★福島芝1800単勝特注★'),(2000,'★福島芝2000特注★')]:
            raw=frame(distance)
            if WEB:
                from analysis import analyze_csv
                from export import build_target_csv,format_target_frame
                from formatting import format_analysis_frame
                batch=analyze_csv(raw,{},{})
                self.assertEqual([r['ranks']['arms'] for r in batch.notes.values()],[1,1,3])
                self.assertEqual(batch.frame['総合評価・コース相性判定'].str.contains(label,regex=False).tolist(),[True,True,False])
                text=build_target_csv(format_target_frame(batch.frame))
                self.assertIn(label.strip('★'),text)
                shown=format_analysis_frame(batch.frame,batch.notes)
                self.assertIn(label,shown.iloc[0]['総合評価・コース相性判定'])
                self.assertIn('<span',shown.iloc[0]['総合評価・コース相性判定'])
                for idx,parts in batch.recommendations.items():
                    self.assertEqual(batch.frame.iloc[idx]['score'],parts.legacy.score)
            else:
                from qt_data_bridge import QtDataBridge
                from qt_export_service import export_target_csv,export_html
                bridge=QtDataBridge(course_stats={},qualified_jockeys=set(),frame_colors={})
                rows=bridge.evaluate_frame(raw)
                self.assertEqual([r['ranks']['arms'] for r in rows],[1,1,3])
                self.assertEqual([label in r['comment'] for r in rows],[True,True,False])
                self.assertTrue(rows[0]['special'])
                with tempfile.TemporaryDirectory() as tmp:
                    csv=Path(tmp)/'result.csv';html=Path(tmp)/'result.html'
                    export_target_csv(rows,str(csv),bridge)
                    export_html(rows,str(html),bridge)
                    self.assertIn(label,csv.read_text(encoding='cp932'))
                    self.assertIn(label,html.read_text(encoding='utf-8-sig'))

    def test_1800_outer_top_runner_not_promoted_to_inner(self):
        raw=frame(1800,arms=(89,88,90),frames=(1,4,5))
        if WEB:
            from analysis import analyze_csv
            batch=analyze_csv(raw,{},{})
            self.assertFalse(batch.frame['総合評価・コース相性判定'].str.contains('★福島芝1800単勝特注★',regex=False).any())
        else:
            from qt_data_bridge import QtDataBridge
            bridge=QtDataBridge(course_stats={},qualified_jockeys=set(),frame_colors={})
            self.assertFalse(any('★福島芝1800単勝特注★' in r['comment'] for r in bridge.evaluate_frame(raw)))


if __name__=='__main__':unittest.main()
