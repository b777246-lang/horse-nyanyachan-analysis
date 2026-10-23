import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from analysis import analyze_csv
from data_loader import read_main_csv, load_comments, load_course_data
from formatting import format_analysis_frame
from export import build_target_csv, format_target_frame, build_html_report
from tua190_service import update_tua190_audit
from tua190_presentation import LABEL, add_tua190_screen_comments

ROOT = Path(__file__).resolve().parents[1]


class Tua190DisplayTests(unittest.TestCase):
    def setUp(self):
        self.raw = (ROOT / '20261024.csv').read_bytes()
        self.record = update_tua190_audit(self.raw, {})
        self.assertEqual(self.record['status'], 'EVALUATED')
        self.batch = analyze_csv(read_main_csv('20261024.csv'), load_course_data(), load_comments('20261024comment.csv'))
        self.base = format_analysis_frame(self.batch.frame, self.batch.notes)

    def test_real_snapshot_marks_exactly_thirteen_entries_without_modifying_sources(self):
        self.assertEqual(self.record['report']['summary']['MATCH'], 13)
        expected = {r['entry_id'] for r in self.record['report']['audit'] if r['state'] == 'MATCH'}
        before = self.base.copy(deep=True)
        screen = add_tua190_screen_comments(self.base, self.record)
        marked = screen['総合評価・コース相性判定'].str.contains(LABEL, regex=False)
        self.assertEqual(set(screen.loc[marked, 'レースID']), expected)
        pd.testing.assert_frame_equal(self.base, before)
        pd.testing.assert_frame_equal(screen.drop(columns='総合評価・コース相性判定'), before.drop(columns='総合評価・コース相性判定'))
        pd.testing.assert_frame_equal(screen, add_tua190_screen_comments(screen, self.record))
        for idx in screen.index[marked]:
            self.assertTrue(screen.at[idx, '総合評価・コース相性判定'].endswith(before.at[idx, '総合評価・コース相性判定']))

    def test_missing_unconfirmed_or_nonresearch_report_does_not_add_label(self):
        for record in (None, {'status': 'UNCONFIRMED'}, {'status': 'EVALUATED', 'report': {'status': 'EVALUATED', 'research_only': True, 'prospective_ready': True, 'prospective_verified': False}}):
            pd.testing.assert_frame_equal(add_tua190_screen_comments(self.base, record), self.base)

    def test_app_displays_research_label_but_keeps_all_downloads_unchanged_after_sort(self):
        downloads = {}
        def capture(**kwargs):
            downloads[kwargs['file_name']] = kwargs['data']
            return False
        target = next(r for r in self.record['report']['audit'] if r['state'] == 'MATCH')
        with patch('data_loader.latest_csv', side_effect=lambda directory='.', comments=False: ROOT / ('20261024comment.csv' if comments else '20261024.csv')), patch('streamlit.download_button', side_effect=capture), patch('cushion_viewer.cached_jra_cushion', return_value={'value': None, 'message': 'テスト'}):
            at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=60).run()
            at.get('button_group')[0].set_value(target['venue']).run()
            at.get('button_group')[1].set_value(target['race_no']).run()
            self.assertFalse(at.exception)
            self.assertTrue(any(LABEL in x.value for x in at.markdown))
            self.assertEqual(downloads['horse_analysis_result.csv'], build_target_csv(format_target_frame(self.batch.frame)))
            self.assertEqual(downloads['horse_analysis_result.html'], build_html_report(self.base))
            self.assertFalse(any(LABEL in content for content in downloads.values()))
            next(b for b in at.button if b.label == '🔥 評価点数順にソート').click().run()
            self.assertFalse(at.exception)
            self.assertTrue(any(LABEL in x.value for x in at.markdown))
            self.assertFalse(any(LABEL in content for content in downloads.values()))


if __name__ == '__main__':
    unittest.main()
