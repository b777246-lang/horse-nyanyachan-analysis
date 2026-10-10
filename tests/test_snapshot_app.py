import hashlib
from pathlib import Path
from queue import Queue
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from cushion_snapshot import COLUMNS, read_entrants
from cushion_snapshot_app import SnapshotCreator
from horse_app import HorseApp
from test_cushion_stats import run


class SnapshotAppTests(unittest.TestCase):
    def creator(self, source, csv_path, output):
        app = SnapshotCreator.__new__(SnapshotCreator)
        app.running = False
        app.results = Queue()
        for name, value in [('source', source), ('csv', csv_path), ('output', output)]:
            setattr(app, name, MagicMock())
            getattr(app, name).get.return_value = str(value)
        app.status, app.create_button, app.progress, app.after, app.on_created = [MagicMock() for _ in range(5)]
        return app

    def test_gui_creates_real_snapshot_reports_completion_and_keeps_source_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'source.db', Path(folder) / 'history.sqlite'
            ids, day = read_entrants('20261010.csv')
            row = run(1, horse_registration_number=ids[0])
            with sqlite3.connect(source) as connection:
                connection.execute('CREATE TABLE race_horses (' + ','.join(COLUMNS[:10]) + ')')
                connection.execute('CREATE TABLE races (' + ','.join(COLUMNS[10:]) + ',race_id)')
                connection.execute('INSERT INTO race_horses VALUES (' + ','.join('?' for _ in COLUMNS[:10]) + ')', tuple(row[k] for k in COLUMNS[:10]))
                connection.execute('INSERT INTO races VALUES (' + ','.join('?' for _ in range(10)) + ')', (*[row[k] for k in COLUMNS[10:]], row['race_id']))
            before = hashlib.sha256(source.read_bytes()).digest()
            app = self.creator(source, '20261010.csv', output)
            def thread(target, daemon):
                result = MagicMock()
                result.start.side_effect = target
                return result
            with patch('cushion_snapshot_app.Thread', side_effect=thread):
                app.start()
            self.assertTrue(app.running)
            app._poll()
            self.assertFalse(app.running)
            self.assertTrue(output.exists())
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), before)
            path, metadata = app.on_created.call_args.args
            self.assertEqual(path, str(output))
            self.assertEqual(metadata['target_date'], day)
            self.assertEqual(metadata['requested_horses'], '315')
            self.assertEqual(metadata['history_rows'], '1')
            self.assertIn('作成完了', app.status.set.call_args.args[0])
            # An existing output is never overwritten, even through the GUI.
            before = output.read_bytes()
            with patch('cushion_snapshot_app.Thread') as worker:
                app.start()
                worker.assert_not_called()
            self.assertEqual(output.read_bytes(), before)
            self.assertIn('同名ファイル', app.status.set.call_args.args[0])

    def test_invalid_input_and_worker_error_are_visible(self):
        app = self.creator('', '', '')
        with patch('cushion_snapshot_app.Thread') as worker:
            app.start()
            worker.assert_not_called()
        self.assertIn('3項目', app.status.set.call_args.args[0])
        app.results.put(('output.sqlite', None, 'schema mismatch'))
        app._poll()
        self.assertIn('schema mismatch', app.status.set.call_args.args[0])
        app.on_created.assert_not_called()

    def test_created_snapshot_only_updates_matching_race_date(self):
        app = HorseApp.__new__(HorseApp)
        window = MagicMock()
        window.context = ([{'race_id': '202610100501010101'}], '東京', 1)
        app.cushion_window = window
        app._on_snapshot_created('new.sqlite', {'target_date': '20261011'})
        window.refresh.assert_not_called()
        app._on_snapshot_created('new.sqlite', {'target_date': '20261010'})
        self.assertEqual(window.db_path, 'new.sqlite')
        window.refresh.assert_called_once()


if __name__ == '__main__':
    unittest.main()
