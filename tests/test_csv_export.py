import io
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from jra_odds import PLACE_CODES


class CsvExportTests(unittest.TestCase):
    def test_fup_comment_is_plain_in_csv_and_colored_in_html(self):
        latest = sorted(p for p in Path('.').glob('*.csv')
                        if re.fullmatch(r'\d{8}\.csv', p.name))[-1]
        data = pd.read_csv(latest, encoding='cp932', header=None, dtype=str)
        places = {code: name for name, code in PLACE_CODES.items()}
        cache = {}
        for rid in data.iloc[:, 15]:
            key = f'{rid[:8]}_{places[rid[8:10]]}_{int(rid[14:16])}'
            cache[key] = [{'horse_no': n, 'jra_odds': 10.0, 'popularity': 1}
                          for n in range(1, 19)]
        downloads = {}

        def capture(**kwargs):
            downloads[kwargs['file_name']] = kwargs['data']
            return False

        with patch('streamlit.download_button', side_effect=capture):
            at = AppTest.from_file(str(Path('app.py').resolve()), default_timeout=60).run()
            at.session_state['jra_odds_cache'] = cache
            at.run()
            self.assertFalse(at.exception)
        csv = pd.read_csv(io.StringIO(downloads['horse_analysis_result.csv']))
        comments = csv['総合評価・コース相性判定'].fillna('')
        marked = comments[comments.str.contains('★F-UP特注★', regex=False)]
        self.assertGreater(len(marked), 0)
        self.assertFalse(comments.str.contains(r'<[^>]+>', regex=True).any())
        self.assertTrue(marked.str.startswith('★F-UP特注★').all())
        self.assertIn(
            '<span style="color: #ff4b4b; font-weight: bold;">★F-UP特注★</span>',
            downloads['horse_analysis_result.html'],
        )


if __name__ == '__main__':
    unittest.main()
