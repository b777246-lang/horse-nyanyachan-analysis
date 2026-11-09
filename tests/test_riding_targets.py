from pathlib import Path
import sqlite3
import tempfile
import unittest

from riding_targets import (
    CHANGE_KEY, CONTINUING_KEY, evaluate_riding_targets, load_previous_starts,
)


class RidingTargetTests(unittest.TestCase):
    def test_continuing_boundaries_and_classes(self):
        previous = {"jockey": "騎手A", "finish_position": 2}
        row = {"jockey": "騎手A", "fup": 6, "class_name": "3勝クラス", "venue": "東京"}
        self.assertEqual([m.key for m in evaluate_riding_targets(row, previous)], [CONTINUING_KEY])
        row["fup"] = 7; previous["finish_position"] = 5
        self.assertEqual([m.key for m in evaluate_riding_targets(row, previous)], [CONTINUING_KEY])
        for finish in (1, 6, None):
            previous["finish_position"] = finish
            self.assertEqual(evaluate_riding_targets(row, previous), ())
        previous["finish_position"] = 3; row["class_name"] = "2勝クラス"
        self.assertEqual(evaluate_riding_targets(row, previous), ())

    def test_new_jockey_rules_and_excluded_venues(self):
        previous = {"jockey": "騎手B", "finish_position": 2}
        row = {"jockey": "騎手A", "fup": 6.5, "class_name": "未勝利", "venue": "東京"}
        self.assertEqual([m.key for m in evaluate_riding_targets(row, previous)], [CHANGE_KEY])
        previous["finish_position"] = 1
        self.assertEqual(evaluate_riding_targets(row, previous), ())
        previous["finish_position"] = 7
        for venue in ("福島", "新潟", "小倉"):
            row["venue"] = venue
            self.assertEqual(evaluate_riding_targets(row, previous), ())
        row.update(venue="東京", class_name="新馬")
        self.assertEqual(evaluate_riding_targets(row, previous), ())

    def test_readonly_history_excludes_current_and_cancelled(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path = Path(folder) / "history.sqlite"
            db = sqlite3.connect(path)
            try:
                db.execute("CREATE TABLE races(race_id TEXT PRIMARY KEY,race_date TEXT)")
                db.execute("""CREATE TABLE race_horses(
                    target_id TEXT PRIMARY KEY,race_id TEXT,horse_registration_number TEXT,
                    jockey TEXT,finish_position INTEGER,finish_status TEXT)""")
                for race_id, day in (("old", "20261101"), ("cancel", "20261107"), ("current", "20261108")):
                    db.execute("INSERT INTO races VALUES(?,?)", (race_id, day))
                db.execute("INSERT INTO race_horses VALUES(?,?,?,?,?,?)",
                           ("old01", "old", "2024000001", "騎手B", 3, "FINISHED"))
                db.execute("INSERT INTO race_horses VALUES(?,?,?,?,?,?)",
                           ("cancel01", "cancel", "2024000001", "騎手C", None, "CANCELLED"))
                db.execute("INSERT INTO race_horses VALUES(?,?,?,?,?,?)",
                           ("current01", "current", "2024000001", "騎手D", 1, "FINISHED"))
                db.commit()
            finally:
                db.close()
            rows, error = load_previous_starts(path, [{
                "entry_id": "202611080000000001", "horse_id": "2024000001",
                "race_date": "20261108",
            }])
            self.assertIsNone(error)
            self.assertEqual(rows["202611080000000001"]["jockey"], "騎手B")
            self.assertEqual(rows["202611080000000001"]["finish_position"], 3)


if __name__ == "__main__":
    unittest.main()

