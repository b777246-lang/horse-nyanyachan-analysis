import glob
import os
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from html import escape
import pandas as pd
import streamlit as st

try:
    from jra_odds import fetch_jra_win_odds_auto
except ImportError:
    fetch_jra_win_odds_auto = None


# 添付 jockey_top3rate_over0.25.csv の3着内率0.25以上の28名。
KOL_SELECTED_JOCKEYS = {
    "C.ルメール", "戸崎圭太", "松山弘平", "横山武史", "坂井瑠星",
    "川田将雅", "丹内祐次", "岩田望来", "横山和生", "高杉吏麒",
    "北村友一", "武豊", "団野大成", "鮫島克駿", "菅原明良",
    "荻野極", "三浦皇成", "西村淳也", "藤岡佑介", "岩田康誠",
    "横山典弘", "D.レーン", "池添謙一", "C.デムーロ", "J.モレイラ",
    "丸山元気", "浜中俊", "R.キング",
}
KOL_JOCKEY_ALIASES = {
    "ルメール": "C.ルメール", "レーン": "D.レーン",
    "C.デム": "C.デムーロ", "モレイラ": "J.モレイラ", "キング": "R.キング",
}

# 添付 wakuban_colors.csv の枠番別背景色。
WAKUBAN_COLORS = {
    1: "#FEFEFE", 2: "#222222", 3: "#CA4943", 4: "#3653A3",
    5: "#E0CB56", 6: "#6DAD57", 7: "#D28D3F", 8: "#CD687A",
}


def normalize_jockey(value):
    if pd.isna(value):
        return ""
    name = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value)))
    return KOL_JOCKEY_ALIASES.get(name, name)


def decimal_value(value):
    try:
        number = Decimal(unicodedata.normalize("NFKC", str(value)).strip())
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def kol_divergence(kol_odds, actual_odds):
    kol, actual = decimal_value(kol_odds), decimal_value(actual_odds)
    if kol is None or actual is None or kol <= 0 or actual <= 0:
        return None
    return (actual - kol) / kol * 100


def kol_alert_matches(kol_odds, actual_odds, popularity, jockey):
    kol, actual, rank = map(decimal_value, (kol_odds, actual_odds, popularity))
    return (
        kol is not None and actual is not None and rank is not None
        and 0 < kol < 50 and actual > 0
        # 150～450%を丸めず判定。実オッズはKOLの2.5～5.5倍。
        and kol * 5 <= actual * 2 <= kol * 11
        and rank >= 5 and rank == rank.to_integral_value()
        and normalize_jockey(jockey) in KOL_SELECTED_JOCKEYS
    )


def jockey_from_main_row(row):
    # ヘッダーなし元CSV: 16列目=レースID、17列目=騎手。
    value = row.get(16, "")
    return "" if pd.isna(value) else str(value).strip()


st.set_page_config(
    page_title="競馬指数 総合分析Webアプリケーション", layout="wide"
)

# --- セッション状態の初期化 ---
if "sort_mode" not in st.session_state:
    st.session_state.sort_mode = "初期配列"

if "jra_odds_cache" not in st.session_state:
    st.session_state.jra_odds_cache = {}


# --- デスクトップ版を参考にした総合評価用のクレンジング関数 ---
def clean_eval_text_for_target(val):
    if not isinstance(val, str):
        val = str(val) if pd.notna(val) else ""
    
    # 絵文字パターンの定義
    emoji_pattern = re.compile(
        "[\U00010000-\U0010ffff\U00002600-\U000027ff]", flags=re.UNICODE
    )
    val = emoji_pattern.sub(r"", val)
    
    # 指定された絵文字や特殊記号、★を削除
    val = (
        val.replace("🔥", "")
        .replace("🎯", "")
        .replace("⭐", "")
        .replace("🌟", "")
        .replace("👑", "")
        .replace("★", "")
    )
    
    # 制御文字の削除
    val = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", val)
    # カンマやダブルクォーテーションの除去
    val = val.replace(",", "").replace('"', "")
    # スペース（半角・全角）を完全に削除
    val = re.sub(r"[\s ]+", "", val)
    
    return val.strip()


# --- ★に挟まれた特注文言を赤字にするHTML変換関数 ---
def format_special_tags_html(text):
    if not text:
        return ""
    pattern = re.compile(r"(★[^★]+★)")
    return pattern.sub(r'<span style="color: #ff4b4b; font-weight: bold;">\1</span>', text)


# --- カスタムCSS ---
st.markdown(
    """
    <style>
    .main .block-container {
        max-width: 100% !important;
        padding-left: 0.5rem;
        padding-right: 0.5rem;
        padding-top: 1rem;
    }
    .table-container {
        width: 100%;
        max-height: 80vh;
        overflow-y: auto;
        overflow-x: hidden;
        border: 1px solid #ddd;
        border-radius: 6px;
        margin-bottom: 20px;
        background-color: white;
    }
    .custom-horse-table {
        width: 100% !important;
        table-layout: fixed;
        border-collapse: collapse;
        font-size: 9.5px;
        background-color: white;
        color: #31333F;
    }
    .custom-horse-table th, .custom-horse-table td {
        border: 1px solid #e0e0e0;
        padding: 4px 3px;
        text-align: center;
        white-space: nowrap;
        overflow: hidden;
        box-sizing: border-box;
    }
    .custom-horse-table th {
        background-color: #f0f2f6;
        position: sticky;
        top: 0;
        z-index: 10;
        font-weight: 600;
        line-height: 1.15;
    }

    /* 17列を画面幅100%に収める */
    .custom-horse-table th:nth-child(1),  .custom-horse-table td:nth-child(1)  { width: 3.5%; }
    .custom-horse-table th:nth-child(2),  .custom-horse-table td:nth-child(2)  { width: 6.0%; }
    .custom-horse-table th:nth-child(3),  .custom-horse-table td:nth-child(3)  { width: 3.0%; }
    .custom-horse-table th:nth-child(4),  .custom-horse-table td:nth-child(4)  { width: 3.0%; }
    .custom-horse-table th:nth-child(5),  .custom-horse-table td:nth-child(5)  { width: 3.5%; }
    .custom-horse-table th:nth-child(6),  .custom-horse-table td:nth-child(6)  { width: 10.0%; }
    .custom-horse-table th:nth-child(7),  .custom-horse-table td:nth-child(7)  { width: 5.0%; }
    .custom-horse-table th:nth-child(8),  .custom-horse-table td:nth-child(8)  { width: 3.5%; }
    .custom-horse-table th:nth-child(9),  .custom-horse-table td:nth-child(9)  { width: 3.2%; }
    .custom-horse-table th:nth-child(10), .custom-horse-table td:nth-child(10) { width: 3.4%; }
    .custom-horse-table th:nth-child(11), .custom-horse-table td:nth-child(11) { width: 3.4%; }
    .custom-horse-table th:nth-child(12), .custom-horse-table td:nth-child(12) { width: 2.8%; }
    .custom-horse-table th:nth-child(13), .custom-horse-table td:nth-child(13) { width: 2.8%; }
    .custom-horse-table th:nth-child(14), .custom-horse-table td:nth-child(14) { width: 5.5%; }
    .custom-horse-table th:nth-child(15), .custom-horse-table td:nth-child(15) { width: 30.0%; }
    .custom-horse-table th:nth-child(16), .custom-horse-table td:nth-child(16) { width: 5.5%; }
    .custom-horse-table th:nth-child(17), .custom-horse-table td:nth-child(17) { width: 5.5%; }

    /* 長文の総合評価だけ折り返して全内容を表示 */
    .custom-horse-table th:nth-child(15),
    .custom-horse-table td:nth-child(15) {
        white-space: normal !important;
        overflow: visible !important;
        overflow-wrap: anywhere;
        text-align: left !important;
        line-height: 1.25;
    }

    /* KOL・乖離率は小さくても読みやすく */
    .custom-horse-table th:nth-child(16),
    .custom-horse-table th:nth-child(17) {
        white-space: normal !important;
    }
    .rank-1 { background-color: #fff2b2 !important; font-weight: bold; }
    .rank-2 { background-color: #e6f2ff !important; }
    .rank-3 { background-color: #d4edda !important; }
    .push-mark-red { color: #ff4b4b !important; font-weight: bold; }
    .odds-gap-alert {
        background-color: #ffe08a !important;
        color: #b42318 !important;
        font-weight: 800 !important;
    }
    .race-header {
        background: #0a1128;
        color: #ffffff;
        border: 1px solid #1e90c8;
        border-radius: 6px;
        padding: 10px 16px;
        margin: 8px 0 12px 0;
        font-size: 18px;
        font-weight: 600;
    }
    .race-header .sub { color: #8fb8d8; font-size: 12px; font-weight: 400; margin-left: 12px; }

    @media screen and (max-width: 1200px) {
        .custom-horse-table { font-size: 8px !important; }
        .custom-horse-table th, .custom-horse-table td { padding: 3px 2px !important; }
    }
    @media screen and (max-width: 768px) {
        .main .block-container {
            padding-left: 0.15rem !important;
            padding-right: 0.15rem !important;
        }
        .custom-horse-table { font-size: 6.5px !important; }
        .custom-horse-table th, .custom-horse-table td {
            padding: 2px 1px !important;
            letter-spacing: -0.15px;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🏇 競馬指数 総合分析Webアプリケーション")


@st.cache_data
def load_course_data():
    course_stats = {}
    try:
        df = pd.read_csv("arms及びarms2及びTUA指数の全てが一位.csv", encoding="cp932")
        course_stats["triple"] = df
    except Exception:
        pass

    csv_files = glob.glob("*指数*位のコース別成績.csv")
    for filepath in csv_files:
        filename = os.path.basename(filepath)
        try:
            df = pd.read_csv(filename, encoding="cp932")
            course_stats[filename] = df
        except Exception:
            pass
    return course_stats


course_stats = load_course_data()


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


# --- サイドバー ---
st.sidebar.header("📂 ファイル読み込み")
uploaded_file = st.sidebar.file_uploader(
    "メイン指数CSVファイルを選択（上書き用）", type=["csv"]
)
uploaded_ext_comment = st.sidebar.file_uploader(
    "💬 外部コメントCSVを選択（任意）", type=["csv"]
)


df = None
source_name = ""
if uploaded_file is not None:
    source_name = uploaded_file.name
    try:
        df = pd.read_csv(uploaded_file, encoding="cp932", header=None, dtype=str)
    except Exception:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file, encoding="utf-8", header=None, dtype=str)
    st.sidebar.success("アップロードされたファイルを読み込みました")
else:
    pattern = re.compile(r"^\d{8}\.csv$")
    matched_files = [f for f in os.listdir(".") if pattern.match(f)]
    if matched_files:
        default_main_csv = sorted(matched_files)[-1]
        source_name = default_main_csv
        try:
            df = pd.read_csv(default_main_csv, encoding="cp932", header=None, dtype=str)
            st.sidebar.info(f"📌 自動検出: {default_main_csv} を読み込んでいます")
        except Exception:
            df = pd.read_csv(default_main_csv, encoding="utf-8", header=None, dtype=str)
            st.sidebar.info(f"📌 自動検出: {default_main_csv} を読み込んでいます")
    else:
        st.sidebar.info("左側のサイドバーから指数CSVファイルをアップロードしてください。")

ext_comment_dict = {}
if uploaded_ext_comment is not None:
    ext_file_to_read = uploaded_ext_comment
else:
    ext_pattern = re.compile(r"^\d{8}comment\.csv$")
    matched_ext_files = [f for f in os.listdir(".") if ext_pattern.match(f)]
    ext_file_to_read = sorted(matched_ext_files)[-1] if matched_ext_files else None

if ext_file_to_read is not None:
    try:
        df_ext = pd.read_csv(ext_file_to_read, encoding="cp932", header=None)
        for _, row in df_ext.iterrows():
            vals = [str(v).strip() for v in row.values if pd.notna(v)]
            if len(vals) >= 6:
                h_name, c_text = vals[2], vals[5]
                if h_name and c_text:
                    ext_comment_dict[h_name] = c_text
    except Exception:
        pass

if df is not None:
    df["arms_val"] = pd.to_numeric(df.iloc[:, 8], errors="coerce").fillna(0)
    df["arms2_val"] = pd.to_numeric(df.iloc[:, 9], errors="coerce").fillna(0)
    df["tua_val"] = pd.to_numeric(df.iloc[:, 10], errors="coerce").fillna(0)
    df["S_val"] = pd.to_numeric(df.iloc[:, 11], errors="coerce").fillna(0)
    df["F_val"] = pd.to_numeric(df.iloc[:, 12], errors="coerce").fillna(0)
    df["finish_up_val"] = pd.to_numeric(df.iloc[:, 13], errors="coerce").fillna(0)

    df["race_group"] = df.apply(
        lambda r: f"{r.get(0, '')}_{r.get(1, '')}_{r.get(2, '')}_{r.get(3, '')}",
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

    export_data_list = []
    raw_data_list = []

    for original_index, row in df.iterrows():
        race_raw = str(row.get(0, ""))
        cond_name = str(row.get(1, ""))
        surface = str(row.get(2, ""))
        try:
            distance = int(row.get(3, 0))
        except ValueError:
            distance = 0

        cond_raw = f"{cond_name} {surface}{distance}"
        header_text = f"{cond_name} {surface}{distance}m"
        venue_name = parse_racetrack(race_raw)
        race_m = re.match(r"^\D+?(\d+)$", race_raw.strip())
        race_no = int(race_m.group(1)) if race_m else 0
        wakuban_raw = row.get(4, "")
        wakuban = (
            int(wakuban_raw)
            if pd.notna(wakuban_raw) and str(wakuban_raw).isdigit()
            else 0
        )
        umaban = str(row.get(5, ""))
        
        push_mark_raw = row.get(6, "")
        push_mark = str(push_mark_raw).strip() if pd.notna(push_mark_raw) else ""
        if push_mark.lower() == "nan":
            push_mark = ""

        if push_mark == "推":
            push_mark_html = f'<span class="push-mark-red">{push_mark}</span>'
        else:
            push_mark_html = push_mark

        name = str(row.get(7, "")).strip()

        # ヘッダーなしCSV:
        # 15列目 = KOLオッズ / 16列目 = TARGET 18桁レースID / 17列目 = 騎手
        kol_raw = row.get(14, "")
        kol_odds = pd.to_numeric(kol_raw, errors="coerce")

        race_id_raw = row.get(15, "")
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

        if arms >= 110:
            highlights.append(f"arms:{arms}")
            score += 1
        if arms2 >= 120:
            highlights.append(f"arms2:{arms2}")
            score += 1
        if tua >= 220:
            highlights.append(f"TUA:{tua}(最強)")
            score += 2
        elif tua >= 200:
            highlights.append(f"TUA:{tua}(有力)")
            score += 1
        if s_idx >= 60:
            highlights.append(f"S:{s_idx}(最強)")
            score += 2
        elif s_idx >= 55:
            highlights.append(f"S:{s_idx}(有力)")
            score += 1
        if f_idx >= 70:
            highlights.append(f"F:{f_idx}(鉄板)")
            score += 2
        elif f_idx >= 65:
            highlights.append(f"F:{f_idx}(軸)")
            score += 1

        if finish_up_count < 4 and (finish_up >= 5 or finish_up_rank <= 3):
            highlights.append("調教良")
            score += 1

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

                            if win_ret_val >= 100 or place_rate_val >= 60:
                                is_triple_1st = True
                                course_compat_text = f"👑 【★トリプル１位★: {c_target} 複勝率{t_row.get('複勝率', '0%')}/単回{t_row.get('単勝回収値', '0')}】"
                                score += 3
                            break

        if not is_triple_1st:
            for t, rnk in [
                ("arms", arms_rank),
                ("arms2", arms2_rank),
                ("TUA", tua_rank),
                ("S", s_rank),
                ("F", f_rank),
            ]:
                if rnk <= 3:
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

                        if win_ret_val >= 100 or place_rate_val >= 60:
                            is_good_compatibility = True
                            course_compat_text = f"🎯 【{t}{rnk}位: {compat['course']} 複勝率{compat['place_rate']}/単回{compat['win_ret']}】(好相性)"
                            score += 1
                            break

        is_dirt = surface == "ダ"
        is_not_maishin = "未勝利" not in cond_name and "新馬" not in cond_name
        suna_食_text = (
            "★特注砂食★"
            if (
                is_dirt
                and is_not_maishin
                and wakuban in [6, 7, 8]
                and s_rank == 1
            )
            else ""
        )
        if suna_食_text:
            score += 1

        f72_text = (
            "★特注F72★"
            if (is_dirt and wakuban == 8 and f_idx >= 72 and distance != 1200)
            else ""
        )
        if f72_text:
            score += 1

        track_name_parsed = parse_racetrack(race_raw)
        
        hanshin_1600_text = (
            "★阪神芝1600特注★"
            if (
                track_name_parsed == "阪神"
                and surface == "芝"
                and distance == 1600
                and arms_rank <= 3
                and f_idx >= 60
                and wakuban in [2, 4, 5, 6, 7]
            )
            else ""
        )
        if hanshin_1600_text:
            score += 1

        nakayama_1600_text = (
            "★中山芝1600特注★"
            if (
                track_name_parsed == "中山"
                and surface == "芝"
                and distance == 1600
                and wakuban in [1, 2, 3, 4]
                and s_rank == 1
            )
            else ""
        )
        if nakayama_1600_text:
            score += 1

        nakayama_2000_text = (
            "★中山芝2000特注★"
            if (
                track_name_parsed == "中山"
                and surface == "芝"
                and distance == 2000
                and wakuban in [1, 2, 3, 4, 8]
                and f_rank == 1
            )
            else ""
        )
        if nakayama_2000_text:
            score += 1

        tokyo_2000_text = (
            "★東京芝2000馬体重480㎏以上特注★"
            if (
                track_name_parsed == "東京"
                and surface == "芝"
                and distance == 2000
                and f_idx >= 70
            )
            else ""
        )
        if tokyo_2000_text:
            score += 1

        kyoto_1600_text = (
            "★京都芝1600特注★"
            if (
                track_name_parsed == "京都"
                and surface == "芝"
                and distance == 1600
                and arms >= 100
                and f_idx >= 65
            )
            else ""
        )
        if kyoto_1600_text:
            score += 1

        # --- 画面表示用（HTMLタグで赤字装飾） ---
        eval_parts_html = []
        if kyoto_1600_text:
            eval_parts_html.append(format_special_tags_html(kyoto_1600_text))
        if tokyo_2000_text:
            eval_parts_html.append(format_special_tags_html(tokyo_2000_text))
        if hanshin_1600_text:
            eval_parts_html.append(format_special_tags_html(hanshin_1600_text))
        if nakayama_2000_text:
            eval_parts_html.append(format_special_tags_html(nakayama_2000_text))
        if nakayama_1600_text:
            eval_parts_html.append(format_special_tags_html(nakayama_1600_text))
        if suna_食_text:
            eval_parts_html.append(format_special_tags_html(suna_食_text))
        if f72_text:
            eval_parts_html.append(format_special_tags_html(f72_text))
        if highlights:
            eval_parts_html.extend(highlights)
        if course_compat_text:
            eval_parts_html.append(course_compat_text)

        # --- CSV出力用（プレーンテキスト） ---
        eval_parts_raw = []
        if kyoto_1600_text:
            eval_parts_raw.append(kyoto_1600_text)
        if tokyo_2000_text:
            eval_parts_raw.append(tokyo_2000_text)
        if hanshin_1600_text:
            eval_parts_raw.append(hanshin_1600_text)
        if nakayama_2000_text:
            eval_parts_raw.append(nakayama_2000_text)
        if nakayama_1600_text:
            eval_parts_raw.append(nakayama_1600_text)
        if suna_食_text:
            eval_parts_raw.append(suna_食_text)
        if f72_text:
            eval_parts_raw.append(f72_text)
        if highlights:
            eval_parts_raw.extend(highlights)
        if course_compat_text:
            eval_parts_raw.append(course_compat_text)

        if not eval_parts_html:
            eval_text_html = ""
            eval_text_raw = ""
        else:
            eval_text_html = " / ".join(eval_parts_html)
            eval_text_raw = " / ".join(eval_parts_raw)
            if is_triple_1st:
                eval_text_html = "🌟 【★トリプル１位★推奨】 " + eval_text_html
                eval_text_raw = "🌟 【★トリプル１位★推奨】 " + eval_text_raw
            elif score >= 4:
                eval_text_html = "🔥 【軸馬推奨】 " + eval_text_html
                eval_text_raw = "🔥 【軸馬推奨】 " + eval_text_raw
            elif score >= 2:
                eval_text_html = "⭐ 【有力候補】 " + eval_text_html
                eval_text_raw = "⭐ 【有力候補】 " + eval_text_raw
            elif (
                is_good_compatibility
                or suna_食_text
                or f72_text
                or hanshin_1600_text
                or nakayama_1600_text
                or nakayama_2000_text
                or tokyo_2000_text
                or kyoto_1600_text
            ):
                eval_text_html = "🎯 【注目条件】 " + eval_text_html
                eval_text_raw = "🎯 【注目条件】 " + eval_text_raw

        if ext_comment_dict and name in ext_comment_dict:
            ext_c = ext_comment_dict[name]
            eval_text_html = f"{ext_c} ▼ {eval_text_html}" if eval_text_html else ext_c
            eval_text_raw = f"{ext_c} ▼ {eval_text_raw}" if eval_text_raw else ext_c

        eval_text_csv = clean_eval_text_for_target(eval_text_raw)

        def get_cell_html(val, rank):
            if rank == 1:
                return f'<td class="rank-1">{val}</td>'
            elif rank == 2:
                return f'<td class="rank-2">{val}</td>'
            elif rank == 3:
                return f'<td class="rank-3">{val}</td>'
            else:
                return f"<td>{val}</td>"

        export_data_list.append({
            "original_index": original_index,
            "score": score,
            "venue": venue_name,
            "race_no": race_no,
            "header": header_text,
            "レース": race_raw,
            "条件": cond_raw,
            "枠番": wakuban,
            "馬番": umaban,
            "推印": push_mark_html,
            "馬名": name,
            "KOLオッズ": "" if pd.isna(kol_odds) else float(kol_odds),
            "実オッズ": "",
            "オッズ差": "",
            "人気": "",
            "レースID": race_id,
            "騎手": jockey_from_main_row(row),
            "乖離率(%)": "",
            "arms": get_cell_html(arms, arms_rank),
            "arms2": get_cell_html(arms2, arms2_rank),
            "TUA": get_cell_html(tua, tua_rank),
            "S": get_cell_html(s_idx, s_rank),
            "F": get_cell_html(f_idx, f_rank),
            "厩舎F-UP2": get_cell_html(finish_up, finish_up_rank),
            "総合評価・コース相性判定": eval_text_html,
        })

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

    res_df = pd.DataFrame(export_data_list)
    raw_csv_df = pd.DataFrame(raw_data_list)

    st.success(f"ファイルを正常に読み込みました（全 {len(res_df)} 頭）")

    # --- ソート＆初期化コントロール UI ---
    st.subheader("📊 出走馬・指数一覧分析")

    st.write("▼ **表示順序の切り替え**")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        if st.button("🔥 評価点数順にソート"):
            st.session_state.sort_mode = "スコア順"
    with col_s2:
        if st.button("🔄 初期配列に戻す"):
            st.session_state.sort_mode = "初期配列"

    if st.session_state.sort_mode == "スコア順":
        res_df = res_df.sort_values(
            by=["score", "original_index"], ascending=[False, True]
        ).reset_index(drop=True)
        raw_csv_df = raw_csv_df.sort_values(
            by=["score", "original_index"], ascending=[False, True]
        ).reset_index(drop=True)
        st.info("📌 現在の表示: 評価点数（コース相性・推奨度）の高い順")
    else:
        res_df = res_df.sort_values(
            by="original_index", ascending=True
        ).reset_index(drop=True)
        raw_csv_df = raw_csv_df.sort_values(
            by="original_index", ascending=True
        ).reset_index(drop=True)

    def render_html_table(dataframe):
        html = ['<div class="table-container"><table class="custom-horse-table">']
        display_columns = [
            "レース",
            "条件",
            "枠番",
            "馬番",
            "推印",
            "馬名",
            "実オッズ",
            "人気",
            "arms",
            "arms2",
            "TUA",
            "S",
            "F",
            "厩舎F-UP2",
            "総合評価・コース相性判定",
            "KOLオッズ",
            "乖離率(%)",
        ]
        html.append("<thead><tr>")
        for col in display_columns:
            html.append(f"<th>{col}</th>")
        html.append("</tr></thead>")
        html.append("<tbody>")
        for _, row in dataframe.iterrows():
            html.append("<tr>")
            html.append(f"<td>{row['レース']}</td>")
            html.append(f"<td>{row['条件']}</td>")
            wakuban = decimal_value(row["枠番"])
            background = WAKUBAN_COLORS.get(wakuban)
            if background:
                foreground = "#FEFEFE" if wakuban in (2, 3, 4) else "#222222"
                html.append(
                    f'<td style="background-color: {background}; '
                    f'color: {foreground}; font-weight: bold;">{row["枠番"]}</td>'
                )
            else:
                html.append(f"<td>{row['枠番']}</td>")
            html.append(f"<td>{row['馬番']}</td>")
            html.append(f"<td>{row['推印']}</td>")
            html.append(f"<td>{row['馬名']}</td>")
            html.append(f"<td>{row.get('実オッズ', '')}</td>")
            html.append(f"<td>{row.get('人気', '')}</td>")
            html.append(str(row["arms"]))
            html.append(str(row["arms2"]))
            html.append(str(row["TUA"]))
            html.append(str(row["S"]))
            html.append(str(row["F"]))
            html.append(str(row["厩舎F-UP2"]))
            html.append(f"<td>{row['総合評価・コース相性判定']}</td>")

            html.append(f"<td>{row.get('KOLオッズ', '')}</td>")
            jockey = row.get("騎手", "")
            divergence = kol_divergence(
                row.get("KOLオッズ", ""), row.get("実オッズ", "")
            )
            alert = kol_alert_matches(
                row.get("KOLオッズ", ""), row.get("実オッズ", ""),
                row.get("人気", ""), jockey,
            )
            diff_class = ' class="odds-gap-alert"' if alert else ""
            diff_text = f"{divergence:+.1f}%" if divergence is not None else ""
            status = "条件合致" if alert else (
                "判定保留：騎手未取得" if not normalize_jockey(jockey)
                else "判定保留：オッズ・人気未取得"
                if divergence is None or decimal_value(row.get("人気", "")) is None
                else "条件未合致"
            )
            tooltip = escape(f"騎手：{jockey or '未取得'} / {status}", quote=True)
            html.append(f'<td{diff_class} title="{tooltip}">{diff_text}</td>')
            html.append("</tr>")
        html.append("</tbody></table></div>")
        return "".join(html)

    # --- 開催場・レース切り替え（TARGET風） ---
    def pick(label, options, key, fmt=str):
        if hasattr(st, "segmented_control"):
            sel = st.segmented_control(
                label,
                options,
                selection_mode="single",
                default=options[0],
                key=key,
                format_func=fmt,
            )
        else:
            sel = st.radio(
                label, options, horizontal=True, key=key, format_func=fmt
            )
        return sel if sel in options else options[0]

    venues = (
        res_df.sort_values("original_index")["venue"].drop_duplicates().tolist()
    )
    sel_venue = pick("開催", venues, key="sel_venue")

    venue_df = res_df[res_df["venue"] == sel_venue]
    race_nos = sorted(venue_df["race_no"].unique().tolist())
    race_options = race_nos + ["ALL"]
    sel_race = pick(
        "R",
        race_options,
        key=f"sel_race_{sel_venue}",
        fmt=lambda x: "全R" if x == "ALL" else f"{x}R",
    )

    m_date = re.search(r"(\d{4})(\d{2})(\d{2})", source_name)
    date_text = (
        f"{m_date.group(1)}/{m_date.group(2)}/{m_date.group(3)}"
        if m_date
        else ""
    )

    if sel_race == "ALL":
        view_df = venue_df
        title = f"{sel_venue} 全レース"
    else:
        view_df = venue_df[venue_df["race_no"] == sel_race]
        head = view_df["header"].iloc[0] if len(view_df) else ""
        title = f"{sel_venue} {sel_race}R　{head}"

    # --- JRA公式 全開催・全レースの単勝オッズ更新 ---
    place_code_to_name = {
        "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
        "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
    }
    race_targets = []
    for (venue, race_no), race_frame in res_df.groupby(["venue", "race_no"], sort=False):
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

    with st.expander("💴 JRA単勝オッズ", expanded=False):
        st.caption(f"CSV内の全開催・全{len(race_targets)}レースを更新します。")
        if st.button("🔄 オッズ更新", key="odds_update_all"):
            if fetch_jra_win_odds_auto is None:
                st.error("jra_odds.py を app.py と同じフォルダに配置してください。")
            else:
                progress = st.progress(0, text="全レースのオッズ更新を開始します")
                failures = []
                success_count = 0
                for position, (venue, race_no, target_date, odds_key, error) in enumerate(race_targets):
                    label = f"{venue}{race_no}R"
                    progress.progress(position / len(race_targets), text=f"{label}を取得中")
                    try:
                        if error:
                            raise ValueError(error)
                        odds_rows, resolved_url = fetch_jra_win_odds_auto(
                            target_date, venue, race_no,
                        )
                        if not odds_rows:
                            raise RuntimeError("単勝オッズを1頭も取得できませんでした。")
                        st.session_state.jra_odds_cache[odds_key] = odds_rows
                        st.session_state[f"jra_resolved_url_{odds_key}"] = resolved_url
                        success_count += 1
                    except Exception as exc:
                        failures.append(f"{label}：{exc}")
                    progress.progress((position + 1) / len(race_targets),
                                      text=f"{position + 1}/{len(race_targets)}レース完了")
                if success_count:
                    st.success(f"全{len(race_targets)}レース中、{success_count}レースのオッズを更新しました。")
                if failures:
                    st.warning("取得に失敗したレースは前回取得したオッズを保持しています。")
                    for failure in failures:
                        st.error(failure)

    # 馬番だけで照合せず、開催・レースごとのキャッシュを適用する。
    odds_by_race = {}
    for venue, race_no, target_date, odds_key, error in race_targets:
        if error:
            continue
        cached_odds = st.session_state.jra_odds_cache.get(odds_key, [])
        if cached_odds:
            odds_by_race[(venue, race_no)] = {
                str(int(item["horse_no"])): item for item in cached_odds
            }

    if odds_by_race:
        def apply_odds(frame):
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

        res_df = apply_odds(res_df)
        raw_csv_df = apply_odds(raw_csv_df)
        view_df = apply_odds(view_df)

        # --- 狙い目: ★F-UP特注★ ---
        # 阪神/京都/中山/東京/中京
        # 未勝利～3勝クラス
        # 厩舎finish-UP 6～7
        # JRA実人気 1～2人気
        target_venues = {"阪神", "京都", "中山", "東京", "中京"}

        def add_fup_special(frame, *, html=True):
            frame = frame.copy()
            comment_col = "総合評価・コース相性判定"

            def number_from_cell(value):
                # HTMLセルの場合、class="rank-1" の「1」を値と誤認しないよう
                # タグを除去してから表示値だけを数値化する。
                if pd.isna(value):
                    return None
                plain = re.sub(r"<[^>]+>", "", str(value)).strip()
                m = re.search(r"-?\d+(?:\.\d+)?", plain)
                return float(m.group()) if m else None

            for idx, row in frame.iterrows():
                # DataFrame内部の開催場列名は「venue」
                venue = str(row.get("venue", "")).strip()

                # CSV 2列目「条件」
                race_condition = str(row.get("条件", "")).strip()
                normalized_condition = (
                    race_condition
                    .replace("１", "1")
                    .replace("２", "2")
                    .replace("３", "3")
                    .replace("ｸﾗｽ", "クラス")
                )

                class_ok = any(
                    c in normalized_condition
                    for c in {"未勝利", "1勝クラス", "2勝クラス", "3勝クラス"}
                )

                fup = number_from_cell(row.get("厩舎F-UP2", ""))
                popularity = number_from_cell(row.get("人気", ""))

                if (
                    venue in target_venues
                    and class_ok
                    and fup is not None
                    and 6 <= fup <= 7
                    and popularity is not None
                    and 1 <= popularity <= 2
                ):
                    mark = "★F-UP特注★"
                    current = str(row.get(comment_col, "") or "")

                    if mark not in current:
                        # 既存の「★...★」赤字化関数を通してから追加。
                        # ★F-UP特注★ も既存の特注コメントと同じ赤字・太字表示になる。
                        marked = format_special_tags_html(mark) if html else mark
                        frame.at[idx, comment_col] = (
                            f"{marked} {current}".strip()
                        )

            return frame

        res_df = add_fup_special(res_df)
        raw_csv_df = add_fup_special(raw_csv_df, html=False)
        view_df = add_fup_special(view_df)

    st.markdown(
        f'<div class="race-header">{title}'
        f'<span class="sub">{date_text}　{len(view_df)}頭</span></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "KOL判定：KOL＜50・乖離率150～450%（両端含む）・実人気5番人気以下・指定騎手28名。"
        "レイティング条件なし。乖離率＝（実オッズ－KOL）÷KOL×100。"
    )
    missing_jockeys = view_df["騎手"].map(normalize_jockey).eq("").sum()
    if missing_jockeys:
        st.info(f"表示中の{missing_jockeys}頭は騎手データ未取得のためKOL判定保留です。元CSVのレースID列の右隣（17列目）に騎手名を追加してください。")
    st.markdown(render_html_table(view_df), unsafe_allow_html=True)

    # --- ダウンロードボタン ---
    download_raw_df = raw_csv_df.drop(
        columns=["original_index", "score", "venue", "race_no", "header"]
    )

    col1, col2 = st.columns(2)
    with col1:
        csv_data = download_raw_df.to_csv(index=False, encoding="cp932", errors="ignore")
        st.download_button(
            label="💾 TARGET用CSVダウンロード",
            data=csv_data,
            file_name="horse_analysis_result.csv",
            mime="text/csv",
        )
    with col2:
        def build_html_report(dataframe, report_title="競馬指数 総合分析レポート"):
            report_html_table = render_html_table(dataframe)
            return f"""<!DOCTYPE html>
            <html lang="ja">
            <head>
            <meta charset="UTF-8">
            <title>{escape(report_title)}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f9f9f9; }}
                h2 {{ color: #333; }}
                .table-container {{
                    width: 100%;
                    overflow-x: auto;
                    border: 1px solid #ddd;
                    border-radius: 6px;
                    background-color: white;
                }}
                .custom-horse-table {{
                    width: 100% !important;
                    border-collapse: collapse;
                    font-size: 11px;
                    background-color: white;
                    color: #31333F;
                }}
                .custom-horse-table th, .custom-horse-table td {{
                    border: 1px solid #e0e0e0;
                    padding: 6px 8px;
                    text-align: center;
                    white-space: nowrap;
                }}
                .custom-horse-table th {{
                    background-color: #f0f2f6;
                    font-weight: 600;
                }}
                .custom-horse-table {{
                    table-layout: fixed;
                }}
                .custom-horse-table th:nth-child(15),
                .custom-horse-table td:nth-child(15) {{
                    width: 30%;
                    white-space: normal !important;
                    overflow-wrap: anywhere;
                    text-align: left !important;
                }}
                .rank-1 {{ background-color: #fff2b2 !important; font-weight: bold; }}
                .rank-2 {{ background-color: #e6f2ff !important; }}
                .rank-3 {{ background-color: #d4edda !important; }}
                .odds-gap-alert {{
                    background-color: #ffe08a !important;
                    color: #b42318 !important;
                    font-weight: 800 !important;
                }}
                .push-mark-red {{ color: #ff4b4b !important; font-weight: bold; }}
            </style>
            </head>
            <body>
            <h2>🏇 {escape(report_title)}</h2>
            {report_html_table}
            </body>
            </html>"""

        html_full = build_html_report(res_df)
        st.download_button(
            label="🌐 HTMLレポートダウンロード",
            data=html_full,
            file_name="horse_analysis_result.html",
            mime="text/html",
        )

    # 全CSVの更新済みデータから、画面の着色と同じKOL判定で抽出する。
    kol_mask = res_df.apply(
        lambda row: kol_alert_matches(
            row.get("KOLオッズ", ""), row.get("実オッズ", ""),
            row.get("人気", ""), row.get("騎手", ""),
        ),
        axis=1,
    )
    kol_df = res_df.loc[kol_mask].copy()
    st.caption(
        f"KOL判定該当馬：全開催・全レースで{len(kol_df)}頭。"
        "オッズ更新後の取得済みデータを使います。"
    )
    st.download_button(
        label="🎯 KOL判定該当馬のみHTMLダウンロード",
        data=build_html_report(kol_df, "KOL判定該当馬レポート"),
        file_name="horse_analysis_kol_matches.html",
        mime="text/html",
        disabled=kol_df.empty,
    )
