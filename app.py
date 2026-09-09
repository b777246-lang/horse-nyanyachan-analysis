import glob
import os
import re
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="競馬指数 総合分析Webアプリケーション", layout="wide"
)

# 📱 iPhoneでピンチイン（拡大・縮小）を使えるようにするメタタグ
st.markdown(
    """
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes">
    """,
    unsafe_allow_html=True,
)

# --- カスタムCSS（テーブルの列幅やセル背景色のスタイル） ---
st.markdown(
    """
    <style>
    /* 全体のパディング調整 */
    .main .block-container {
        max-width: 100% !important;
        padding-left: 0.2rem;
        padding-right: 0.2rem;
        padding-top: 1rem;
    }
    
    /* 横スクロール可能なテーブルコンテナに戻す */
    .table-container {
        width: 100%;
        max-height: 75vh;
        overflow-x: auto !important; /* 横スクロールを許可して隠れないようにする */
        overflow-y: auto !important;
        -webkit-overflow-scrolling: touch;
        border: 1px solid #ddd;
        border-radius: 4px;
        margin-bottom: 20px;
        background-color: white;
    }

    .custom-horse-table {
        width: max-content !important; /* 内容に合わせて幅を確保し、全列を表示する */
        min-width: 100% !important;
        border-collapse: collapse;
        font-size: 11px; /* 潰れすぎない見やすいサイズに調整 */
        background-color: white;
        color: #31333F;
    }

    .custom-horse-table th, .custom-horse-table td {
        border: 1px solid #e0e0e0;
        padding: 6px 8px;
        text-align: center;
        white-space: nowrap; /* 各セルが勝手に折り返して崩れるのを防ぐ */
    }

    .custom-horse-table th {
        background-color: #f0f2f6;
        position: sticky;
        top: 0;
        z-index: 10;
        font-weight: 600;
    }

    /* 最後の列（総合評価・コメント）の幅をしっかり確保 */
    .custom-horse-table th:last-child, 
    .custom-horse-table td:last-child {
        min-width: 220px;
        white-space: normal !important;
        text-align: left !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    """
    <style>
    .main .block-container {
        max-width: 98% !important;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    
    .table-container {
        max-height: 550px;
        overflow-y: auto;
        border: 1px solid #ddd;
        border-radius: 4px;
        margin-bottom: 20px;
    }

    .custom-horse-table {
        width: 100% !important;
        border-collapse: collapse;
        font-size: 13px;
        background-color: white;
        color: #31333F;
    }

    .custom-horse-table th, .custom-horse-table td {
        border: 1px solid #e0e0e0;
        padding: 8px 10px;
        text-align: center;
        white-space: nowrap;
    }

    .custom-horse-table th {
        background-color: #f0f2f6;
        position: sticky;
        top: 0;
        z-index: 10;
        font-weight: 600;
    }

    /* 最後の列（総合評価・コース相性判定）だけ幅を広げ、テキストを折り返す */
    .custom-horse-table th:last-child, 
    .custom-horse-table td:last-child {
        width: 100% !important;
        white-space: normal !important;
        text-align: left !important;
    }

    /* 順位に応じたハイライト用クラス */
    .rank-1 {
        background-color: #fff2b2 !important; /* 1位: 黄色系統 */
        font-weight: bold;
    }
    .rank-2 {
        background-color: #e6f2ff !important; /* 2位: 水色系統 */
    }
    .rank-3 {
        background-color: #d4edda !important; /* 3位: 黄緑系統 */
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🏇 競馬指数 総合分析Webアプリケーション")


# --- コース別成績データの事前読み込み（キャッシュ機能で高速化） ---
@st.cache_data
def load_course_data():
  course_stats = {}
  try:
    df = pd.read_csv("arms及びarms2及びTUA指数の全てが一位.csv", encoding="cp932")
    course_stats["triple"] = df
  except Exception as e:
    pass

  csv_files = glob.glob("*指数*位のコース別成績.csv")
  for filepath in csv_files:
    filename = os.path.basename(filepath)
    try:
      df = pd.read_csv(filename, encoding="cp932")
      course_stats[filename] = df
    except Exception as e:
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

# --- サイドバー：ファイル読み込みエリア ---
st.sidebar.header("📂 ファイル読み込み")

uploaded_file = st.sidebar.file_uploader(
    "メイン指数CSVファイルを選択（上書き用）", type=["csv"]
)
uploaded_ext_comment = st.sidebar.file_uploader(
    "💬 外部コメントCSVを選択（任意）", type=["csv"]
)

# 1. ユーザーが新しくメインファイルをアップロードした場合
if uploaded_file is not None:
  try:
    df = pd.read_csv(uploaded_file, encoding="cp932", header=None)
  except Exception:
    uploaded_file.seek(0)
    df = pd.read_csv(uploaded_file, encoding="utf-8", header=None)
  st.sidebar.success("アップロードされたメインファイルを読み込みました")

# 2. アップロードされていない場合は、GitHub内にある「YYYYMMDD.csv」形式のファイルを自動検索する
else:
  # 8桁の数字.csv というパターンのファイルを自動で探す
  pattern = re.compile(r"^\d{8}\.csv$")
  matched_files = [f for f in os.listdir(".") if pattern.match(f)]

  if matched_files:
    # 最も新しい（ファイル名が一番大きい＝日付が新しい）ものを自動選択
    default_main_csv = sorted(matched_files)[-1]
    try:
      df = pd.read_csv(default_main_csv, encoding="cp932", header=None)
      st.sidebar.info(
          f"📌 自動検出: {default_main_csv} を読み込んでいます"
      )
    except Exception:
      df = pd.read_csv(default_main_csv, encoding="utf-8", header=None)
      st.sidebar.info(
          f"📌 自動検出: {default_main_csv} を読み込んでいます"
      )
  else:
    df = None
    st.sidebar.info(
        "左側のサイドバーから「指数CSVファイル」をアップロードしてください。"
    )

# 外部コメントの自動読み込み処理（未選択の場合の自動検出）
if uploaded_ext_comment is not None:
  ext_file_to_read = uploaded_ext_comment
else:
  # YYYYMMDDcomment.csv というパターンのファイルを自動検索
  ext_pattern = re.compile(r"^\d{8}comment\.csv$")
  matched_ext_files = [f for f in os.listdir(".") if ext_pattern.match(f)]
  ext_file_to_read = sorted(matched_ext_files)[-1] if matched_ext_files else None

ext_comment_dict = {}
if ext_file_to_read is not None:
  try:
    df_ext = pd.read_csv(ext_file_to_read, encoding="cp932", header=None)
    for _, row in df_ext.iterrows():
      vals = [str(v).string().strip() if hasattr(str(v), 'string') else str(v).strip() for v in row.values if pd.notna(v)]
      if len(vals) >= 6:
        h_name = vals[2]
        c_text = vals[5]
        if h_name and c_text:
          ext_comment_dict[h_name] = c_text
    if uploaded_ext_comment is not None:
      st.sidebar.success(f"外部コメント読込成功（{len(ext_comment_dict)}頭分）")
    else:
      st.sidebar.info(f"📌 自動検出コメント読込: {os.path.basename(str(ext_file_to_read))}（{len(ext_comment_dict)}頭分）")
  except Exception as e:
    pass

  # --- データ処理ロジック ---
  df["arms_val"] = pd.to_numeric(df.iloc[:, 7], errors="coerce").fillna(0)
  df["arms2_val"] = pd.to_numeric(df.iloc[:, 8], errors="coerce").fillna(0)
  df["tua_val"] = pd.to_numeric(df.iloc[:, 9], errors="coerce").fillna(0)
  df["S_val"] = pd.to_numeric(df.iloc[:, 10], errors="coerce").fillna(0)
  df["F_val"] = pd.to_numeric(df.iloc[:, 11], errors="coerce").fillna(0)
  df["finish_up_val"] = pd.to_numeric(df.iloc[:, 12], errors="coerce").fillna(
      0
  )

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

  for idx, row in df.iterrows():
    race_raw = str(row.get(0, ""))
    cond_name = str(row.get(1, ""))
    surface = str(row.get(2, ""))
    try:
      distance = int(row.get(3, 0))
    except ValueError:
      distance = 0

    cond_raw = f"{cond_name} {surface}{distance}"
    wakuban_raw = row.get(4, "")
    wakuban = (
        int(wakuban_raw)
        if pd.notna(wakuban_raw) and str(wakuban_raw).isdigit()
        else 0
    )
    umaban = str(row.get(5, ""))
    name = str(row.get(6, "")).strip()

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

    if finish_up_count < 4:
      if finish_up >= 5 or finish_up_rank <= 3:
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
              compat = {
                  "course": c_target,
                  "win_rate": str(t_row.get("勝率", "0%")),
                  "place_rate": str(t_row.get("複勝率", "0%")),
                  "win_ret": str(t_row.get("単勝回収値", "0")),
                  "place_ret": str(t_row.get("複勝回収値", "0")),
              }
              try:
                win_ret_val = float(
                    str(compat["win_ret"]).replace("%", "").strip()
                )
              except ValueError:
                win_ret_val = 0.0
              try:
                place_rate_val = float(
                    str(compat["place_rate"]).replace("%", "").strip()
                )
              except ValueError:
                place_rate_val = 0.0

              if win_ret_val >= 100 or place_rate_val >= 60:
                is_triple_1st = True
                course_compat_text = f"👑 【★トリプル１位★: {compat['course']} 複勝率{compat['place_rate']}/単回{compat['win_ret']}】"
                score += 3
              break

    if not is_triple_1st:
      checks = [
          ("arms", arms_rank),
          ("arms2", arms2_rank),
          ("TUA", tua_rank),
          ("S", s_rank),
          ("F", f_rank),
      ]
      for t, rnk in checks:
        if rnk <= 3:
          compat = get_course_compatibility(
              race_raw, surface, distance, t, rnk, course_stats
          )
          if compat:
            try:
              win_ret_val = float(
                  str(compat["win_ret"]).replace("%", "").strip()
              )
            except ValueError:
              win_ret_val = 0.0
            try:
              place_rate_val = float(
                  str(compat["place_rate"]).replace("%", "").strip()
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
        if (is_dirt and is_not_maishin and wakuban in [6, 7, 8] and s_rank == 1)
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

    eval_parts = []
    if nakayama_2000_text:
      eval_parts.append(nakayama_2000_text)
    if nakayama_1600_text:
      eval_parts.append(nakayama_1600_text)
    if suna_食_text:
      eval_parts.append(suna_食_text)
    if f72_text:
      eval_parts.append(f72_text)
    if highlights:
      eval_parts.extend(highlights)
    if course_compat_text:
      eval_parts.append(course_compat_text)

    if not eval_parts:
      eval_text = ""
    else:
      eval_text = " / ".join(eval_parts)
      if is_triple_1st:
        eval_text = "🌟 【★トリプル１位★推奨】 " + eval_text
      elif score >= 4:
        eval_text = "🔥 【軸馬推奨】 " + eval_text
      elif score >= 2:
        eval_text = "⭐ 【有力候補】 " + eval_text
      elif (
          is_good_compatibility
          or suna_食_text
          or f72_text
          or nakayama_1600_text
          or nakayama_2000_text
      ):
        eval_text = "🎯 【注目条件】 " + eval_text

    if ext_comment_dict and name in ext_comment_dict:
      ext_c = ext_comment_dict[name]
      eval_text = f"{ext_c} ▼ {eval_text}" if eval_text else ext_c

    # --- 各指数の順位に応じたHTMLセル装飾（色分け）関数 ---
    def get_cell_html(val, rank):
      if rank == 1:
        return f'<td class="rank-1">{val}</td>'
      elif rank == 2:
        return f'<td class="rank-2">{val}</td>'
      elif rank == 3:
        return f'<td class="rank-3">{val}</td>'
      else:
        return f"<td>{val}</td>"

    # 画面表示用のHTML埋め込みデータ
    export_data_list.append({
        "レース": race_raw,
        "条件": cond_raw,
        "枠番": wakuban,
        "馬番": umaban,
        "馬名": name,
        "arms": get_cell_html(arms, arms_rank),
        "arms2": get_cell_html(arms2, arms2_rank),
        "TUA": get_cell_html(tua, tua_rank),
        "S": get_cell_html(s_idx, s_rank),
        "F": get_cell_html(f_idx, f_rank),
        "厩舎F-UP2": get_cell_html(finish_up, finish_up_rank),
        "総合評価・コース相性判定": eval_text,
    })

    # CSV出力用の生データ
    raw_data_list.append({
        "レース": race_raw,
        "条件": cond_raw,
        "枠番": wakuban,
        "馬番": umaban,
        "馬名": name,
        "arms": arms,
        "arms2": arms2,
        "TUA": tua,
        "S": s_idx,
        "F": f_idx,
        "厩舎F-UP2": finish_up,
        "総合評価・コース相性判定": eval_text,
    })

  res_df = pd.DataFrame(export_data_list)
  raw_csv_df = pd.DataFrame(raw_data_list)

  st.success(f"ファイルを正常に読み込みました（全 {len(res_df)} 頭）")

  # --- カスタムHTMLテーブルの組み立て（確実に列のズレやインデックスを防止） ---
  st.subheader("📊 出走馬・指数一覧分析")


  def render_html_table(dataframe):
    html = ['<div class="table-container"><table class="custom-horse-table">']

    # ヘッダー行の作成
    html.append("<thead><tr>")
    for col in dataframe.columns:
      html.append(f"<th>{col}</th>")
    html.append("</tr></thead>")

    # ボディ行の作成
    html.append("<tbody>")
    for _, row in dataframe.iterrows():
      html.append("<tr>")
      # レース〜馬番までは通常セル
      for i in range(5):
        html.append(f"<td>{row.iloc[i]}</td>")
      # 指数カラム（HTMLタグがすでに入っているためそのまま出力）
      for i in range(5, 11):
        html.append(str(row.iloc[i]))
      # 総合評価カラム
      html.append(f"<td>{row.iloc[11]}</td>")
      html.append("</tr>")
    html.append("</tbody>")

    html.append("</table></div>")
    return "".join(html)


  table_html = render_html_table(res_df)
  st.markdown(table_html, unsafe_allow_html=True)

  # --- ダウンロードボタン ---
  col1, col2 = st.columns(2)

  with col1:
    csv_data = raw_csv_df.to_csv(index=False, encoding="cp932", errors="ignore")
    st.download_button(
        label="💾 TARGET用CSVファイルでダウンロード",
        data=csv_data,
        file_name="horse_analysis_result.csv",
        mime="text/csv",
    )

  with col2:
    html_data = res_df.to_html(index=False, escape=False)
    html_full = f"""<!DOCTYPE html>
        <html lang="ja">
        <head>
        <meta charset="UTF-8">
        <title>競馬指数 総合分析レポート</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: center; font-size: 13px; }}
            th {{ background-color: #3498db; color: white; }}
            th:last-child, td:last-child {{ text-align: left; }}
            .rank-1 {{ background-color: #fff2b2 !important; font-weight: bold; }}
            .rank-2 {{ background-color: #e6f2ff !important; }}
            .rank-3 {{ background-color: #d4edda !important; }}
        </style>
        </head>
        <body>
        <h2>競馬指数 総合分析レポート</h2>
        {html_data}
        </body>
        </html>
        """
    st.download_button(
        label="🌐 HTMLレポートとしてダウンロード",
        data=html_full,
        file_name="horse_analysis_result.html",
        mime="text/html",
    )

else:
  st.info(
      "左側のサイドバーから「指数CSVファイル」をアップロードしてください。"
  )
