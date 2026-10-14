import io
import unittest
from unittest.mock import MagicMock

import pandas as pd

from analysis import analyze_csv
from data_loader import read_main_csv, normalize_main_frame, load_course_data
from export import build_target_csv, build_html_report
from formatting import format_analysis_frame
from horse_app import HorseApp


class AgeInputTests(unittest.TestCase):
    def test_nineteenth_column_preserves_identity_and_age(self):
        text = ','.join([''] * 15 + ['202610100504030101', '0024102281', '戸崎圭太', '3'])
        result = normalize_main_frame(read_main_csv(io.StringIO(text)))
        self.assertEqual(result.at[0, 'age'], '3')
        self.assertEqual(result.at[0, 'horse_id'], '0024102281')
        self.assertEqual(result.at[0, 'jockey'], '戸崎圭太')
        pd.testing.assert_frame_equal(normalize_main_frame(result), result)
        self.assertEqual(normalize_main_frame(pd.DataFrame([[''] * 19])).at[0, 'age'], '')
        self.assertFalse(normalize_main_frame(pd.DataFrame([[''] * 18])).attrs['has_age'])

    def test_web_age_is_retained_but_not_displayed_or_exported(self):
        original = read_main_csv('20261010.csv').iloc[:, :18]
        added = original.copy()
        added[18] = '3'
        before = analyze_csv(original, load_course_data(), {})
        after = analyze_csv(added, load_course_data(), {})
        self.assertTrue(after.frame['age'].eq('3').all())
        pd.testing.assert_frame_equal(before.frame, after.frame.drop(columns='age'))
        self.assertEqual(build_target_csv(before.frame), build_target_csv(after.frame))
        self.assertEqual(build_html_report(format_analysis_frame(before.frame, before.notes)),
                         build_html_report(format_analysis_frame(after.frame, after.notes)))

    def test_desktop_age_does_not_change_analysis_or_jockey(self):
        original = read_main_csv('20261010.csv').iloc[:, :18]
        added = original.copy()
        added[18] = '3'
        outputs = []
        for data in (original, added):
            app = HorseApp.__new__(HorseApp)
            app.ext_comment_df = None
            app.set_display_data = MagicMock()
            app.load_course_data()
            app.process_and_display_data(data.copy())
            outputs.append(app.export_data_list)
        self.assertTrue(all(row['age'] == '3' for row in outputs[1]))
        self.assertEqual(outputs[0], [{key: value for key, value in row.items() if key != 'age'} for row in outputs[1]])


if __name__ == '__main__':
    unittest.main()
