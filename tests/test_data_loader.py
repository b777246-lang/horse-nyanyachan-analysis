import tempfile
import unittest
from pathlib import Path

import pandas as pd

from data_loader import latest_csv, normalize_main_frame, read_main_csv
import io


class DataLoaderTests(unittest.TestCase):
    def test_new_csv_preserves_registration_number_and_reads_jockey(self):
        text = ','.join([''] * 15 + ['202610100504030101', '0024102281', '戸崎圭太'])
        frame = normalize_main_frame(read_main_csv(io.StringIO(text)))
        self.assertEqual(frame.at[0, 'horse_id'], '0024102281')
        self.assertEqual(frame.at[0, 'jockey'], '戸崎圭太')
        pd.testing.assert_frame_equal(normalize_main_frame(frame), frame)

    def test_legacy_jockey_and_missing_new_jockey_are_distinguished(self):
        legacy = pd.DataFrame([[''] * 16 + ['ルメール']])
        self.assertEqual(normalize_main_frame(legacy).at[0, 'jockey'], 'ルメール')
        incomplete = pd.DataFrame([[''] * 16 + ['2024102281']])
        normalized = normalize_main_frame(incomplete)
        self.assertEqual(normalized.at[0, 'horse_id'], '2024102281')
        self.assertEqual(normalized.at[0, 'jockey'], '')
        mixed = pd.DataFrame([[''] * 16 + ['2024102281'], [''] * 16 + ['ルメール']])
        with self.assertRaisesRegex(ValueError, '混在'):
            normalize_main_frame(mixed)

    def test_latest_csv_uses_eight_digit_dates_and_separates_comments(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for name in ('20261003.csv', '20261004.csv', '202601005.csv',
                         '20261004comment.csv', 'F指数1位のコース別成績.csv'):
                (folder / name).touch()
            self.assertEqual(latest_csv(folder).name, '20261004.csv')
            self.assertEqual(latest_csv(folder, comments=True).name, '20261004comment.csv')

    def test_normalization_preserves_extra_columns_and_supports_old_csv(self):
        frame = pd.DataFrame([[''] * 20])
        frame[19] = 'future input'
        normalized = normalize_main_frame(frame)
        self.assertIn('horse_name', normalized.columns)
        self.assertEqual(normalized.at[0, 19], 'future input')
        pd.testing.assert_frame_equal(normalize_main_frame(normalized), normalized)
        old = normalize_main_frame(frame.iloc[:, :14])
        self.assertEqual(old.at[0, 'jockey'], '')
        self.assertEqual(old.at[0, 'race_id'], '')
        with self.assertRaisesRegex(ValueError, '必須列'):
            normalize_main_frame(frame.iloc[:, :13])


if __name__ == '__main__':
    unittest.main()
