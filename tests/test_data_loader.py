import tempfile
import unittest
from pathlib import Path

import pandas as pd

from data_loader import latest_csv, normalize_main_frame


class DataLoaderTests(unittest.TestCase):
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
