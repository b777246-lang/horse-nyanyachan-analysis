import re
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from bs4 import BeautifulSoup
from streamlit.testing.v1 import AppTest

from jra_odds import PLACE_CODES


class BulkOddsTests(unittest.TestCase):
    def test_all_races_failure_retention_and_race_scoped_display(self):
        latest = sorted(p for p in Path('.').glob('*.csv')
                        if re.fullmatch(r'\d{8}\.csv', p.name))[-1]
        data = pd.read_csv(latest, encoding='cp932', header=None, dtype=str)
        places = {code: name for name, code in PLACE_CODES.items()}
        targets = {(rid[:8], places[rid[8:10]], int(rid[14:16]))
                   for rid in data.iloc[:, 15]}
        calls = []

        def fetch(date, venue, race):
            calls.append((date, venue, race))
            if (venue, race) == (selected_venue, failed_race):
                raise RuntimeError('simulated failure')
            # 同じ馬番でも開催・レースごとに異なる値で混入を検出する。
            value = int(PLACE_CODES[venue]) * 100 + race
            return ([{'horse_no': n, 'jra_odds': value + n / 100,
                      'popularity': n} for n in range(1, 19)], 'https://example.com/race')

        with patch('jra_odds.fetch_jra_win_odds_auto', side_effect=fetch):
            at = AppTest.from_file(str(Path('app.py').resolve()), default_timeout=60).run()
            selected_venue = at.get('button_group')[0].value
            failed_race = int(at.get('button_group')[1].value)
            date = next(d for d, v, r in targets
                        if (v, r) == (selected_venue, failed_race))
            key = f'{date}_{selected_venue}_{failed_race}'
            previous = [{'horse_no': 1, 'jra_odds': 777.0, 'popularity': 1}]
            at.session_state['jra_odds_cache'][key] = previous
            at.get('button_group')[1].set_value('ALL').run()
            at.button(key='odds_update_all').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(set(calls), targets)
            self.assertEqual(len(calls), len(targets))
            self.assertEqual(at.session_state['jra_odds_cache'][key], previous)
            self.assertTrue(any('simulated failure' in e.value for e in at.error))
            self.assertTrue(at.success)
            count = 0
            for element in at.markdown:
                for row in BeautifulSoup(element.value, 'html.parser').select('tbody tr'):
                    cells = row.find_all('td', recursive=False)
                    race = int(re.search(r'\d+', cells[0].get_text()).group())
                    horse = int(cells[3].get_text())
                    odds = cells[6].get_text()
                    if race == failed_race:
                        self.assertEqual(odds, '777.0' if horse == 1 else '')
                    else:
                        expected = int(PLACE_CODES[selected_venue]) * 100 + race + horse / 100
                        self.assertEqual(float(odds), expected)
                    count += 1
            self.assertGreater(count, 0)
            at.button[0].click().run()
            self.assertFalse(at.exception)
            self.assertEqual(len(calls), len(targets), 'sorting must not fetch again')


if __name__ == '__main__':
    unittest.main()
