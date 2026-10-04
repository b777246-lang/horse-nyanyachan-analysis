"""画面とHTMLの装飾。数値判定はanalysis/signalsに委譲する。"""
import re
from html import escape
import pandas as pd
from config import WAKUBAN_COLORS, DEFAULT_SETTINGS
from values import decimal_value, normalize_jockey
from signals import kol_divergence, kol_alert_matches, DEFAULT_REGISTRY

SCREEN_CSS = """
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
    """


def format_special_tags_html(text):
    if not text:
        return ""
    pattern = re.compile(r"(★[^★]+★)")
    return pattern.sub(r'<span style="color: #ff4b4b; font-weight: bold;">\1</span>', text)

def get_cell_html(val, rank):
    if rank == 1:
        return f'<td class="rank-1">{val}</td>'
    elif rank == 2:
        return f'<td class="rank-2">{val}</td>'
    elif rank == 3:
        return f'<td class="rank-3">{val}</td>'
    else:
        return f"<td>{val}</td>"

def render_html_table(dataframe, *, settings=DEFAULT_SETTINGS):
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
            row.get("人気", ""), jockey, settings=settings,
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


def format_analysis_frame(frame, notes, *, settings=DEFAULT_SETTINGS, registry=DEFAULT_REGISTRY):
    display = frame.copy()
    for column in ("arms", "arms2", "TUA", "S", "F", "厩舎F-UP2"):
        display[column] = display[column].astype("object")
    for idx, row in frame.iterrows():
        note = notes[row["original_index"]]
        comment = note["evaluation"]
        for special in note["special_comments"]:
            if special:
                comment = comment.replace(special, format_special_tags_html(special))
        external = note["external_comment"]
        if external:
            comment = f"{external} ▼ {comment}" if comment else external
        for match in registry.evaluate(row, settings, stage="live"):
            if match.comment and match.comment not in comment:
                comment = f"{format_special_tags_html(match.comment)} {comment}".strip()
        display.at[idx, "総合評価・コース相性判定"] = comment
        if row["推印"] == "推":
            display.at[idx, "推印"] = '<span class="push-mark-red">推</span>'
        for column, rank in note["ranks"].items():
            display.at[idx, column] = get_cell_html(row[column], rank)
    return display
