import io
import unittest

import pandas as pd

from analysis import analyze_csv
from config import DEFAULT_SETTINGS
from signals import DEFAULT_REGISTRY
from training_context import (load_training_courses, normalize_trainer,
                              normalize_training_course)


def keys(context):
    return {match.key for match in DEFAULT_REGISTRY.evaluate(context, DEFAULT_SETTINGS)}


def main_frame(trainer="中村直也", f_value=65):
    rows=[]
    for n,value in enumerate((f_value,50,40,30),1):
        rows.append([
            '京1','1勝クラス','芝','1600','1',str(n),'',f'人工馬{n}',
            '80','90','100','50',str(value),'2','10',
            f'2026112108050501{n:02d}',f'202400{n:04d}','騎手','3','人工父','','普通',trainer,
        ])
    return pd.DataFrame(rows)


class TrainerWorkoutSpecialTests(unittest.TestCase):
    def test_all_five_rules_and_boundaries(self):
        cases=(
            ('nakamura_hill_f',dict(trainer='中村直也',training_course='坂路',F=65),'F',65),
            ('shimizu_wood_arms',dict(trainer='清水久詞',training_course='ウッド',arms=100),'arms',100),
            ('kanari_wood_arms2',dict(trainer='金成貴史',training_course='ウッド',arms2=110,arms2_rank=3),'arms2',110),
            ('ohashi_wood_tua',dict(trainer='大橋勇樹',training_course='ウッド',TUA=180,TUA_rank=3),'TUA',180),
            ('owada_hill_arms',dict(trainer='大和田成',training_course='坂路',arms=90),'arms',90),
        )
        for key,base,field,threshold in cases:
            self.assertIn(key,keys(base))
            self.assertNotIn(key,keys(dict(base,**{field:threshold-.01})))
            other='ウッド' if base['training_course']=='坂路' else '坂路'
            self.assertNotIn(key,keys(dict(base,training_course=other)))
            self.assertNotIn(key,keys(dict(base,trainer='別厩舎')))
        for key,base,rank_field in (
                ('kanari_wood_arms2',cases[2][1],'arms2_rank'),
                ('ohashi_wood_tua',cases[3][1],'TUA_rank')):
            for rank,expected in ((1,True),(3,True),(4,False)):
                self.assertEqual(key in keys(dict(base,**{rank_field:rank})),expected)

    def test_course_and_trainer_normalization(self):
        self.assertEqual(normalize_trainer('(栗) 中村 直也'),'中村直也')
        for raw,expected in (('栗東坂','坂路'),('美南坂','坂路'),
                             ('栗東CW','ウッド'),('美南Ｗ','ウッド'),('函館Ｗ','ウッド'),
                             ('栗東芝','')):
            self.assertEqual(normalize_training_course(raw),expected)
        raw=('レースID+馬番,馬名,調教コース\n'
             '202611210805050101,人工馬1,栗東坂\n').encode('utf-8-sig')
        self.assertEqual(load_training_courses(io.BytesIO(raw)),
                         {'202611210805050101':'坂路'})

    def test_web_pipeline_uses_column23_and_workout_mapping(self):
        frame=main_frame()
        entry_id=frame.iloc[0,15]
        result=analyze_csv(frame,{}, {},training_courses={entry_id:'坂路'})
        self.assertIn('★中村厩舎特注条件★',result.frame.iloc[0]['総合評価・コース相性判定'])
        self.assertNotIn('★中村厩舎特注条件★',result.frame.iloc[1]['総合評価・コース相性判定'])

    def test_legacy_22_columns_stay_compatible_and_cannot_guess_trainer(self):
        frame=main_frame().iloc[:,:22]
        result=analyze_csv(frame,{}, {},training_courses={frame.iloc[0,15]:'坂路'})
        self.assertNotIn('★中村厩舎特注条件★',result.frame.iloc[0]['総合評価・コース相性判定'])


if __name__=='__main__':
    unittest.main()
