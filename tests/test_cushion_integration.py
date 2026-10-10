from datetime import datetime
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from streamlit.testing.v1 import AppTest

from cushion_desktop import CushionStatsPanel
from cushion_snapshot import COLUMNS, create_snapshot
from cushion_stats import get_cushion_stats
from data_loader import normalize_main_frame, read_main_csv
from jra_cushion import extract, select_current_record
from test_cushion_stats import run
from test_jra_cushion import html


class CushionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.csv_patch = patch('data_loader.latest_csv', side_effect=lambda directory='.', comments=False: None if comments else Path('20261010.csv'))
        self.csv_patch.start()
        self.addCleanup(self.csv_patch.stop)

    def test_csv_jra_snapshot_web_desktop_and_failure_no_stale_value(self):
        main = normalize_main_frame(read_main_csv('20261010.csv'))
        entrants = [dict(horse_no=row['horse_no'], horse_name=row['horse_name'], horse_id=row['horse_id'])
                    for _, row in main[main['race'].eq('東2')].iterrows()]
        horse = entrants[0]['horse_id']
        rows = [run(1, horse_registration_number=horse, finish_position=1, win_return_yen=360, place_return_yen=120),
                run(2, horse_registration_number=horse, finish_status='DNF', finish_position=None),
                run(3, horse_registration_number=horse, race_id='2026101005010101', race_date='20261010', finish_position=1, win_return_yen=999)]
        with tempfile.TemporaryDirectory() as folder:
            source, snapshot = Path(folder) / 'source.sqlite', Path(folder) / 'snapshot.sqlite'
            with sqlite3.connect(source) as connection:
                connection.execute('CREATE TABLE race_horses (' + ','.join(COLUMNS[:10]) + ')')
                connection.execute('CREATE TABLE races (' + ','.join(COLUMNS[10:]) + ',race_id)')
                for row in rows:
                    connection.execute('INSERT INTO race_horses VALUES (' + ','.join('?' for _ in COLUMNS[:10]) + ')', tuple(row[k] for k in COLUMNS[:10]))
                for race_id in dict.fromkeys(row['race_id'] for row in rows):
                    row = next(r for r in rows if r['race_id'] == race_id)
                    connection.execute('INSERT INTO races VALUES (' + ','.join('?' for _ in range(10)) + ')', (*[row[k] for k in COLUMNS[10:]], race_id))
            create_snapshot(source, snapshot, [row['horse_id'] for row in entrants], '20261010')
            now = datetime(2026, 10, 10, 9, 30, tzinfo=ZoneInfo('Asia/Tokyo'))
            fetched = select_current_record(extract(html()), '20261010', '東京', now)
            panel = CushionStatsPanel.__new__(CushionStatsPanel)
            panel.heading, panel.detail, panel._draw = MagicMock(), MagicMock(), MagicMock()
            with patch('cushion_desktop.fetch_jra_cushion', return_value=fetched):
                panel.load_jra(snapshot, entrants, '20261010', venue='東京', race_no=2)
            self.assertEqual(panel.records[0]['着別度数'], '1-0-0-1/2')
            self.assertEqual(panel.records[0]['単回収率(%)'], 180)
            at = AppTest.from_file(str(Path('app.py').resolve()), default_timeout=60).run()
            with patch('cushion_viewer.Path.is_file', return_value=True), \
                 patch('cushion_viewer.get_cushion_stats', side_effect=lambda path, *args, **kwargs: get_cushion_stats(snapshot, *args, **kwargs)), \
                 patch('cushion_viewer.cached_jra_cushion', return_value=fetched) as fetch:
                at.get('button_group')[1].set_value(2).run()
                self.assertFalse(at.exception)
                frame = at.dataframe[0].value
                self.assertEqual(len(frame), len(entrants))
                for key, value in panel.records[0].items():
                    self.assertEqual(frame.iloc[0][key], value)
                # Failed refresh cannot keep the formerly published value active.
                fetch.side_effect = ValueError('simulated retrieval failure')
                at.button(key='cushion_refresh').click().run()
                self.assertFalse(at.exception)
                self.assertEqual(at.dataframe[0].value['対象走数'].sum(), 0)
                self.assertTrue(any('取得できません' in message.value for message in at.warning))
                fetch.side_effect = None
                fetch.return_value = select_current_record(extract(html(day=9, weekday='金')), '20261010', '東京', now)
                at.run()
                self.assertEqual(at.dataframe[0].value['対象走数'].sum(), 0)
                self.assertTrue(any('未公表' in message.value for message in at.info))


if __name__ == '__main__':
    unittest.main()
