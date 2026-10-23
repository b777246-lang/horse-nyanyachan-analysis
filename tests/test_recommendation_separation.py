"""旧推奨・特注の独立性と、既存出力への互換合成を検証する。"""
import ast
from dataclasses import replace
import io
from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from analysis import analyze_csv
from config import DEFAULT_SETTINGS
from data_loader import load_comments, load_course_data, read_main_csv
from export import format_target_frame
from formatting import format_analysis_frame, render_html_table
from legacy_recommendations import evaluate_legacy
from odds_service import apply_odds
from recommendation_composition import RecommendationParts, compose_compatible_recommendation
from signals import DEFAULT_REGISTRY, SignalMatch, add_live_comments, fup_matches

ROOT = Path(__file__).resolve().parents[1]


def context(**updates):
    row = dict(race='東1', venue='東京', surface='芝', distance=1600,
               condition='1勝クラス', frame=1, arms=10, arms2=10, TUA=10, S=10, F=10,
               arms_rank=4, arms2_rank=4, TUA_rank=4, S_rank=4, F_rank=4,
               fup=0, fup_rank=4, fup_count=4)
    return dict(row, **updates)


class RecommendationSeparationTests(unittest.TestCase):
    def test_seven_pre_special_rules_accept_boundaries_and_reject_nonmatches(self):
        cases = [
            ('kyoto_1600', dict(venue='京都', arms=100, F=65), [dict(arms=99), dict(F=64), dict(surface='ダ')]),
            ('tokyo_2000', dict(distance=2000, F=70), [dict(F=69), dict(distance=1800)]),
            ('hanshin_1600', dict(venue='阪神', arms_rank=3, F=60, frame=2),
             [dict(arms_rank=4), dict(F=59), dict(frame=1)]),
            ('nakayama_2000', dict(venue='中山', distance=2000, frame=8, F_rank=1),
             [dict(frame=5), dict(F_rank=2)]),
            ('nakayama_1600', dict(venue='中山', frame=4, S_rank=1), [dict(frame=5), dict(S_rank=2)]),
            ('sand', dict(surface='ダ', frame=6, S_rank=1),
             [dict(condition='未勝利'), dict(condition='新馬'), dict(frame=5), dict(S_rank=2)]),
            ('f72', dict(surface='ダ', frame=8, F=72), [dict(F=71), dict(distance=1200), dict(frame=7)]),
        ]
        for key, valid, invalids in cases:
            row = context(**valid)
            with self.subTest(key=key, valid=True):
                self.assertIn(key, [m.key for m in DEFAULT_REGISTRY.evaluate(row)])
            for changes in invalids:
                with self.subTest(key=key, invalid=changes):
                    self.assertNotIn(key, [m.key for m in DEFAULT_REGISTRY.evaluate(dict(row, **changes))])

    def test_tokyo_weight_text_remains_a_manual_check_without_weight_filter(self):
        for weight in (None, 400, 480):
            row = context(distance=2000, F=70)
            if weight is not None:
                row['body_weight'] = weight
            match = next(m for m in DEFAULT_REGISTRY.evaluate(row) if m.key == 'tokyo_2000')
            self.assertEqual(match.comment, '★東京芝2000馬体重480㎏以上特注★')

    def test_multiple_real_specials_add_scores_in_config_order_without_changing_legacy(self):
        row = context(surface='ダ', frame=8, F=72, S_rank=1)
        legacy = evaluate_legacy(row, {})
        specials = DEFAULT_REGISTRY.evaluate(row)
        self.assertEqual([m.key for m in specials], ['sand', 'f72'])
        self.assertEqual(legacy.score, 2)
        self.assertEqual(legacy.highlights, ('F:72(鉄板)',))
        compatible = compose_compatible_recommendation(RecommendationParts(legacy, specials))
        self.assertEqual(compatible.score, 4)
        self.assertEqual(compatible.evaluation,
                         '🔥 【軸馬推奨】 ★特注砂食★ / ★特注F72★ / F:72(鉄板)')
        self.assertEqual(evaluate_legacy(dict(row, frame=1), {}), legacy)
        self.assertEqual(compose_compatible_recommendation(RecommendationParts(legacy, ())).score, 2)

    def test_compatibility_labels_prioritize_triple_then_merged_score_and_attention(self):
        legacy = evaluate_legacy(context(), {})
        for count, label in [(1, '🎯 【注目条件】 '), (2, '⭐ 【有力候補】 '), (4, '🔥 【軸馬推奨】 ')]:
            specials = tuple(SignalMatch(str(i), f'特注{i}', 1) for i in range(count))
            combined = compose_compatible_recommendation(RecommendationParts(legacy, specials))
            self.assertEqual(combined.score, count)
            self.assertEqual(combined.evaluation, label + ' / '.join(f'特注{i}' for i in range(count)))
        triple = replace(legacy, is_triple_1st=True, course_comment='三指数コース')
        result = compose_compatible_recommendation(RecommendationParts(triple, ()))
        self.assertEqual(result.evaluation, '🌟 【★トリプル１位★推奨】 三指数コース')
        silent = compose_compatible_recommendation(RecommendationParts(legacy, (SignalMatch('silent', '', 4),)))
        self.assertEqual((silent.score, silent.evaluation), (4, ''))

    def test_legacy_index_training_boundaries_and_common_ranks_are_inputs(self):
        for field, boundary, points in [('arms', 110, 1), ('arms2', 120, 1), ('TUA', 200, 1),
                                         ('TUA', 220, 2), ('S', 55, 1), ('S', 60, 2),
                                         ('F', 65, 1), ('F', 70, 2)]:
            with self.subTest(field=field, boundary=boundary):
                self.assertEqual(evaluate_legacy(context(**{field: boundary}), {}).score, points)
                self.assertLess(evaluate_legacy(context(**{field: boundary - 1}), {}).score, points)
        self.assertEqual(evaluate_legacy(context(fup=5, fup_count=3), {}).highlights, ('調教良',))
        self.assertEqual(evaluate_legacy(context(fup_rank=3, fup_count=3), {}).highlights, ('調教良',))
        self.assertEqual(evaluate_legacy(context(fup=5, fup_rank=1, fup_count=4), {}).highlights, ())

    def test_course_priority_and_triple_first_match_semantics_remain_unchanged(self):
        row = context(arms_rank=1, arms2_rank=1, TUA_rank=1)
        good = pd.DataFrame([{'コース': '東京 芝1600', '単勝回収値': '100', '複勝率': '10%'}])
        bad = pd.DataFrame([{'コース': '東京 芝1600', '単勝回収値': '99', '複勝率': '59%'}])
        stats = {'triple': good, 'arms指数1位のコース別成績.csv': good}
        triple = evaluate_legacy(row, stats)
        self.assertTrue(triple.is_triple_1st)
        self.assertFalse(triple.is_good_compatibility)
        self.assertEqual(triple.score, 3)
        stats['triple'] = pd.concat([bad, good], ignore_index=True)
        stats['arms2指数1位のコース別成績.csv'] = good
        single = evaluate_legacy(row, stats)
        self.assertFalse(single.is_triple_1st, 'first matching course row must retain precedence')
        self.assertTrue(single.is_good_compatibility)
        self.assertEqual(single.score, 1)
        self.assertIn('arms1位:', single.course_comment)

    def test_batch_keeps_independent_results_without_changing_frame_or_notes_schema(self):
        batch = analyze_csv(read_main_csv('20261018.csv'), load_course_data(), load_comments('20261018comment.csv'))
        self.assertEqual(len(batch.recommendations), 450)
        for _, row in batch.frame.iterrows():
            idx = row['original_index']
            parts = batch.recommendations[idx]
            combined = compose_compatible_recommendation(parts)
            self.assertEqual(row['score'], parts.legacy.score + sum(m.score for m in parts.specials))
            self.assertEqual(batch.notes[idx]['evaluation'], combined.evaluation)
            self.assertEqual(batch.notes[idx]['special_comments'], tuple(m.comment for m in parts.specials if m.comment))
            self.assertEqual(set(batch.notes[idx]), {'evaluation', 'external_comment', 'special_comments', 'ranks'})
        self.assertNotIn('recommendations', batch.frame.columns)
        self.assertNotIn('legacy', batch.frame.columns)
        self.assertNotIn('specials', batch.frame.columns)

    def test_live_fup_is_added_removed_and_readded_from_fresh_base_without_score_changes(self):
        batch = analyze_csv(read_main_csv('20261018.csv'), load_course_data(), {})
        eligible = batch.frame.apply(lambda row: fup_matches(dict(row, 人気=1)), axis=1)
        self.assertTrue(eligible.any())
        original = batch.frame.loc[[eligible[eligible].index[0]]].copy()
        horse = original.iloc[0]
        base = format_target_frame(original)
        for popularity in (1, 3, 2, 5):
            odds = {(horse['venue'], int(horse['race_no'])): {
                str(int(horse['馬番'])): dict(jra_odds=10, popularity=popularity)}}
            live = add_live_comments(apply_odds(base, odds))
            display = format_analysis_frame(live, batch.notes)
            expected = popularity in (1, 2)
            self.assertEqual(live.iloc[0]['総合評価・コース相性判定'].count('★F-UP特注★'), int(expected))
            self.assertEqual(display.iloc[0]['総合評価・コース相性判定'].count('★F-UP特注★'), int(expected))
            self.assertEqual('<span style="color: #ff4b4b; font-weight: bold;">★F-UP特注★</span>'
                             in display.iloc[0]['総合評価・コース相性判定'], expected)
            pd.testing.assert_frame_equal(add_live_comments(live), live)
            self.assertEqual(live.iloc[0]['score'], horse['score'])
        pd.testing.assert_frame_equal(base, format_target_frame(original))

    def test_special_and_shared_modules_do_not_depend_on_legacy_engine(self):
        for filename in ('signals.py', 'values.py', 'data_loader.py', 'odds_service.py', 'config.py'):
            tree = ast.parse((ROOT / filename).read_text())
            imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            imports += [item.name for node in ast.walk(tree) if isinstance(node, ast.Import) for item in node.names]
            self.assertNotIn('legacy_recommendations', imports, filename)
        tree = ast.parse((ROOT / 'legacy_recommendations.py').read_text())
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertNotIn('signals', imports)
        self.assertNotIn('analysis', imports)
        self.assertNotIn('recommendation_composition', imports)

    def test_streamlit_sort_and_reset_keep_screen_and_all_horse_csv_consistent(self):
        downloads = {}
        def capture(**kwargs):
            downloads[kwargs['file_name']] = kwargs['data']
            return False
        with patch('data_loader.latest_csv', side_effect=lambda directory='.', comments=False: ROOT / ('20261018comment.csv' if comments else '20261018.csv')), patch('streamlit.download_button', side_effect=capture), patch(
                'cushion_viewer.cached_jra_cushion', return_value=dict(value=None, message='テスト')):
            at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=60).run()
            self.assertFalse(at.exception)
            initial = downloads['horse_analysis_result.csv']
            at.get('button_group')[1].set_value('ALL').run()
            next(button for button in at.button if button.label == '🔥 評価点数順にソート').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state['sort_mode'], 'スコア順')
            batch = analyze_csv(read_main_csv('20261018.csv'), load_course_data(), load_comments('20261018comment.csv'))
            ordered = batch.frame.sort_values(['score', 'original_index'], ascending=[False, True]).reset_index(drop=True)
            csv = pd.read_csv(io.StringIO(downloads['horse_analysis_result.csv']), dtype=str)
            self.assertEqual(csv['レースID'].tolist(), ordered['レースID'].tolist())
            display = format_analysis_frame(ordered, batch.notes)
            expected = render_html_table(display[display['venue'].eq(at.get('button_group')[0].value)])
            self.assertIn(expected, [element.value for element in at.markdown])
            next(button for button in at.button if button.label == '🔄 初期配列に戻す').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(downloads['horse_analysis_result.csv'], initial)


if __name__ == '__main__':
    unittest.main()
