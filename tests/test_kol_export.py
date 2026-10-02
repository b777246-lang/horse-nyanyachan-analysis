import io
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from bs4 import BeautifulSoup
from streamlit.testing.v1 import AppTest

from jra_odds import PLACE_CODES


class KolExportTests(unittest.TestCase):
    def test_filtered_html_matches_highlighted_horses_and_preserves_full_exports(self):
        latest = sorted(p for p in Path('.').glob('*.csv')
                        if re.fullmatch(r'\d{8}\.csv', p.name))[-1]
        data = pd.read_csv(latest, encoding='cp932', header=None, dtype=str)
        places = {code: name for name, code in PLACE_CODES.items()}
        cache = {}
        for index, row in data.iterrows():
            rid = row[15]
            key = f'{rid[:8]}_{places[rid[8:10]]}_{int(rid[14:16])}'
            # 下限、上限、および範囲外を混ぜる。
            multiplier = (2.5, 5.5, 2.4, 5.6)[index % 4]
            cache.setdefault(key, []).append({
                'horse_no': int(rid[-2:]), 'jra_odds': float(row[14]) * multiplier,
                'popularity': 5,
            })
        downloads = {}

        def capture(**kwargs):
            downloads[kwargs['file_name']] = kwargs
            return False

        with patch('streamlit.download_button', side_effect=capture):
            at = AppTest.from_file(str(Path('app.py').resolve()), default_timeout=60).run()
            self.assertFalse(at.exception)
            self.assertTrue(downloads['horse_analysis_kol_matches.html']['disabled'])
            at.session_state['jra_odds_cache'] = cache
            at.run()
            self.assertFalse(at.exception)
            self.assertFalse(downloads['horse_analysis_kol_matches.html']['disabled'])

        full = BeautifulSoup(downloads['horse_analysis_result.html']['data'], 'html.parser')
        filtered = BeautifulSoup(downloads['horse_analysis_kol_matches.html']['data'], 'html.parser')
        all_rows = full.select('tbody tr')
        expected = [str(row) for row in all_rows if row.select_one('.odds-gap-alert')]
        actual = [str(row) for row in filtered.select('tbody tr')]
        self.assertGreater(len(expected), 0)
        self.assertLess(len(expected), len(all_rows))
        self.assertEqual(actual, expected)
        self.assertEqual(len(all_rows), len(data))
        self.assertEqual(len(pd.read_csv(io.StringIO(downloads['horse_analysis_result.csv']['data']))),
                         len(data))
        self.assertIn('KOL判定該当馬レポート', filtered.title.get_text())


if __name__ == '__main__':
    unittest.main()
