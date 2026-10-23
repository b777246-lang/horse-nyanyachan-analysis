import csv
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import hashlib
from tua190_service import update_tua190_audit, STATE_KEY
from s2_service import update_s2_audit, STATE_KEY as S2_KEY
from s2_shared.storage import encode
from tua190_dirt import evaluate_csv_bytes
from tua190_history_snapshot import create_snapshot


def csv21(day='20261024'):
    rows = []
    for number, (tua, s, age) in enumerate(((200, 80, 3), (195, 70, 3),
                                            (190, 60, 3), (180, 50, 3)), 1):
        rows.append(['東1', '条件', 'ダ', '1400', '1', str(number), '', f'馬{number}',
                     '1', '2', str(tua), str(s), '40', '3', '',
                     day + '05010101' + f'{number:02d}', f'20230000{number:02d}',
                     '騎手', str(age), '父', ''])
    out = io.StringIO(newline='')
    csv.writer(out).writerows(rows)
    return out.getvalue().encode('cp932')


def source_db(path, latest='20261018'):
    db = sqlite3.connect(path)
    db.executescript('''
      CREATE TABLE races (race_id TEXT PRIMARY KEY,race_date TEXT,surface TEXT);
      CREATE TABLE race_horses (
        target_id TEXT PRIMARY KEY,race_id TEXT,horse_registration_number TEXT,
        finish_position INTEGER,popularity INTEGER,finish_status TEXT);
    ''')
    db.execute('INSERT INTO races VALUES (?,?,?)', ('2020010501010101', '20200105', '芝'))
    db.execute('INSERT INTO races VALUES (?,?,?)', (latest + '05010101', latest, 'ダ'))
    for number, (finish, popularity, status) in enumerate(
            ((3, 2, 'FINISHED'), (1, 4, 'FINISHED'), (4, 1, 'FINISHED'),
             (5, 5, 'FINISHED')), 1):
        db.execute('INSERT INTO race_horses VALUES (?,?,?,?,?,?)',
                   (latest + '05010101' + f'{number:02d}', latest + '05010101',
                    f'20230000{number:02d}', finish, popularity, status))
    db.commit(); db.close()


class Tua190Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root/'source.sqlite'
        source_db(self.db)

    def test_condition_and_competition_rank(self):
        report = evaluate_csv_bytes(csv21(), self.db)
        self.assertEqual(report['status'], 'EVALUATED')
        states = {row['horse_no']: row for row in report['audit']}
        self.assertEqual(states[1]['state'], 'MATCH')
        self.assertIn('previous_finish_1_or_2', states[2]['reasons'])
        self.assertIn('previous_popularity_1', states[3]['reasons'])
        self.assertIn('tua_below_190', states[4]['reasons'])
        self.assertEqual(states[3]['details']['tua_rank'], 3)
        self.assertEqual(report['summary']['MATCH'], 1)

    def test_previous_null_is_unconfirmed_and_counts_in_career(self):
        db = sqlite3.connect(self.db)
        db.execute("UPDATE race_horses SET finish_position=NULL,finish_status='DNF' "
                   "WHERE horse_registration_number='2023000001'")
        db.commit(); db.close()
        report = evaluate_csv_bytes(csv21(), self.db)
        row = report['audit'][0]
        self.assertEqual(row['state'], 'UNCONFIRMED')
        self.assertEqual(row['details']['career_jra_flat_before'], 1)
        self.assertIn('previous_finish_or_popularity_unknown', row['reasons'])

    def test_career_26_is_excluded(self):
        db = sqlite3.connect(self.db)
        for n in range(25):
            day = f'2025{n // 28 + 1:02d}{n % 28 + 1:02d}'
            race = day + '05010101'
            db.execute('INSERT OR IGNORE INTO races VALUES (?,?,?)', (race, day, '芝' if n % 2 else 'ダ'))
            db.execute('INSERT INTO race_horses VALUES (?,?,?,?,?,?)',
                       (race + '01', race, '2023000001', 4, 3, 'FINISHED'))
        db.commit(); db.close()
        row = evaluate_csv_bytes(csv21(), self.db)['audit'][0]
        self.assertEqual(row['details']['career_jra_flat_before'], 26)
        self.assertIn('career_over_25', row['reasons'])
        self.assertEqual(row['state'], 'NO_MATCH')

    def test_stale_history_never_matches(self):
        stale = self.root/'stale.sqlite'; source_db(stale, '20261012')
        report = evaluate_csv_bytes(csv21(), stale)
        self.assertEqual(report['freshness']['state'], 'STALE')
        self.assertFalse(any(row['state'] == 'MATCH' for row in report['audit']))
        self.assertTrue(any(row['state'] == 'UNCONFIRMED' for row in report['audit']))

    def test_snapshot_matches_source(self):
        source = self.root/'input.csv'; source.write_bytes(csv21())
        snapshot = self.root/'history.sqlite'
        metadata = create_snapshot(self.db, source, snapshot)
        original = evaluate_csv_bytes(source.read_bytes(), self.db)
        copied = evaluate_csv_bytes(source.read_bytes(), snapshot)
        self.assertEqual([(r['state'], r['reasons'], r['details']) for r in original['audit']],
                         [(r['state'], r['reasons'], r['details']) for r in copied['audit']])
        self.assertEqual(metadata['input_csv_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())

    def snapshot(self, raw=None):
        source = self.root/'input.csv'; source.write_bytes(raw or csv21())
        snapshot = self.root/'history.sqlite'
        create_snapshot(self.db, source, snapshot)
        return snapshot

    def test_missing_database_keeps_all_horses_unconfirmed_and_fixed_eight_unchanged(self):
        state = {}
        fixed = update_s2_audit(csv21(), state)
        before = encode(fixed['report'])
        result = update_tua190_audit(csv21(), state, snapshot_path=self.root/'missing.sqlite')
        self.assertEqual(result['status'], 'UNCONFIRMED')
        self.assertEqual(len(result['report']['audit']), 4)
        self.assertTrue(all(r['state'] == 'UNCONFIRMED' and r['and_passed'] is None for r in result['report']['audit']))
        self.assertEqual(encode(state[S2_KEY]['report']), before)
        self.assertIs(result['prospective_ready'], False)
        self.assertIs(result['prospective_verified'], False)

    def test_valid_snapshot_matches_shared_evaluator_exactly_and_is_read_only(self):
        snapshot = self.snapshot()
        before = snapshot.read_bytes()
        result = update_tua190_audit(csv21(), {}, snapshot_path=snapshot)
        self.assertEqual(result['status'], 'EVALUATED')
        self.assertEqual(encode(result['report']), encode(evaluate_csv_bytes(csv21(), snapshot)))
        self.assertEqual(snapshot.read_bytes(), before)
        self.assertIsNone(result['error'])

    def test_date_and_csv_hash_mismatch_never_reuse_previous_match(self):
        snapshot = self.snapshot()
        state = {}
        self.assertEqual(update_tua190_audit(csv21(), state, snapshot_path=snapshot)['report']['summary']['MATCH'], 1)
        changed = csv21().replace('馬1'.encode('cp932'), '馬A'.encode('cp932'))
        result = update_tua190_audit(changed, state, snapshot_path=snapshot)
        self.assertEqual(result['status'], 'UNCONFIRMED')
        self.assertIn('sha256', result['error']['message'])
        result = update_tua190_audit(csv21('20261025'), state, snapshot_path=snapshot)
        self.assertIn('date_mismatch', result['error']['message'])
        self.assertTrue(all(r['state'] != 'MATCH' for r in result['report']['audit']))

    def test_coverage_and_future_history_are_rejected(self):
        snapshot = self.snapshot()
        with sqlite3.connect(snapshot) as db:
            db.execute("DELETE FROM requested_horses WHERE horse_registration_number='2023000001'")
        result = update_tua190_audit(csv21(), {}, snapshot_path=snapshot)
        self.assertIn('coverage', result['error']['message'])
        with sqlite3.connect(snapshot) as db:
            db.execute("INSERT INTO requested_horses VALUES ('2023000001')")
            db.execute("UPDATE history SET race_date='20261024'")
        result = update_tua190_audit(csv21(), {}, snapshot_path=snapshot)
        self.assertIn('future_results', result['error']['message'])

    def test_stale_and_broken_db_and_input_clear_previous_results(self):
        stale = self.root/'stale.sqlite'; source_db(stale, '20261012')
        raw = self.root/'input.csv'; raw.write_bytes(csv21())
        snap = self.root/'stale_history.sqlite'; create_snapshot(stale, raw, snap)
        state = {}
        result = update_tua190_audit(csv21(), state, snapshot_path=snap)
        self.assertIn('stale', result['error']['message'])
        broken = self.root/'broken.sqlite'; broken.write_bytes(b'not sqlite')
        self.assertEqual(update_tua190_audit(csv21(), state, snapshot_path=broken)['status'], 'UNCONFIRMED')
        self.assertEqual(update_tua190_audit(b'bad csv', state, snapshot_path=broken)['status'], 'INVALID_INPUT')
        update_tua190_audit(None, state)
        self.assertNotIn(STATE_KEY, state)

    def test_multiple_dates_require_separate_day_snapshots(self):
        raw = csv21() + csv21('20261025').replace(b'20230000', b'20240000')
        source = self.root/'multi.csv'; source.write_bytes(raw)
        with self.assertRaises(ValueError):
            create_snapshot(self.db, source, self.root/'multi.sqlite')
        result = update_tua190_audit(raw, {}, snapshot_path=self.db)
        self.assertEqual(result['status'], 'UNCONFIRMED')
        self.assertIn('multiple_target_dates', result['error']['message'])
        self.assertFalse(any(r['state'] == 'MATCH' for r in result['report']['audit']))

    def test_snapshot_does_not_overwrite_destination_created_during_generation(self):
        source = self.root/'input.csv'; source.write_bytes(csv21())
        output = self.root/'history.sqlite'
        def competing_file(temp, destination):
            Path(destination).write_bytes(b'existing user file')
            raise FileExistsError('created concurrently')
        with patch('tua190_history_snapshot.os.link', side_effect=competing_file):
            with self.assertRaises(FileExistsError):
                create_snapshot(self.db, source, output)
        self.assertEqual(output.read_bytes(), b'existing user file')
        self.assertEqual(list(self.root.glob('.tua190-*')), [])

    def test_age_and_history_limits_and_cancelled_starts(self):
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO races VALUES ('2026101905010101','20261019','ダ')")
            db.execute("INSERT INTO race_horses VALUES ('cancelled','2026101905010101','2023000001',1,1,'CANCELLED')")
        row = evaluate_csv_bytes(csv21(), self.db)['audit'][0]
        self.assertEqual(row['state'], 'MATCH')
        self.assertEqual(row['details']['career_jra_flat_before'], 1)
        old = csv21().decode('cp932')
        rows = list(csv.reader(io.StringIO(old))); rows[0][18] = '7'
        stream = io.StringIO(newline=''); csv.writer(stream).writerows(rows)
        row = evaluate_csv_bytes(stream.getvalue().encode('cp932'), self.db)['audit'][0]
        self.assertEqual(row['state'], 'NO_MATCH')
        self.assertIn('age_over_6', row['reasons'])


if __name__ == '__main__':
    unittest.main()
