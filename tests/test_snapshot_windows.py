"""Enforce Windows file-lifetime constraints even on a Linux test runner."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from cushion_snapshot import COLUMNS, create_snapshot
from test_cushion_stats import HORSE, run


class SnapshotWindowsTests(unittest.TestCase):
    def test_destination_closed_before_publish_and_cleanup_on_success_and_failure(self):
        for invalid_source in (False, True):
            with self.subTest(invalid_source=invalid_source), tempfile.TemporaryDirectory() as folder:
                source, output = Path(folder) / 'source.db', Path(folder) / 'history.sqlite'
                row = run(1)
                with sqlite3.connect(source) as connection:
                    connection.execute('CREATE TABLE races (' + ','.join(COLUMNS[10:]) + ',race_id)')
                    connection.execute('INSERT INTO races VALUES (' + ','.join('?' for _ in range(10)) + ')', (*[row[k] for k in COLUMNS[10:]], row['race_id']))
                    if not invalid_source:
                        connection.execute('CREATE TABLE race_horses (' + ','.join(COLUMNS[:10]) + ')')
                        connection.execute('INSERT INTO race_horses VALUES (' + ','.join('?' for _ in COLUMNS[:10]) + ')', tuple(row[k] for k in COLUMNS[:10]))
                opened = {}
                original_connect, original_unlink = sqlite3.connect, Path.unlink
                class TrackingConnection(sqlite3.Connection):
                    closed = False
                    def close(self):
                        super().close()
                        self.closed = True
                def connect(path, *args, **kwargs):
                    connection = original_connect(path, *args, factory=TrackingConnection, **kwargs)
                    if '.cushion-' in str(path):
                        opened[str(path)] = connection
                    return connection
                def unlink(path, *args, **kwargs):
                    if str(path) in opened and not opened[str(path)].closed:
                        raise PermissionError('simulated WinError 32: database still open')
                    return original_unlink(path, *args, **kwargs)
                import os
                original_link = os.link
                def link(src, dst):
                    self.assertTrue(opened[str(src)].closed, 'SQLite must close before publishing')
                    return original_link(src, dst)
                with patch('cushion_snapshot.sqlite3.connect', side_effect=connect), patch.object(Path, 'unlink', unlink), patch('cushion_snapshot.os.link', side_effect=link):
                    if invalid_source:
                        with self.assertRaises(sqlite3.OperationalError):
                            create_snapshot(source, output, [HORSE], '20260102')
                    else:
                        create_snapshot(source, output, [HORSE], '20260102')
                self.assertTrue(opened)
                self.assertTrue(all(c.closed for c in opened.values()))
                self.assertEqual(list(Path(folder).glob('.cushion-*')), [])
                self.assertEqual(output.exists(), not invalid_source)


if __name__ == '__main__':
    unittest.main()
