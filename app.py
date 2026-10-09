"""Streamlitの画面と操作。判定・装飾・出力は各モジュールに委譲する。"""
import re
import streamlit as st

from analysis import analyze_csv
from values import normalize_jockey
from signals import add_live_comments, filter_kol_horses
from config import load_settings
from data_loader import latest_csv, read_main_csv, load_comments, load_course_data
from formatting import SCREEN_CSS, format_analysis_frame, render_html_table
from export import build_html_report, build_target_csv, format_target_frame
from odds_service import build_race_targets, cached_odds_by_race, update_all_odds, apply_odds

try:
    from jra_odds import fetch_jra_win_odds_auto
except ImportError:
    fetch_jra_win_odds_auto = None


settings = load_settings()

st.set_page_config(
    page_title="競馬指数 総合分析Webアプリケーション", layout="wide"
)

# --- セッション状態の初期化 ---
if "sort_mode" not in st.session_state:
    st.session_state.sort_mode = "初期配列"

if "jra_odds_cache" not in st.session_state:
    st.session_state.jra_odds_cache = {}


# --- カスタムCSS ---
st.markdown(SCREEN_CSS, unsafe_allow_html=True)

st.title("🏇 競馬指数 総合分析Webアプリケーション")


course_stats = st.cache_data(load_course_data)()


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
    df = read_main_csv(uploaded_file)
    st.sidebar.success("アップロードされたファイルを読み込みました")
else:
    default_main_csv = latest_csv()
    if default_main_csv is not None:
        source_name = default_main_csv.name
        df = read_main_csv(default_main_csv)
        st.sidebar.info(f"📌 自動検出: {source_name} を読み込んでいます")
    else:
        st.sidebar.info("左側のサイドバーから指数CSVファイルをアップロードしてください。")

ext_comment_dict = load_comments(
    uploaded_ext_comment if uploaded_ext_comment is not None else latest_csv(comments=True)
)

if df is not None:
    batch = analyze_csv(df, course_stats, ext_comment_dict, settings=settings)
    res_df = format_analysis_frame(batch.frame, batch.notes, settings=settings)
    raw_csv_df = format_target_frame(batch.frame)

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
    race_targets = build_race_targets(res_df, date_text)

    with st.expander("💴 JRA単勝オッズ", expanded=False):
        st.caption(f"CSV内の全開催・全{len(race_targets)}レースを更新します。")
        if st.button("🔄 オッズ更新", key="odds_update_all"):
            if fetch_jra_win_odds_auto is None:
                st.error("jra_odds.py を app.py と同じフォルダに配置してください。")
            else:
                progress = st.progress(0, text="全レースのオッズ更新を開始します")
                summary = update_all_odds(
                    race_targets, st.session_state.jra_odds_cache, fetch_jra_win_odds_auto,
                    lambda fraction, text: progress.progress(fraction, text=text),
                )
                for key, url in summary.urls.items():
                    st.session_state[f"jra_resolved_url_{key}"] = url
                success_count = summary.success_count
                failures = summary.failures
                if success_count:
                    st.success(f"全{len(race_targets)}レース中、{success_count}レースのオッズを更新しました。")
                if failures:
                    st.warning("取得に失敗したレースは前回取得したオッズを保持しています。")
                    for failure in failures:
                        st.error(failure)

    # 馬番だけで照合せず、開催・レースごとのキャッシュを適用する。
    odds_by_race = cached_odds_by_race(race_targets, st.session_state.jra_odds_cache)
    if odds_by_race:
        raw_csv_df = add_live_comments(apply_odds(raw_csv_df, odds_by_race), settings=settings)
        res_df = format_analysis_frame(raw_csv_df, batch.notes, settings=settings)
        if sel_race == "ALL":
            view_df = res_df[res_df["venue"] == sel_venue]
        else:
            view_df = res_df[(res_df["venue"] == sel_venue) & (res_df["race_no"] == sel_race)]

    st.markdown(
        f'<div class="race-header">{title}'
        f'<span class="sub">{date_text}　{len(view_df)}頭</span></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"KOL判定：KOL＜{settings.kol.maximum}・乖離率{settings.kol.divergence_min}～{settings.kol.divergence_max}%（両端含む）・実人気{settings.kol.popularity_min}番人気以下・指定騎手{len(settings.kol.jockeys)}名。"
        "レイティング条件なし。乖離率＝（実オッズ－KOL）÷KOL×100。"
    )
    missing_jockeys = view_df["騎手"].map(normalize_jockey).eq("").sum()
    if missing_jockeys:
        st.info(f"表示中の{missing_jockeys}頭は騎手データ未取得のためKOL判定保留です。新CSVは16列目=レースID、17列目=血統登録番号、18列目=騎手名です。騎手列を確認してください。")
    st.markdown(render_html_table(view_df, settings=settings), unsafe_allow_html=True)

    # --- ダウンロードボタン ---
    col1, col2 = st.columns(2)
    with col1:
        csv_data = build_target_csv(raw_csv_df)
        st.download_button(
            label="💾 TARGET用CSVダウンロード",
            data=csv_data,
            file_name="horse_analysis_result.csv",
            mime="text/csv",
        )
    with col2:
        html_full = build_html_report(res_df, settings=settings)
        st.download_button(
            label="🌐 HTMLレポートダウンロード",
            data=html_full,
            file_name="horse_analysis_result.html",
            mime="text/html",
        )

    # 全CSVの更新済みデータから、画面の着色と同じKOL判定で抽出する。
    kol_df = filter_kol_horses(res_df, settings=settings)
    st.caption(
        f"KOL判定該当馬：全開催・全レースで{len(kol_df)}頭。"
        "オッズ更新後の取得済みデータを使います。"
    )
    st.download_button(
        label="🎯 KOL判定該当馬のみHTMLダウンロード",
        data=build_html_report(kol_df, "KOL判定該当馬レポート", settings=settings),
        file_name="horse_analysis_kol_matches.html",
        mime="text/html",
        disabled=kol_df.empty,
    )
