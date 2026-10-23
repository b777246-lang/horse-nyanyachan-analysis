import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from analysis import analyze_csv
from data_loader import read_main_csv, normalize_main_frame, load_course_data
from export import build_target_csv, build_html_report
from formatting import format_analysis_frame
from sire_snapshot import read_sire_entrants
from sire_stats import get_sire_stats
from sire_presentation import build_sire_records

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'sire_history_20261018.sqlite'


class SireWebTests(unittest.TestCase):
    def setUp(self):
        source = patch('data_loader.latest_csv', side_effect=lambda directory='.', comments=False: ROOT / ('20261018comment.csv' if comments else '20261018.csv'))
        source.start()
        self.addCleanup(source.stop)
        self.pending = patch('cushion_viewer.cached_jra_cushion', return_value={'value': None, 'message': '当日未公表（テスト）'})
        self.fetch = self.pending.start()
        self.addCleanup(self.pending.stop)

    def test_column20_and_legacy_csv_do_not_change_existing_exports(self):
        full = read_main_csv('20261018.csv')
        named = normalize_main_frame(full)
        self.assertEqual(named.iloc[0]['sire_name'], 'シルバーステート')
        pd.testing.assert_frame_equal(normalize_main_frame(named), named)
        for count in (18, 19):
            self.assertTrue(normalize_main_frame(full.iloc[:, :count])['sire_name'].eq('').all())
        before = analyze_csv(full.iloc[:, :19], load_course_data(), {})
        after = analyze_csv(full, load_course_data(), {})
        pd.testing.assert_frame_equal(before.frame, after.frame)
        self.assertEqual(build_target_csv(before.frame), build_target_csv(after.frame))
        self.assertEqual(build_html_report(format_analysis_frame(before.frame, before.notes)),
                         build_html_report(format_analysis_frame(after.frame, after.notes)))

    def test_both_tabs_share_one_fetch_and_sire_records_match_shared_api(self):
        self.fetch.return_value = dict(value='9.2', measurement_text='10月18日（日曜）7時00分', fetched_at='test', year_basis='検証値', source_url='https://www.jra.go.jp/')
        at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=60).run()
        self.assertFalse(at.exception)
        self.fetch.assert_called_once()
        self.assertEqual([tab.label for tab in at.tabs], ['出走馬別成績', '種牡馬別成績'])
        main = normalize_main_frame(read_main_csv('20261018.csv'))
        entrants = [dict(horse_no=r['horse_no'], horse_name=r['horse_name'], horse_id=r['horse_id'], sire_name=r['sire_name'])
                    for _, r in main[main['race'].eq('新1')].iterrows()]
        expected = build_sire_records(entrants, get_sire_stats(SNAPSHOT, entrants, '20261018', '9.2', venue='新潟', distance=1200), venue='新潟', distance=1200)
        actual = at.tabs[1].dataframe[0].value
        pd.testing.assert_frame_equal(actual, pd.DataFrame(expected))
        self.assertEqual(list(actual.columns[:4]), ['馬番', '馬名', '種牡馬', '産駒着別度数'])
        self.assertNotIn('コース', actual.columns)
        self.assertNotIn('当日クッション値帯', actual.columns)
        self.assertTrue(any('種牡馬DBを自動読込' in message.value for message in at.tabs[1].caption))
        # Every turf race remains selectable, with its course and same current value.
        at.get('button_group')[0].set_value('京都').run()
        kyoto = main[main['race'].str.startswith('京') & main['surface'].eq('芝')]
        at.get('button_group')[1].set_value(int(kyoto.iloc[0]['race'][1:])).run()
        self.assertFalse(at.exception)
        self.assertEqual(at.tabs[1].dataframe[0].value['馬名'].tolist(), kyoto[kyoto['race'].eq(kyoto.iloc[0]['race'])]['horse_name'].tolist())
        at.checkbox(key='cushion_official_only').check().run()
        self.assertFalse(at.exception)

    def test_missing_cushion_and_independent_db_failures_keep_original_tab(self):
        at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=60).run()
        self.assertFalse(at.exception)
        self.assertTrue(at.tabs[1].dataframe[0].value['産駒着別度数'].eq('—').all())
        self.assertTrue(at.tabs[1].dataframe[0].value['備考'].str.contains('判定不可').all())
        at.radio(key='cushion_input_mode').set_value('手動入力').run()
        at.text_input(key='cushion_value_20261018_新潟').set_value('9.2').run()
        previous = at.tabs[0].dataframe[0].value.copy()
        with patch('sire_web.get_sire_stats', side_effect=sqlite3.DatabaseError('broken sire DB')):
            at.run()
            self.assertFalse(at.exception)
            pd.testing.assert_frame_equal(previous, at.tabs[0].dataframe[0].value)
            self.assertTrue(any('broken sire DB' in msg.value for msg in at.tabs[1].info))
        with patch('cushion_viewer.get_cushion_stats', side_effect=sqlite3.DatabaseError('broken horse DB')):
            at.run()
            self.assertFalse(at.exception)
            self.assertGreater(at.tabs[1].dataframe[0].value['対象走数'].sum(), 0)
        # Missing sire files yield a visible explanation, not a fabricated zero.
        real_exists = Path.is_file
        with patch.object(Path, 'is_file', lambda path: False if path.name.startswith('sire_history_') else real_exists(path)):
            at.run()
            self.assertFalse(at.exception)
            self.assertTrue(at.tabs[1].dataframe[0].value['産駒着別度数'].eq('—').all())
            self.assertTrue(any('種牡馬DBがありません' in msg.value for msg in at.tabs[1].info))
        at.get('button_group')[1].set_value('ALL').run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.tabs), 0)
        at.get('button_group')[0].set_value('東京').run()
        at.get('button_group')[1].set_value(1).run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.tabs), 0)

    def test_wrong_day_sire_name_and_scope_are_not_zero_starts(self):
        entrants, day, _ = read_sire_entrants('20261018.csv')
        first = next(e for e in entrants if e['surface'] == '芝')
        with self.assertRaises(ValueError):
            get_sire_stats(SNAPSHOT, [first], '20261017', '9.2', venue=first['venue'], distance=first['distance'])
        mismatch = dict(first, sire_name='一致しない父名')
        report = get_sire_stats(SNAPSHOT, [mismatch], day, '9.2', venue=first['venue'], distance=first['distance'])
        self.assertEqual(report['horses'][0]['reason'], 'sire_mismatch')
        record = build_sire_records([mismatch], report)[0]
        self.assertEqual(record['産駒着別度数'], '—')
        report = get_sire_stats(SNAPSHOT, [first], day, '9.2', venue='存在しない場', distance=first['distance'])
        self.assertEqual(report['horses'][0]['reason'], 'course_not_in_snapshot')

    def test_unknown_sire_and_genuine_zero_have_distinct_displays(self):
        entrants, day, _ = read_sire_entrants('20261018.csv')
        first = next(e for e in entrants if e['surface'] == '芝')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'copy.sqlite'
            source = sqlite3.connect(SNAPSHOT.as_uri() + '?mode=ro', uri=True)
            destination = sqlite3.connect(path)
            try:
                source.backup(destination)
                destination.execute("UPDATE entrant_sires SET sire_name='' WHERE horse_registration_number=?", (first['horse_id'],))
                destination.commit()
                unknown = dict(first, sire_name='')
                report = get_sire_stats(path, [unknown], day, '9.2', venue=first['venue'], distance=first['distance'])
                self.assertEqual(report['horses'][0]['reason'], 'sire_unknown')
                self.assertEqual(build_sire_records([unknown], report)[0]['産駒着別度数'], '—')
                destination.execute('UPDATE entrant_sires SET sire_name=? WHERE horse_registration_number=?', (first['sire_name'], first['horse_id']))
                destination.execute('DELETE FROM sire_history WHERE sire_name=? AND venue=? AND distance=?', (first['sire_name'], first['venue'], first['distance']))
                destination.commit()
                report = get_sire_stats(path, [first], day, '9.2', venue=first['venue'], distance=first['distance'])
                self.assertIsNone(report['horses'][0]['reason'])
                self.assertEqual(build_sire_records([first], report)[0]['産駒着別度数'], '0-0-0-0/0')
            finally:
                source.close()
                destination.close()

    def test_all_3472_results_match_independent_sql_using_original_values(self):
        entrants, day, _ = read_sire_entrants('20261018.csv')
        groups = {}
        for horse in entrants:
            if horse['surface'] == '芝':
                groups.setdefault((horse['venue'], horse['target_id'][14:16], horse['distance']), []).append(horse)
        before = hashlib.sha256(SNAPSHOT.read_bytes()).digest()
        db = sqlite3.connect(SNAPSHOT.as_uri() + '?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        comparisons = 0
        try:
            for (venue, race, distance), horses in groups.items():
                for band, value in enumerate(('6.4', '6.5', '7.5', '8.5', '9.5', '10.5', '11.5'), 1):
                    for official in (False, True):
                        report = get_sire_stats(SNAPSHOT, horses, day, value, venue=venue, distance=distance, official_only=official)
                        for row in report['horses']:
                            expected = db.execute('''SELECT COUNT(*) n,
                                SUM(CASE WHEN finish_position=1 THEN 1 ELSE 0 END) first,
                                SUM(CASE WHEN finish_position=2 THEN 1 ELSE 0 END) second,
                                SUM(CASE WHEN finish_position=3 THEN 1 ELSE 0 END) third,
                                SUM(win_return_yen) win, SUM(place_return_yen) place
                                FROM sire_history WHERE sire_name=? AND venue=? AND surface='芝'
                                AND distance=? AND race_date<? AND cushion_value IS NOT NULL
                                AND (CASE WHEN cushion_value<=6.4 THEN 1 WHEN cushion_value<=7.4 THEN 2
                                    WHEN cushion_value<=8.4 THEN 3 WHEN cushion_value<=9.4 THEN 4
                                    WHEN cushion_value<=10.4 THEN 5 WHEN cushion_value<=11.4 THEN 6 ELSE 7 END)=?
                                AND cushion_status IN ('JRA_PDF_VERIFIED','CSV_PROVIDED')
                                AND (?=0 OR cushion_status='JRA_PDF_VERIFIED') AND bet_eligible=1
                                AND ((finish_status IN ('FINISHED','DEMOTED') AND finish_position>0)
                                    OR (finish_status IN ('DNF','DISQUALIFIED') AND finish_position IS NULL))''',
                                (row['sire_name'], venue, distance, day, band, int(official))).fetchone()
                            stats = row['stats']
                            self.assertIsNotNone(stats)
                            self.assertEqual(stats['starts'], expected['n'])
                            for key in ('first', 'second', 'third'):
                                self.assertEqual(stats[key], expected[key] or 0)
                            self.assertEqual(sum(stats[k] for k in ('first', 'second', 'third', 'unplaced')), stats['starts'])
                            for kind in ('win', 'place'):
                                self.assertAlmostEqual(stats[kind + '_total_yen'], expected[kind] or 0)
                                if expected['n']:
                                    self.assertAlmostEqual(stats[kind + '_roi'], expected[kind] / expected['n'])
                                else:
                                    self.assertIsNone(stats[kind + '_roi'])
                            comparisons += 1
        finally:
            db.close()
        self.assertEqual(comparisons, 3472)
        self.assertEqual(hashlib.sha256(SNAPSHOT.read_bytes()).digest(), before)


if __name__ == '__main__':
    unittest.main()
