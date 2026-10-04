"""全レース更新とキャッシュ反映。UIとJRA通信を引数として受け取る。"""
import re
from dataclasses import dataclass
import pandas as pd
from signals import kol_divergence

def build_race_targets(frame, date_text):
    place_code_to_name = {
        "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
        "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
    }
    race_targets = []
    for (venue, race_no), race_frame in frame.groupby(["venue", "race_no"], sort=False):
        ids = [str(v).strip() for v in race_frame["レースID"]
               if re.fullmatch(r"\d{18}", str(v).strip())]
        prefixes = sorted({rid[:16] for rid in ids})
        target_date = re.sub(r"\D", "", date_text)
        error = ""
        if len(prefixes) > 1:
            error = "複数の18桁レースIDが混在しています。CSVを確認してください。"
        elif prefixes:
            prefix = prefixes[0]
            target_date = prefix[:8]
            if (place_code_to_name.get(prefix[8:10]) != venue
                    or int(prefix[14:16]) != int(race_no)):
                error = "18桁レースIDと開催・Rが一致しません。CSVを確認してください。"
        if not re.fullmatch(r"\d{8}", target_date):
            error = "開催日を取得できません。レースIDまたはCSVファイル名を確認してください。"
        odds_key = f"{target_date}_{venue}_{int(race_no)}"
        race_targets.append((venue, int(race_no), target_date, odds_key, error))

    return race_targets

def cached_odds_by_race(race_targets, cache):
    odds_by_race = {}
    for venue, race_no, target_date, odds_key, error in race_targets:
        if error:
            continue
        cached_odds = cache.get(odds_key, [])
        if cached_odds:
            odds_by_race[(venue, race_no)] = {
                str(int(item["horse_no"])): item for item in cached_odds
            }

    return odds_by_race

def apply_odds(frame, odds_by_race):
    frame = frame.copy()

    for col in ("KOLオッズ", "実オッズ", "オッズ差", "人気", "乖離率(%)"):
        if col not in frame.columns:
            frame[col] = ""
        frame[col] = frame[col].astype("object")

    for idx, row in frame.iterrows():
        horse_no_text = str(row.get("馬番", "")).strip()
        try:
            horse_no_text = str(int(float(horse_no_text)))
        except (ValueError, TypeError):
            pass

        frame.at[idx, "乖離率(%)"] = ""
        race_key = (str(row.get("venue", "")), int(row["race_no"]))
        item = odds_by_race.get(race_key, {}).get(horse_no_text)
        if not item:
            continue

        odds_value = item.get("jra_odds", "")
        popularity_value = item.get("popularity", "")

        frame.at[idx, "実オッズ"] = (
            "" if odds_value is None else float(odds_value)
        )
        frame.at[idx, "人気"] = (
            "" if popularity_value is None else popularity_value
        )

        divergence = kol_divergence(row.get("KOLオッズ", ""), odds_value)
        frame.at[idx, "乖離率(%)"] = (
            "" if divergence is None else float(divergence)
        )

        kol_value = pd.to_numeric(
            row.get("KOLオッズ", ""), errors="coerce"
        )
        if pd.notna(kol_value) and odds_value not in ("", None):
            # 指定式: 実オッズ - KOLオッズ
            frame.at[idx, "オッズ差"] = round(
                float(odds_value) - float(kol_value), 1
            )
        else:
            frame.at[idx, "オッズ差"] = ""

    return frame


@dataclass(frozen=True)
class UpdateSummary:
    success_count: int
    failures: tuple[str, ...]
    urls: dict[str, str]


def update_all_odds(targets, cache, fetch, on_progress):
    """成功したレースだけ置き換える。失敗しても残りのレースを続行する。"""
    failures = []
    urls = {}
    success_count = 0
    for position, (venue, race_no, date, key, error) in enumerate(targets):
        label = f"{venue}{race_no}R"
        on_progress(position / len(targets), f"{label}を取得中")
        try:
            if error:
                raise ValueError(error)
            rows, url = fetch(date, venue, race_no)
            if not rows:
                raise RuntimeError("単勝オッズを1頭も取得できませんでした。")
            cache[key] = rows
            urls[key] = url
            success_count += 1
        except Exception as exc:
            failures.append(f"{label}：{exc}")
        on_progress((position + 1) / len(targets), f"{position + 1}/{len(targets)}レース完了")
    return UpdateSummary(success_count, tuple(failures), urls)
