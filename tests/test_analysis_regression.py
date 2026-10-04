"""整理前のapp.pyが生成した出力と、2日分全711頭の結果を照合する。"""
import hashlib
import json
import unittest
from pathlib import Path

from analysis import analyze_csv
from data_loader import load_comments, load_course_data, read_main_csv
from export import build_html_report, build_target_csv, format_target_frame
from formatting import format_analysis_frame
from jra_odds import PLACE_CODES
from odds_service import apply_odds, build_race_targets, cached_odds_by_race
from signals import add_live_comments, filter_kol_horses


class AnalysisRegressionTests(unittest.TestCase):
    def test_all_horses_comments_scores_and_exports_match_before_refactor(self):
        fixture = Path(__file__).parent / 'fixtures' / 'refactor'
        expected = json.loads((fixture / 'expected_outputs.json').read_text())
        expected_analysis = json.loads((fixture / 'expected_analysis.json').read_text())
        stats = load_course_data()
        total = 0
        for date in ('20261003', '20261004'):
            data = read_main_csv(fixture / f'{date}.csv')
            comments = load_comments(fixture / f'{date}comment.csv')
            batch = analyze_csv(data, stats, comments)
            total += len(batch.frame)
            self.assertEqual(batch.frame['score'].astype(int).tolist(), expected_analysis[date]['scores'])
            for current, previous in (
                ('arms', 'arms_rank'), ('arms2', 'arms2_rank'), ('TUA', 'tua_rank'),
                ('S', 'S_rank'), ('F', 'F_rank'), ('厩舎F-UP2', 'finish_up_rank'),
            ):
                self.assertEqual([note['ranks'][current] for note in batch.notes.values()],
                                 expected_analysis[date]['ranks'][previous])
            # 判定層の出力にはHTMLを混入させない。
            self.assertFalse(batch.frame['総合評価・コース相性判定'].str.contains('<span', regex=False).any())
            cache = {}
            venues = {value: key for key, value in PLACE_CODES.items()}
            for index, row in data.iterrows():
                rid = row[15]
                key = f'{rid[:8]}_{venues[rid[8:10]]}_{int(rid[14:16])}'
                cache.setdefault(key, []).append({
                    'horse_no': int(rid[-2:]),
                    'jra_odds': float(row[14]) * (2.5 if index % 2 else 3),
                    'popularity': 1 if index % 3 == 0 else 5,
                })
            for stage in ('initial', 'odds', 'sort'):
                with self.subTest(date=date, stage=stage):
                    raw = format_target_frame(batch.frame)
                    display = format_analysis_frame(batch.frame, batch.notes)
                    if stage == 'sort':
                        raw = raw.sort_values(['score', 'original_index'], ascending=[False, True]).reset_index(drop=True)
                        display = display.sort_values(['score', 'original_index'], ascending=[False, True]).reset_index(drop=True)
                    if stage != 'initial':
                        targets = build_race_targets(display, date)
                        raw = add_live_comments(apply_odds(raw, cached_odds_by_race(targets, cache)))
                        display = format_analysis_frame(raw, batch.notes)
                    outputs = {
                        'horse_analysis_result.csv': build_target_csv(raw),
                        'horse_analysis_result.html': build_html_report(display),
                        'horse_analysis_kol_matches.html': build_html_report(
                            filter_kol_horses(display), 'KOL判定該当馬レポート'),
                    }
                    for name, text in outputs.items():
                        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(),
                                         expected[f'{date}-{stage}'][name], name)
        self.assertEqual(total, 711)


if __name__ == '__main__':
    unittest.main()
