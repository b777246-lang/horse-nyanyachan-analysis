"""旧推奨専用の指数評価・調教評価・コース相性・ラベル。特注条件は参照しない。"""
from dataclasses import dataclass

from config import DEFAULT_SETTINGS
from values import parse_racetrack


@dataclass(frozen=True)
class LegacyRecommendation:
    score: int
    highlights: tuple[str, ...]
    course_comment: str
    is_triple_1st: bool
    is_good_compatibility: bool


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


def evaluate_legacy(context, course_stats, *, settings=DEFAULT_SETTINGS):
    """共通処理で計算済みの指数・順位を受け取り、旧推奨だけを評価する。"""
    race_raw = context['race']
    surface, distance = context['surface'], context['distance']
    arms, arms2, tua = context['arms'], context['arms2'], context['TUA']
    s_idx, f_idx, finish_up = context['S'], context['F'], context['fup']
    arms_rank, arms2_rank, tua_rank = context['arms_rank'], context['arms2_rank'], context['TUA_rank']
    s_rank, f_rank = context['S_rank'], context['F_rank']
    finish_up_rank, finish_up_count = context['fup_rank'], context['fup_count']
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

    return LegacyRecommendation(score, tuple(highlights), course_compat_text,
                                is_triple_1st, is_good_compatibility)


def recommendation_label(result, total_score, *, additional_attention=False, settings=DEFAULT_SETTINGS):
    """合成側から渡された互換スコアで従来の優先順位を再現する。"""
    if result.is_triple_1st:
        return "🌟 【★トリプル１位★推奨】 "
    if total_score >= settings.index.axis_score:
        return "🔥 【軸馬推奨】 "
    if total_score >= settings.index.candidate_score:
        return "⭐ 【有力候補】 "
    if result.is_good_compatibility or additional_attention:
        return "🎯 【注目条件】 "
    return ""
