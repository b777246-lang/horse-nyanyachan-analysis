"""生データから指数評価・コース相性を計算する。HTMLは生成しない。"""
import re
from dataclasses import dataclass
import pandas as pd
from config import DEFAULT_SETTINGS
from signals import DEFAULT_REGISTRY
from data_loader import jockey_from_main_row, normalize_main_frame

@dataclass
class AnalysisBatch:
    frame: pd.DataFrame
    notes: dict

def parse_racetrack(race_str):
    race_str = str(race_str).strip()
    if not race_str:
        return ""
    char = race_str[0]
    mapping = {
        "東": "東京",
        "中": "中山",
        "福": "福島",
        "京": "京都",
        "阪": "阪神",
        "新": "新潟",
        "札": "札幌",
        "函": "函館",
        "小": "小倉",
        "名": "中京",
    }
    return mapping.get(char, char)

def get_course_compatibility(
    race_col, surface, distance, index_type, rank, stats
):
    target_filename = f"{index_type}指数{rank}位のコース別成績.csv"
    df = stats.get(target_filename)
    if df is not None:
        track_name = parse_racetrack(race_col)
        for idx, row in df.iterrows():
            c_target = str(row.get("コース", ""))
            if track_name and track_name in c_target:
                if surface in c_target and str(distance) in c_target:
                    return {
                        "course": c_target,
                        "win_rate": str(row.get("勝率", "0%")),
                        "place_rate": str(row.get("複勝率", "0%")),
                        "win_ret": str(row.get("単勝回収値", "0")),
                        "place_ret": str(row.get("複勝回収値", "0")),
                    }
    return None


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

        highlights = []
        score = 0

        if arms >= settings.index.arms:
            highlights.append(f"arms:{arms}")
            score += settings.index.standard_points
        if arms2 >= settings.index.arms2:
            highlights.append(f"arms2:{arms2}")
            score += settings.index.standard_points
        if tua >= settings.index.tua_strong:
            highlights.append(f"TUA:{tua}(最強)")
            score += settings.index.strong_points
        elif tua >= settings.index.tua_candidate:
            highlights.append(f"TUA:{tua}(有力)")
            score += settings.index.standard_points
        if s_idx >= settings.index.s_strong:
            highlights.append(f"S:{s_idx}(最強)")
            score += settings.index.strong_points
        elif s_idx >= settings.index.s_candidate:
            highlights.append(f"S:{s_idx}(有力)")
            score += settings.index.standard_points
        if f_idx >= settings.index.f_strong:
            highlights.append(f"F:{f_idx}(鉄板)")
            score += settings.index.strong_points
        elif f_idx >= settings.index.f_candidate:
            highlights.append(f"F:{f_idx}(軸)")
            score += settings.index.standard_points

        if finish_up_count < settings.index.training_count_max and (finish_up >= settings.index.training_min or finish_up_rank <= settings.index.training_rank_max):
            highlights.append("調教良")
            score += settings.index.standard_points

        course_compat_text = ""
        is_good_compatibility = False
        is_triple_1st = False

        if arms_rank == 1 and arms2_rank == 1 and tua_rank == 1:
            if "triple" in course_stats:
                df_triple = course_stats["triple"]
                track_name = parse_racetrack(race_raw)
                for _, t_row in df_triple.iterrows():
                    c_target = str(t_row.get("コース", ""))
                    if track_name and track_name in c_target:
                        if surface in c_target and str(distance) in c_target:
                            try:
                                win_ret_val = float(
                                    str(t_row.get("単勝回収値", "0"))
                                    .replace("%", "")
                                    .strip()
                                )
                            except ValueError:
                                win_ret_val = 0.0
                            try:
                                place_rate_val = float(
                                    str(t_row.get("複勝率", "0%"))
                                    .replace("%", "")
                                    .strip()
                                )
                            except ValueError:
                                place_rate_val = 0.0

                            if win_ret_val >= settings.course.win_return_min or place_rate_val >= settings.course.place_rate_min:
                                is_triple_1st = True
                                course_compat_text = f"👑 【★トリプル１位★: {c_target} 複勝率{t_row.get('複勝率', '0%')}/単回{t_row.get('単勝回収値', '0')}】"
                                score += settings.course.triple_score
                            break

        if not is_triple_1st:
            for t, rnk in [
                ("arms", arms_rank),
                ("arms2", arms2_rank),
                ("TUA", tua_rank),
                ("S", s_rank),
                ("F", f_rank),
            ]:
                if rnk <= settings.course.rank_max:
                    compat = get_course_compatibility(
                        race_raw, surface, distance, t, rnk, course_stats
                    )
                    if compat:
                        try:
                            win_ret_val = float(
                                compat["win_ret"].replace("%", "").strip()
                            )
                        except ValueError:
                            win_ret_val = 0.0
                        try:
                            place_rate_val = float(
                                compat["place_rate"].replace("%", "").strip()
                            )
                        except ValueError:
                            place_rate_val = 0.0

                        if win_ret_val >= settings.course.win_return_min or place_rate_val >= settings.course.place_rate_min:
                            is_good_compatibility = True
                            course_compat_text = f"🎯 【{t}{rnk}位: {compat['course']} 複勝率{compat['place_rate']}/単回{compat['win_ret']}】(好相性)"
                            score += settings.course.single_score
                            break

        context = {
            "venue": venue_name, "condition": cond_name, "surface": surface,
            "distance": distance, "frame": wakuban,
            "arms": arms, "arms2": arms2, "TUA": tua, "S": s_idx, "F": f_idx,
            "arms_rank": arms_rank, "arms2_rank": arms2_rank, "TUA_rank": tua_rank,
            "S_rank": s_rank, "F_rank": f_rank, "fup": finish_up,
            "fup_rank": finish_up_rank, "fup_count": finish_up_count,
            "horse_name": name, "horse_no": umaban, "race_id": race_id,
            "jockey": jockey_from_main_row(row), "kol_odds": kol_odds,
            "horse_id": str(row.get('horse_id', '')).strip() if pd.notna(row.get('horse_id', '')) else '',
        }
        special_matches = registry.evaluate(context, settings, stage="pre")
        special_comments = tuple(match.comment for match in special_matches if match.comment)
        score += sum(match.score for match in special_matches)
        eval_parts_raw = list(special_comments)
        if highlights:
            eval_parts_raw.extend(highlights)
        if course_compat_text:
            eval_parts_raw.append(course_compat_text)

        if not eval_parts_raw:
            eval_text_raw = ""
        else:
            eval_text_raw = " / ".join(eval_parts_raw)
            if is_triple_1st:
                eval_text_raw = "🌟 【★トリプル１位★推奨】 " + eval_text_raw
            elif score >= settings.index.axis_score:
                eval_text_raw = "🔥 【軸馬推奨】 " + eval_text_raw
            elif score >= settings.index.candidate_score:
                eval_text_raw = "⭐ 【有力候補】 " + eval_text_raw
            elif is_good_compatibility or special_matches:
                eval_text_raw = "🎯 【注目条件】 " + eval_text_raw

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
        if df.attrs.get('has_horse_id'):
            raw_data_list[-1]['血統登録番号'] = context['horse_id']

    return AnalysisBatch(pd.DataFrame(raw_data_list), notes)
