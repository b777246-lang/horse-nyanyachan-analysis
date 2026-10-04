"""TARGET用CSVと通常・KOL HTMLの出力。"""
import re
import pandas as pd
from html import escape
from formatting import render_html_table
from config import DEFAULT_SETTINGS

def build_html_report(dataframe, report_title="競馬指数 総合分析レポート", *, settings=DEFAULT_SETTINGS):
    report_html_table = render_html_table(dataframe, settings=settings)
    # 出力HTMLは画面幅に押し込まず、列幅を確保して横スクロールする。
    widths = (4, 8, 3, 3, 3, 10, 5, 3, 4, 4, 4, 3, 3, 5, 26, 6, 6)
    colgroup = "<colgroup>" + "".join(
        f'<col style="width: {width}%;">' for width in widths
    ) + "</colgroup>"
    report_html_table = report_html_table.replace(
        '<table class="custom-horse-table">',
        '<table class="custom-horse-table">' + colgroup,
        1,
    )
    return f"""<!DOCTYPE html>
            <html lang="ja">
            <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{escape(report_title)}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 12px; background-color: #f9f9f9; }}
                h2 {{ color: #333; }}
                .table-container {{
                    width: 100%;
                    overflow-x: auto;
                    border: 1px solid #ddd;
                    border-radius: 6px;
                    background-color: white;
                    box-sizing: border-box;
                    -webkit-overflow-scrolling: touch;
                }}
                .custom-horse-table {{
                    width: 100% !important;
                    min-width: 1280px;
                    table-layout: fixed;
                    border-collapse: collapse;
                    font-size: 12px;
                    background-color: white;
                    color: #31333F;
                }}
                .custom-horse-table th, .custom-horse-table td {{
                    border: 1px solid #e0e0e0;
                    padding: 6px 4px;
                    text-align: center;
                    white-space: normal;
                    overflow-wrap: anywhere;
                    line-height: 1.5;
                    box-sizing: border-box;
                    vertical-align: middle;
                }}
                .custom-horse-table th {{
                    background-color: #f0f2f6;
                    font-weight: 600;
                }}
                .custom-horse-table th:nth-child(15),
                .custom-horse-table td:nth-child(15) {{
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


def build_target_csv(frame):
    return frame.drop(columns=["original_index", "score", "venue", "race_no", "header"]).to_csv(index=False, encoding="cp932", errors="ignore")


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


def format_target_frame(frame):
    frame = frame.copy()
    frame["総合評価・コース相性判定"] = frame["総合評価・コース相性判定"].map(clean_eval_text_for_target)
    return frame
