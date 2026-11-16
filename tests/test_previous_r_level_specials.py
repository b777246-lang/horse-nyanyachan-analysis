from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

import pandas as pd

from analysis import analyze_csv
from config import DEFAULT_SETTINGS
from signals import DEFAULT_REGISTRY


def main_row(venue, venue_code, *, arms=10, s_value=10, condition="1勝クラス"):
    abbr = {"小倉": "小", "新潟": "新", "福島": "福"}[venue]
    return [
        abbr + "1", condition, "芝", "1800", "1", "1", "", "人工馬",
        str(arms), "20", "30", str(s_value), "50", "6", "10",
        f"20261116{venue_code}01010101", "2024000001", "騎手", "3", "人工父", "", "普通",
    ]


class PreviousRaceLevelSpecialTests(unittest.TestCase):
    def test_rule_boundaries_and_venue_are_explicit(self):
        kokura = {"venue": "小倉", "S": 55, "S_rank": 1, "previous_r_level": "高＋"}
        self.assertIn("kokura_prev_high_plus_s", [m.key for m in DEFAULT_REGISTRY.evaluate(kokura, DEFAULT_SETTINGS)])
        for changes in ({"venue": "東京"}, {"S": 54.99}, {"S_rank": 2}, {"previous_r_level": "高★"}):
            context = dict(kokura, **changes)
            self.assertNotIn("kokura_prev_high_plus_s", [m.key for m in DEFAULT_REGISTRY.evaluate(context, DEFAULT_SETTINGS)])

        niigata = {"venue": "新潟", "arms": 110, "arms_rank": 3, "previous_r_level": "高★"}
        self.assertIn("niigata_prev_high_star_arms", [m.key for m in DEFAULT_REGISTRY.evaluate(niigata, DEFAULT_SETTINGS)])
        for changes in ({"venue": "小倉"}, {"arms": 109.99}, {"arms_rank": 4}, {"previous_r_level": "高＋"}):
            context = dict(niigata, **changes)
            self.assertNotIn("niigata_prev_high_star_arms", [m.key for m in DEFAULT_REGISTRY.evaluate(context, DEFAULT_SETTINGS)])

        local = {"venue": "福島", "surface": "芝", "condition": "未勝利",
                 "previous_venue": "東京", "previous_surface": "ダ",
                 "previous_r_level": "高★", "previous_finish_position": 2}
        self.assertIn("local_prev_high_star_maiden", [m.key for m in DEFAULT_REGISTRY.evaluate(local, DEFAULT_SETTINGS)])
        for changes in ({"venue": "東京"}, {"surface": "障"}, {"condition": "1勝クラス"},
                        {"previous_venue": "福島"}, {"previous_surface": "障"},
                        {"previous_r_level": "高＋"}, {"previous_finish_position": 1},
                        {"previous_finish_position": 10}):
            context = dict(local, **changes)
            self.assertNotIn("local_prev_high_star_maiden", [m.key for m in DEFAULT_REGISTRY.evaluate(context, DEFAULT_SETTINGS)])

    def test_web_analysis_passes_previous_r_level_into_special_engine(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            db_path = Path(folder) / "history.sqlite"
            with closing(sqlite3.connect(db_path)) as db:
                db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)")
                db.execute("INSERT INTO metadata VALUES('source_latest_prior_date','20261115')")
                db.execute('''CREATE TABLE history(
                    horse_registration_number TEXT,target_id TEXT PRIMARY KEY,race_id TEXT,
                    race_date TEXT,surface TEXT,finish_position INTEGER,popularity INTEGER,
                    finish_status TEXT,jockey TEXT,r_level TEXT,r_level_status TEXT)''')
                db.execute("INSERT INTO history VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                    "2024000001", "old01", "old", "20261115", "芝", 3, 4,
                    "FINISHED", "騎手", "高＋", "AVAILABLE"))
                db.commit()

            result = analyze_csv(pd.DataFrame([main_row("小倉", "10", s_value=55)]), {}, {}, history_db_path=db_path)
            self.assertIn("★前走高＋小倉特注★", result.frame.iloc[0]["総合評価・コース相性判定"])
            self.assertIn("★前走高＋小倉特注★", result.notes[0]["special_comments"])

            with closing(sqlite3.connect(db_path)) as db:
                db.execute("UPDATE history SET r_level='高★'")
                db.commit()
            result = analyze_csv(pd.DataFrame([main_row("新潟", "04", arms=110)]), {}, {}, history_db_path=db_path)
            self.assertIn("★前走高★新潟特注★", result.frame.iloc[0]["総合評価・コース相性判定"])
            self.assertIn("★前走高★新潟特注★", result.notes[0]["special_comments"])

            with closing(sqlite3.connect(db_path)) as db:
                db.execute("UPDATE history SET race_id='2026111505010101',surface='芝',"
                           "finish_position=9,r_level='高★'")
                db.commit()
            result = analyze_csv(pd.DataFrame([main_row("福島", "03", condition="未勝利")]), {}, {}, history_db_path=db_path)
            self.assertIn("★ローカル前走高★特注★", result.frame.iloc[0]["総合評価・コース相性判定"])
            self.assertIn("★ローカル前走高★特注★", result.notes[0]["special_comments"])


if __name__ == "__main__":
    unittest.main()
