import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from cushion_stats import aggregate_history, cushion_band, get_cushion_stats, normalize_horse_id
from cushion_snapshot import create_snapshot, read_entrants

HORSE = '0000000001'


def run(number, **overrides):
    row = dict(horse_registration_number=HORSE, target_id=f'2026010105010101{number:02}',
               race_id='2026010105010101', horse_number=number, horse_name='テスト馬',
               finish_position=4, finish_status='FINISHED', bet_eligible=1,
               win_return_yen=0, place_return_yen=0, race_date='20260101', venue='東京',
               surface='芝', distance=1600, course='芝1600', track_condition='良',
               track_condition_raw='良', cushion_value=9.2, cushion_status='JRA_PDF_VERIFIED')
    row.update(overrides)
    return row


class CushionStatsTests(unittest.TestCase):
    def test_all_boundaries_and_reject_extra_precision(self):
        for value, band in [('5.4', 1), ('6.4', 1), ('6.5', 2), ('7.4', 2), ('7.5', 3),
                            ('8.4', 3), ('8.5', 4), ('9.4', 4), ('9.5', 5), ('10.4', 5),
                            ('10.5', 6), ('11.4', 6), ('11.5', 7), ('12.2', 7)]:
            self.assertEqual(cushion_band(value), band)
        for value in ('6.45', float('nan'), float('inf'), None, '', -1, 0):
            with self.assertRaises(ValueError):
                cushion_band(value)
        self.assertEqual(normalize_horse_id(' 0000000001 '), HORSE)
        with self.assertRaises(ValueError):
            normalize_horse_id('1')

    def test_counts_rates_returns_and_adjudicated_outcomes(self):
        rows = [run(1, finish_position=1, win_return_yen=360, place_return_yen=120),
                run(2, finish_position=2, finish_status='DEMOTED', place_return_yen=140),
                run(3, finish_position=3, place_return_yen=180), run(4),
                run(5, finish_status='DNF', finish_position=None),
                run(6, finish_status='DISQUALIFIED', finish_position=None, win_return_yen=170, place_return_yen=110),
                run(7, finish_status='CANCELLED', bet_eligible=0, finish_position=None, win_return_yen=None, place_return_yen=None),
                run(8, finish_status='EXCLUDED', bet_eligible=0, finish_position=None)]
        result = aggregate_history(rows, [HORSE], '20260102', 9.2)[0]
        self.assertEqual(result['finish_counts'], '1-1-1-3/6')
        self.assertAlmostEqual(result['win_rate'], 100 / 6)
        self.assertAlmostEqual(result['quinella_rate'], 200 / 6)
        self.assertEqual(result['place_rate'], 50)
        self.assertAlmostEqual(result['win_roi'], 530 / 6)
        self.assertAlmostEqual(result['place_roi'], 550 / 6)
        self.assertEqual((result['dnf'], result['disqualified']), (1, 1))
        self.assertEqual(result['issues'], [])

    def test_filters_dates_missing_and_unknown_status(self):
        rows = [run(1), run(2, surface='ダ'), run(3, race_date='20260102'),
                run(4, race_date='20260103'), run(5, cushion_value=9.5),
                run(6, horse_registration_number='0000000002'),
                run(7, cushion_value=6.45), run(8, finish_status='UNKNOWN'),
                run(9, cushion_status='NOT_PUBLISHED'), run(10, cushion_value=None),
                run(11, finish_position=None), run(12, finish_status='DNF', finish_position=1),
                run(13, cushion_status='CSV_PROVIDED')]
        result = aggregate_history(rows, [HORSE], '20260102', 9.2)[0]
        self.assertEqual(result['starts'], 2)
        self.assertEqual(len(result['issues']), 4)
        self.assertEqual(result['source_counts']['CSV_PROVIDED'], 1)
        self.assertEqual(aggregate_history(rows, [HORSE], '20260102', 9.2, official_only=True)[0]['starts'], 1)
        self.assertEqual(aggregate_history(rows, [HORSE], '20260102', 9.2, track='京都')[0]['starts'], 0)
        self.assertEqual(aggregate_history(rows, [HORSE], '20260102', 9.2, distance=2000)[0]['starts'], 0)
        with self.assertRaises(ValueError):
            aggregate_history([run(1), run(1)], [HORSE], '20260102', 9.2)

    def test_missing_return_does_not_become_zero_or_change_denominator(self):
        result = aggregate_history([run(1, win_return_yen=None), run(2)], [HORSE], '20260102', 9.2)[0]
        self.assertEqual(result['starts'], 2)
        self.assertIsNone(result['win_roi'])
        self.assertEqual(result['place_roi'], 0)
        self.assertEqual(result['win_missing'], 1)
        for bad in (-1, float('nan'), float('inf'), 120.5):
            self.assertIsNone(aggregate_history([run(1, win_return_yen=bad)], [HORSE], '20260102', 9.2)[0]['win_roi'])

    def test_no_data_and_cushion_unavailable_keep_every_horse(self):
        result = aggregate_history([], [HORSE, '0000000002'], '20260102', 9.2)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['finish_counts'], '0-0-0-0/0')
        for key in ('win_rate', 'quinella_rate', 'place_rate', 'win_roi', 'place_roi'):
            self.assertIsNone(result[0][key])
        result = aggregate_history([run(1)], [HORSE], '20260102', None)[0]
        self.assertEqual(result['reason'], 'cushion_unavailable')
        self.assertEqual(result['starts'], 0)

    def test_actual_csv_preserves_registration_numbers(self):
        ids, day = read_entrants('20261010.csv')
        self.assertEqual(day, '20261010')
        self.assertEqual(len(ids), 315)
        self.assertTrue(all(len(horse) == 10 for horse in ids))

    def test_snapshot_roundtrip_source_unchanged_and_no_future_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / 'source.db', Path(tmp) / 'snapshot.sqlite'
            with sqlite3.connect(source) as db:
                db.execute('CREATE TABLE races (race_id TEXT PRIMARY KEY, race_date TEXT, venue TEXT, surface TEXT, distance INTEGER, course TEXT, track_condition TEXT, track_condition_raw TEXT, cushion_value REAL, cushion_status TEXT)')
                db.execute('CREATE TABLE race_horses (horse_registration_number TEXT, target_id TEXT PRIMARY KEY, race_id TEXT, horse_number INTEGER, horse_name TEXT, finish_position INTEGER, finish_status TEXT, bet_eligible INTEGER, win_return_yen REAL, place_return_yen REAL)')
                db.execute('CREATE INDEX ix_horses_registration_history ON race_horses(horse_registration_number,race_id)')
                rows = [run(1, finish_position=1, win_return_yen=360),
                        run(2, race_id='2026010205010101', race_date='20260102', cushion_value=6.45),
                        run(3, race_id='2026010305010101', race_date='20260103')]
                for row in rows:
                    db.execute('INSERT OR IGNORE INTO races VALUES (?,?,?,?,?,?,?,?,?,?)', tuple(row[k] for k in ['race_id', 'race_date', 'venue', 'surface', 'distance', 'course', 'track_condition', 'track_condition_raw', 'cushion_value', 'cushion_status']))
                    db.execute('INSERT INTO race_horses VALUES (?,?,?,?,?,?,?,?,?,?)', tuple(row[k] for k in ['horse_registration_number', 'target_id', 'race_id', 'horse_number', 'horse_name', 'finish_position', 'finish_status', 'bet_eligible', 'win_return_yen', 'place_return_yen']))
            digest = hashlib.sha256(source.read_bytes()).digest()
            metadata = create_snapshot(source, output, [HORSE, '0000000002'], '20260103')
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), digest)
            self.assertEqual(metadata['history_rows'], '2')
            self.assertEqual(metadata['cushion_anomalies'], '1')
            self.assertEqual(metadata['source_last_date'], '20260103')
            result = get_cushion_stats(output, [HORSE, '0000000002', '0000000003'], '20260103', 9.2)
            self.assertEqual(result['horses'][0]['win_roi'], 360)
            self.assertEqual(result['horses'][1]['reason'], 'no_matching_history')
            self.assertEqual(result['horses'][2]['reason'], 'horse_not_in_snapshot')
            self.assertEqual(get_cushion_stats(output, [HORSE], '20260101', 9.2)['horses'][0]['starts'], 0)
            with self.assertRaises(ValueError):
                get_cushion_stats(output, [HORSE], '20260104', 9.2)
            with sqlite3.connect(output) as db:
                self.assertEqual(db.execute('SELECT cushion_value,cushion_band FROM history WHERE horse_number=2').fetchone(), (6.45, None))
            with self.assertRaises(ValueError):
                create_snapshot(source, source, [HORSE], '20260103')
            with self.assertRaises(ValueError):
                create_snapshot(source, output, [HORSE], '20260103')


if __name__ == '__main__':
    unittest.main()
