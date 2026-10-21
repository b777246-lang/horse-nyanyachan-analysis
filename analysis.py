"""生データから指数評価・コース相性を計算する。HTMLは生成しない。"""
import re
from dataclasses import dataclass, field
import pandas as pd
from config import DEFAULT_SETTINGS
from signals import DEFAULT_REGISTRY
from data_loader import jockey_from_main_row, normalize_main_frame
from values import parse_racetrack
from legacy_recommendations import evaluate_legacy, get_course_compatibility
from recommendation_composition import RecommendationParts, compose_compatible_recommendation

@dataclass
class AnalysisBatch:
    frame: pd.DataFrame
    notes: dict
    recommendations: dict = field(default_factory=dict)

def analyze_csv(df, course_stats, ext_comment_dict, *, settings=DEFAULT_SETTINGS, registry=DEFAULT_REGISTRY):
    df = normalize_main_frame(df)
    df["arms_val"] = pd.to_numeric(df['arms'], errors="coerce").fillna(0)
    df["arms2_val"] = pd.to_numeric(df['arms2'], errors="coerce").fillna(0)
    df["tua_val"] = pd.to_numeric(df['TUA'], errors="coerce").fillna(0)
    df["S_val"] = pd.to_numeric(df['S'], errors="coerce").fillna(0)
    df["F_val"] = pd.to_numeric(df['F'], errors="coerce").fillna(0)
    df["finish_up_val"] = pd.to_numeric(df['fup'], errors="coerce").fillna(0)

    df["race_group"] = df.apply(
        lambda r: f"{r.get('race', '')}_{r.get('condition', '')}_{r.get('surface', '')}_{r.get('distance', '')}",
        axis=1,
    )

    df["arms_rank"] = df.groupby("race_group")["arms_val"].rank(
        ascending=False, method="min"
    )
    df["arms2_rank"] = df.groupby("race_group")["arms2_val"].rank(
        ascending=False, method="min"
    )
    df["tua_rank"] = df.groupby("race_group")["tua_val"].rank(
        ascending=False, method="min"
    )
    df["S_rank"] = df.groupby("race_group")["S_val"].rank(
        ascending=False, method="min"
    )
    df["F_rank"] = df.groupby("race_group")["F_val"].rank(
        ascending=False, method="min"
    )
    df["finish_up_rank"] = (
        df.groupby("race_group")["finish_up_val"]
        .rank(ascending=False, method="min")
        .fillna(99)
    )
    df["finish_up_count"] = df.groupby(["race_group", "finish_up_val"])[
        "finish_up_val"
    ].transform("count")

    notes = {}
    recommendations = {}
    raw_data_list = []

    for original_index, row in df.iterrows():
        race_raw = str(row.get('race', ""))
        cond_name = str(row.get('condition', ""))
        surface = str(row.get('surface', ""))
        try:
            distance = int(row.get('distance', 0))
        except ValueError:
            distance = 0

        cond_raw = f"{cond_name} {surface}{distance}"
        header_text = f"{cond_name} {surface}{distance}m"
        venue_name = parse_racetrack(race_raw)
        race_m = re.match(r"^\D+?(\d+)$", race_raw.strip())
        race_no = int(race_m.group(1)) if race_m else 0
        wakuban_raw = row.get('frame', "")
        wakuban = (
            int(wakuban_raw)
            if pd.notna(wakuban_raw) and str(wakuban_raw).isdigit()
            else 0
        )
        umaban = str(row.get('horse_no', ""))

        push_mark_raw = row.get('push_mark', "")
        push_mark = str(push_mark_raw).strip() if pd.notna(push_mark_raw) else ""
        if push_mark.lower() == "nan":
            push_mark = ""


        name = str(row.get('horse_name', "")).strip()

        # ヘッダーなしCSV:
        # CSVの列位置はdata_loaderで正規化する。新形式はID→血統登録番号→騎手。
        kol_raw = row.get('kol_odds', "")
        kol_odds = pd.to_numeric(kol_raw, errors="coerce")

        race_id_raw = row.get('race_id', "")
        if pd.isna(race_id_raw):
            race_id = ""
        else:
            race_id = str(race_id_raw).strip()
            # pandasで数値として読まれた場合の末尾 .0 を除去
            if re.fullmatch(r"\d+\.0", race_id):
                race_id = race_id[:-2]
        if not re.fullmatch(r"\d{18}", race_id):
            race_id = ""

        arms = row["arms_val"]
        arms2 = row["arms2_val"]
        tua = row["tua_val"]
        s_idx = row["S_val"]
        f_idx = row["F_val"]
        finish_up = row["finish_up_val"]

        arms_rank = int(row["arms_rank"])
        arms2_rank = int(row["arms2_rank"])
        tua_rank = int(row["tua_rank"])
        s_rank = int(row["S_rank"])
        f_rank = int(row["F_rank"])
        finish_up_count = row["finish_up_count"]
        finish_up_rank = int(row["finish_up_rank"])

        context = {
            "race": race_raw, "venue": venue_name, "condition": cond_name, "surface": surface,
            "distance": distance, "frame": wakuban,
            "arms": arms, "arms2": arms2, "TUA": tua, "S": s_idx, "F": f_idx,
            "arms_rank": arms_rank, "arms2_rank": arms2_rank, "TUA_rank": tua_rank,
            "S_rank": s_rank, "F_rank": f_rank, "fup": finish_up,
            "fup_rank": finish_up_rank, "fup_count": finish_up_count,
            "horse_name": name, "horse_no": umaban, "race_id": race_id,
            "jockey": jockey_from_main_row(row), "kol_odds": kol_odds,
            "horse_id": str(row.get('horse_id', '')).strip() if pd.notna(row.get('horse_id', '')) else '',
        }
        # 両エンジンは共通入力だけを参照し、相互に呼び出さない。
        legacy_result = evaluate_legacy(context, course_stats, settings=settings)
        special_matches = registry.evaluate(context, settings, stage="pre")
        parts = RecommendationParts(legacy_result, special_matches)
        recommendations[original_index] = parts
        compatible = compose_compatible_recommendation(parts, settings=settings)
        score, eval_text_raw = compatible.score, compatible.evaluation
        special_comments = tuple(match.comment for match in special_matches if match.comment)

        evaluation_before_external = eval_text_raw
        if ext_comment_dict and name in ext_comment_dict:
            ext_c = ext_comment_dict[name]
            eval_text_raw = f"{ext_c} ▼ {eval_text_raw}" if eval_text_raw else ext_c

        eval_text_csv = eval_text_raw

        notes[original_index] = {
            "evaluation": evaluation_before_external,
            "external_comment": ext_comment_dict.get(name, ""),
            "special_comments": special_comments,
            "ranks": {"arms": arms_rank, "arms2": arms2_rank, "TUA": tua_rank,
                      "S": s_rank, "F": f_rank, "厩舎F-UP2": finish_up_rank},
        }

        raw_data_list.append({
            "original_index": original_index,
            "score": score,
            "venue": venue_name,
            "race_no": race_no,
            "header": header_text,
            "レース": race_raw,
            "条件": cond_raw,
            "枠番": wakuban,
            "馬番": umaban,
            "推印": push_mark,
            "馬名": name,
            "KOLオッズ": "" if pd.isna(kol_odds) else float(kol_odds),
            "実オッズ": "",
            "オッズ差": "",
            "人気": "",
            "レースID": race_id,
            "騎手": jockey_from_main_row(row),
            "乖離率(%)": "",
            "arms": arms,
            "arms2": arms2,
            "TUA": tua,
            "S": s_idx,
            "F": f_idx,
            "厩舎F-UP2": finish_up,
            "総合評価・コース相性判定": eval_text_csv,
        })
        if df.attrs.get('has_age'):
            raw_data_list[-1]['age'] = row.get('age', '')
        if df.attrs.get('has_horse_id'):
            raw_data_list[-1]['血統登録番号'] = context['horse_id']

    return AnalysisBatch(pd.DataFrame(raw_data_list), notes, recommendations)
