import csv
from contextlib import closing
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest

import pandas as pd

from analysis import analyze_csv
from csv22_compat import csv21_bytes
from data_loader import normalize_main_frame
from formatting import render_html_table
from s2_service import update_s2_audit
from tua190_service import update_tua190_audit
from tua190_history_snapshot import create_snapshot


def row(level=None):
    values = ['東1', '未勝利', '芝', '1600', '1', '1', '', '馬',
              '10', '20', '30', '40', '50', '6', '10',
              '202611140501010101', '2024000001', '騎手', '3', '父', '']
    if level is not None:
        values.append(level)
    return values


def raw(level='普通'):
    stream = io.StringIO(newline='')
    csv.writer(stream, lineterminator='\r\n').writerow(row(level))
    return stream.getvalue().encode('cp932')


class RaceLevelTests(unittest.TestCase):
    def test_csv21_and_csv22_are_compatible_and_s2_stays_fixed21(self):
        self.assertEqual(normalize_main_frame(pd.DataFrame([row()])).iloc[0]['race_level'], '')
        self.assertEqual(normalize_main_frame(pd.DataFrame([row('高ー')])).iloc[0]['race_level'], '高－')
        projected = list(csv.reader(io.StringIO(csv21_bytes(raw()).decode('cp932'))))
        self.assertEqual(projected[0], row())
        self.assertEqual(update_s2_audit(raw(), {})['status'], 'EVALUATED')

    def test_invalid_or_conflicting_current_level_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_main_frame(pd.DataFrame([row('最強')]))
        second = row('低＋')
        second[5] = '2'; second[15] = '202611140501010102'
        with self.assertRaises(ValueError):
            normalize_main_frame(pd.DataFrame([row('高＋'), second]))

    def test_analysis_and_html_show_current_and_previous_level(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            db_path = Path(folder) / 'history.sqlite'
            with closing(sqlite3.connect(db_path)) as db:
                db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)')
                db.execute("INSERT INTO metadata VALUES('source_latest_prior_date','20261107')")
                db.execute('''CREATE TABLE history(
                    horse_registration_number TEXT,target_id TEXT PRIMARY KEY,race_id TEXT,
                    race_date TEXT,surface TEXT,finish_position INTEGER,popularity INTEGER,
                    finish_status TEXT,jockey TEXT,r_level TEXT,r_level_status TEXT)''')
                db.execute("INSERT INTO history VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                    '2024000001', 'old01', 'old', '20261107', '芝', 3, 4,
                    'FINISHED', '騎手', '高＋', 'AVAILABLE'))
                db.commit()
            frame = analyze_csv(pd.DataFrame([row('普通')]), {}, {}, history_db_path=db_path).frame
            self.assertEqual(frame.iloc[0]['今走Rレベル'], '普通')
            self.assertEqual(frame.iloc[0]['前走Rレベル'], '高＋')
            html = render_html_table(frame)
            self.assertIn('<th>前走Rレベル</th>', html)
            self.assertIn('<td>高＋</td>', html)

    def test_mobile_screen_table_omits_repeated_race_and_condition_only(self):
        frame = analyze_csv(pd.DataFrame([row('普通')]), {}, {}).frame
        compact = render_html_table(frame, show_race_columns=False)
        full = render_html_table(frame)
        self.assertIn('class="custom-horse-table compact-horse-table"', compact)
        self.assertNotIn('<th>レース</th>', compact)
        self.assertNotIn('<th>条件</th>', compact)
        self.assertIn('<th>前走Rレベル</th>', compact)
        self.assertIn('<th>レース</th>', full)
        self.assertIn('<th>条件</th>', full)

    def test_new_tua_snapshot_carries_r_level_without_separate_db(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder); source = root/'source.db'; source_csv = root/'input.csv'; output = root/'history.sqlite'
            with closing(sqlite3.connect(source)) as db:
                db.execute('CREATE TABLE races(race_id TEXT PRIMARY KEY,race_date TEXT,surface TEXT,r_level TEXT,r_level_status TEXT)')
                db.execute('CREATE TABLE race_horses(horse_registration_number TEXT,target_id TEXT PRIMARY KEY,race_id TEXT,finish_position INTEGER,popularity INTEGER,finish_status TEXT,jockey TEXT)')
                db.execute("INSERT INTO races VALUES('old','20261107','芝','低★','AVAILABLE')")
                db.execute("INSERT INTO race_horses VALUES('2024000001','old01','old',3,4,'FINISHED','騎手')")
                db.commit()
            source_csv.write_bytes(raw())
            create_snapshot(source, source_csv, output)
            with closing(sqlite3.connect(output)) as db:
                self.assertEqual(db.execute('SELECT r_level,r_level_status FROM history').fetchone(), ('低★', 'AVAILABLE'))
            record = update_tua190_audit(source_csv.read_bytes(), {}, snapshot_path=output)
            self.assertEqual(record['status'], 'EVALUATED')
            self.assertEqual(record['history_path'], str(output.resolve()))
            self.assertIsNone(record['error'])


if __name__ == '__main__':
    unittest.main()
