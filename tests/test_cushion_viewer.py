from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from cushion_presentation import build_viewer_records
from data_loader import read_main_csv, normalize_main_frame
from cushion_stats import aggregate_history
from test_cushion_stats import HORSE, run


class CushionViewerTests(unittest.TestCase):
    def setUp(self):
        # Fix the input fixture independently of new daily CSV uploads.
        self.csv_patch = patch('data_loader.latest_csv', side_effect=lambda directory='.', comments=False: None if comments else Path('20261010.csv'))
        self.csv_patch.start()
        self.addCleanup(self.csv_patch.stop)

    def test_shared_records_keep_missing_horses_and_numbers(self):
        report = {'horses': aggregate_history([run(1, finish_position=1, win_return_yen=360)], [HORSE, '0000000002'], '20260102', 9.2)}
        entrants = [{'horse_no': 3, 'horse_name': '未照合', 'horse_id': ''},
                    {'horse_no': 2, 'horse_name': '履歴なし', 'horse_id': '0000000002'},
                    {'horse_no': 1, 'horse_name': '勝馬', 'horse_id': HORSE}]
        rows = build_viewer_records(entrants, report)
        self.assertEqual([row['馬番'] for row in rows], [1, 2, 3])
        self.assertEqual(rows[0]['単回収率(%)'], 360)
        self.assertEqual(rows[1]['着別度数'], '0-0-0-0/0')
        self.assertIsNone(rows[1]['複勝率(%)'])
        self.assertIn('血統登録番号', rows[2]['備考'])

    def test_web_controls_unavailable_value_invalid_precision_and_dirt(self):
        at = AppTest.from_file(str(Path('app.py').resolve()), default_timeout=60).run()
        self.assertFalse(at.exception)
        self.assertTrue(any('ダートレース' in v.value for v in at.info))
        venue = at.get('button_group')[0].value
        at.get('button_group')[1].set_value(2).run()
        self.assertFalse(at.exception)
        at.radio(key='cushion_input_mode').set_value('手動入力').run()
        self.assertEqual(len(at.dataframe), 1)
        self.assertTrue(any('未取得' in v.value for v in at.info))
        frame = at.dataframe[0].value
        self.assertEqual(len(frame), 13)
        self.assertEqual(frame['対象走数'].sum(), 0)
        key = f'cushion_value_20261010_{venue}'
        at.text_input(key=key).set_value('6.45').run()
        self.assertFalse(at.exception)
        self.assertTrue(any('小数第1位' in v.value for v in at.warning))
        at.text_input(key=key).set_value('9.2').run()
        self.assertFalse(at.exception)
        self.assertTrue(any('8.5～9.4' in v.value for v in at.markdown))
        at.selectbox(key='cushion_sort').set_value('対象走数').run()
        self.assertFalse(at.exception)
        at.get('button_group')[1].set_value('ALL').run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.dataframe), 0)

    def test_web_snapshot_results_and_sort_preserve_all_entrants(self):
        at = AppTest.from_file(str(Path('app.py').resolve()), default_timeout=60).run()
        venue = at.get('button_group')[0].value
        main = normalize_main_frame(read_main_csv('20261010.csv'))
        horse_id = main[main['race'].eq('東2')].iloc[0]['horse_id']
        report = {'metadata': {'source_first_date': '20200105', 'source_last_date': '20261004'},
                  'horses': aggregate_history([run(1, horse_registration_number=horse_id, finish_position=1, win_return_yen=360)], [horse_id], '20261010', 9.2)}
        with patch('cushion_viewer.Path.is_file', return_value=True), patch('cushion_viewer.get_cushion_stats', return_value=report) as fetch:
            at.get('button_group')[1].set_value(2).run()
            at.radio(key='cushion_input_mode').set_value('手動入力').run()
            at.text_input(key=f'cushion_value_20261010_{venue}').set_value('9.2').run()
            self.assertFalse(at.exception)
            self.assertEqual(len(at.dataframe[0].value), 13)
            self.assertEqual(fetch.call_args.args[2:4], ('20261010', '9.2'))
            self.assertEqual(at.dataframe[0].value['対象走数'].sum(), 1)
            self.assertEqual(at.dataframe[0].value.iloc[0]['単回収率(%)'], 360)
            at.selectbox(key='cushion_sort').set_value('勝率(%)').run()
            self.assertEqual(at.dataframe[0].value.iloc[0]['単回収率(%)'], 360)
            self.assertTrue(any('20261004' in v.value for v in at.caption))
            at.checkbox(key='cushion_official_only').check().run()
            self.assertTrue(fetch.call_args.kwargs['official_only'])
            fetch.side_effect = sqlite3.DatabaseError('invalid test database')
            at.run()
            self.assertFalse(at.exception)
            self.assertTrue(any('軽量DBを利用できません' in v.value for v in at.warning))
            self.assertEqual(len(at.dataframe[0].value), 13)


if __name__ == '__main__':
    unittest.main()
