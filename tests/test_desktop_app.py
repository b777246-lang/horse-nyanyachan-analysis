import hashlib
import json
from pathlib import Path
from queue import Queue
import unittest
import tempfile
from unittest.mock import MagicMock, patch

import pandas as pd

from horse_app import HorseApp
from cushion_desktop_window import CushionViewerWindow


class DesktopAppTests(unittest.TestCase):
    def app(self):
        app = HorseApp.__new__(HorseApp)
        app.ext_comment_df = None
        app.set_display_data = MagicMock()
        app.load_course_data()
        return app

    def test_original_analysis_comments_and_jockeys_unchanged(self):
        expected = json.loads(Path('tests/fixtures/desktop_expected.json').read_text())
        for filename, digest in expected.items():
            app = self.app()
            frame = pd.read_csv(filename, encoding='cp932', header=None, converters={15: str, 16: str, 17: str})
            app.process_and_display_data(frame)
            rows = [{k: v for k, v in row.items() if k not in {'horse_id', 'surface'}} for row in app.export_data_list]
            self.assertEqual(hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest(), digest)
            if filename == '20261010.csv':
                self.assertEqual(app.export_data_list[0]['horse_id'], str(frame.iloc[0, 16]))
                self.assertEqual(app.export_data_list[0]['jockey'], str(frame.iloc[0, 17]))

    def test_csv_loader_preserves_leading_zero_ids(self):
        app = self.app()
        fields = ['file_label', 'ext_comment_btn', 'odds_btn', 'comment_sort_btn', 'reset_sort_btn', 'csv_btn', 'html_btn', 'kol_html_btn', 'sort_status_label']
        for name in fields:
            setattr(app, name, MagicMock())
        app.process_and_display_data = MagicMock()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '20261010.csv'
            frame = pd.read_csv('20261010.csv', encoding='cp932', header=None, dtype=str).iloc[:1].copy()
            frame[16] = '0000000001'
            frame.to_csv(path, encoding='cp932', header=False, index=False)
            with patch('horse_app.filedialog.askopenfilename', return_value=str(path)):
                app.load_csv()
            self.assertIsInstance(app.df_current.iloc[0, 16], str)
            self.assertEqual(app.df_current.iloc[0, 16], '0000000001')

    def test_old_race_network_response_is_discarded(self):
        window = CushionViewerWindow.__new__(CushionViewerWindow)
        window.generation = 2
        window.results = Queue()
        window.results.put((1, {'value': '9.2'}, None))
        window.results.put((2, {'value': None, 'message': '当日未公表'}, None))
        window._display, window.after, window.status = MagicMock(), MagicMock(), MagicMock()
        window._poll()
        window._display.assert_called_once_with(None, '当日未公表')

    def test_dialog_tracks_race_without_modifying_main_rows(self):
        app = self.app()
        app.view_rows = [{'馬番': 1, '馬名': 'テスト', 'race_id': '202610100501010101', 'horse_id': '0000000001', 'surface': '芝'}]
        app.sel_venue, app.sel_race, app.source_name = '東京', 1, '20261010.csv'
        app.cushion_window = None
        with patch('horse_app.CushionViewerWindow') as dialog:
            app.open_cushion_viewer()
            dialog.assert_called_once_with(app)
            dialog.return_value.sync.assert_called_once_with(app.view_rows, '東京', 1, '20261010.csv')
        self.assertEqual(app.view_rows[0]['horse_id'], '0000000001')


if __name__ == '__main__':
    unittest.main()
