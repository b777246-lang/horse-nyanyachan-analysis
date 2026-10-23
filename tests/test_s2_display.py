from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from analysis import analyze_csv
from data_loader import read_main_csv, load_comments, load_course_data
from export import build_target_csv, format_target_frame, build_html_report
from formatting import format_analysis_frame
from s2_service import update_s2_audit
from s2_presentation import add_s2_screen_comments
from tua190_service import update_tua190_audit
from tua190_presentation import add_tua190_screen_comments, LABEL

ROOT = Path(__file__).resolve().parents[1]


class S2DisplayTests(unittest.TestCase):
    def setUp(self):
        raw = (ROOT / '20261024.csv').read_bytes()
        self.record = update_s2_audit(raw, {})
        self.tua = update_tua190_audit(raw, {})
        self.batch = analyze_csv(read_main_csv('20261024.csv'), load_course_data(), load_comments('20261024comment.csv'))
        self.base = format_analysis_frame(self.batch.frame, self.batch.notes)

    def test_all_real_matches_have_exact_numbers_in_purple_and_keep_original_data(self):
        expected = {}
        for item in self.record['report']['condition_audit']:
            if item['state'] == 'MATCH':
                expected.setdefault(item['entry_id'], []).append(item['condition_number'])
        self.assertEqual(len(expected), 63)
        self.assertEqual(sum(map(len, expected.values())), 75)
        original = self.base.copy(deep=True)
        tua = add_tua190_screen_comments(self.base, self.tua)
        screen = add_s2_screen_comments(tua, self.record)
        for idx, row in screen.iterrows():
            text = row['総合評価・コース相性判定']
            numbers = expected.get(row['レースID'], [])
            if numbers:
                label = '【' + ' / '.join(f'No.{n}' for n in numbers) + '】'
                self.assertIn(f'<span style="color: #7c3aed; font-weight: bold;">{label}</span>', text)
            else:
                self.assertEqual(text, tua.at[idx, '総合評価・コース相性判定'])
            self.assertTrue(text.endswith(tua.at[idx, '総合評価・コース相性判定']))
        pd.testing.assert_frame_equal(self.base, original)
        pd.testing.assert_frame_equal(screen.drop(columns='総合評価・コース相性判定'), original.drop(columns='総合評価・コース相性判定'))
        pd.testing.assert_frame_equal(add_s2_screen_comments(screen, self.record), screen)
        self.assertEqual(screen['総合評価・コース相性判定'].str.contains(LABEL, regex=False).sum(), 13)

    def test_nonmatch_invalid_unknown_number_and_false_flags_do_not_display(self):
        valid = next(x for x in self.record['report']['condition_audit'] if x['state'] == 'MATCH')
        for changes in ({'state': 'NO_MATCH'}, {'state': 'UNCONFIRMED'}, {'state': 'INVALID_INPUT'}, {'state': 'OUT_OF_SCOPE'}, {'and_passed': False}, {'condition_number': 999}, {'race_id': 'wrong'}):
            record = deepcopy(self.record)
            record['report']['condition_audit'] = [dict(valid, **changes)]
            pd.testing.assert_frame_equal(add_s2_screen_comments(self.base, record), self.base)
        for field in ('prospective_ready', 'prospective_verified'):
            record = deepcopy(self.record); record['report'][field] = True
            pd.testing.assert_frame_equal(add_s2_screen_comments(self.base, record), self.base)
        pd.testing.assert_frame_equal(add_s2_screen_comments(self.base, None), self.base)

    def test_web_numbers_survive_odds_and_sort_without_changing_downloads(self):
        downloads = {}
        def capture(**kwargs):
            downloads[kwargs['file_name']] = kwargs['data']; return False
        target = next(x for x in self.record['report']['condition_audit'] if x['state'] == 'MATCH')
        horse = self.batch.frame[self.batch.frame['レースID'].eq(target['entry_id'])].iloc[0]
        with patch('data_loader.latest_csv', side_effect=lambda directory='.', comments=False: ROOT / ('20261024comment.csv' if comments else '20261024.csv')), patch('streamlit.download_button', side_effect=capture), patch('cushion_viewer.cached_jra_cushion', return_value={'value': None, 'message': 'テスト'}):
            at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=60).run()
            at.get('button_group')[0].set_value(horse['venue']).run()
            at.get('button_group')[1].set_value(int(horse['race_no'])).run()
            self.assertFalse(at.exception)
            self.assertTrue(any(f'No.{target["condition_number"]}' in x.value for x in at.markdown))
            self.assertEqual(downloads['horse_analysis_result.csv'], build_target_csv(format_target_frame(self.batch.frame)))
            self.assertEqual(downloads['horse_analysis_result.html'], build_html_report(self.base))
            next(b for b in at.button if b.label == '🔥 評価点数順にソート').click().run()
            self.assertFalse(at.exception)
            self.assertTrue(any(f'No.{target["condition_number"]}' in x.value for x in at.markdown))
            at.session_state['jra_odds_cache'] = {f'20261024_{horse["venue"]}_{int(horse["race_no"])}': [{'horse_no': int(horse['馬番']), 'jra_odds': 21.3, 'popularity': 1}]}
            at.run()
            self.assertFalse(at.exception)
            self.assertTrue(any(f'No.{target["condition_number"]}' in x.value for x in at.markdown))
            self.assertTrue(all('【No.' not in content for content in downloads.values()))


if __name__ == '__main__':
    unittest.main()
