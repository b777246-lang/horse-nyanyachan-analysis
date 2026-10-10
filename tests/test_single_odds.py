import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class SingleOddsTests(unittest.TestCase):
    def test_single_update_changes_only_selected_race_and_preserves_cache_on_failure(self):
        rows = [{'horse_no': 1, 'jra_odds': 12.3, 'popularity': 5}]
        with patch('jra_odds.fetch_jra_win_odds_auto', return_value=(rows, 'https://example.com/race')) as fetch:
            at = AppTest.from_file(str(Path('app.py').resolve()), default_timeout=60).run()
            venue = at.get('button_group')[0].value
            race = int(at.get('button_group')[1].value)
            other_key = '20260101_別レース_12'
            previous = [{'horse_no': 1, 'jra_odds': 99.0, 'popularity': 1}]
            at.session_state['jra_odds_cache'][other_key] = previous
            at.button(key='odds_update_current').click().run()
            self.assertFalse(at.exception)
            self.assertFalse(at.error)
            fetch.assert_called_once()
            date, requested_venue, requested_race = fetch.call_args.args
            self.assertEqual((requested_venue, requested_race), (venue, race))
            key = f'{date}_{venue}_{race}'
            self.assertEqual(at.session_state['jra_odds_cache'][key], rows)
            self.assertEqual(at.session_state['jra_odds_cache'][other_key], previous)
            fetch.side_effect = RuntimeError('simulated single failure')
            at.button(key='odds_update_current').click().run()
            self.assertFalse(at.exception)
            self.assertTrue(at.error)
            self.assertEqual(at.session_state['jra_odds_cache'][key], rows)
            self.assertEqual(at.session_state['jra_odds_cache'][other_key], previous)
            at.get('button_group')[1].set_value('ALL').run()
            self.assertFalse(at.exception)
            self.assertNotIn('odds_update_current', [button.key for button in at.button])
            self.assertIn('odds_update_all', [button.key for button in at.button])


if __name__ == '__main__':
    unittest.main()
