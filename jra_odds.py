"""
JRA公式 単勝オッズ取得モジュール

用途:
- StreamlitアプリからJRA公式出馬表を取得
- 馬番、馬名、単勝オッズ、人気を抽出
- TARGETの18桁レースIDと馬番で照合

注意:
- JRAのページURLは呼び出し側から渡す設計です。
- JRAページURLを固定せず、アプリ側のレース選択処理と分離しています。
"""

from __future__ import annotations

import re
from typing import Any

import requests
from bs4 import BeautifulSoup


JRA_HOME_URL = "https://www.jra.go.jp/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


def fetch_jra_win_odds(race_url: str, timeout: int = 20) -> list[dict[str, Any]]:
    """
    JRA公式の出馬表URLから単勝オッズを取得する。

    戻り値:
        [
            {
                "horse_no": 1,
                "horse_name": "馬名",
                "jra_odds": 5.2,
                "popularity": 2,
            },
            ...
        ]
    """
    if not race_url:
        raise ValueError("JRAレースURLが指定されていません。")

    session = requests.Session()
    session.headers.update(HEADERS)

    # JRAトップへ先にアクセスしてセッションを作る。
    home = session.get(
        JRA_HOME_URL,
        timeout=timeout,
        allow_redirects=True,
    )
    home.raise_for_status()

    session.headers.update({"Referer": home.url})

    response = session.get(
        race_url,
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()

    html = response.content.decode("cp932", errors="replace")

    if "パラメータエラー" in html:
        raise RuntimeError(
            "JRAからパラメータエラーページが返されました。"
            f"\n取得URL: {response.url}"
        )

    if "単勝オッズ" not in html:
        raise RuntimeError(
            "JRAページには「単勝オッズ」が見つかりませんでした。"
            f"\n取得URL: {response.url}"
        )

    soup = BeautifulSoup(html, "html.parser")

    rows: list[dict[str, Any]] = []

    # 現在確認できているJRA公式HTML構造:
    # <tr>
    #   <td class="num">馬番</td>
    #   <td class="horse">
    #       <div class="name">馬名</div>
    #       <div class="odds">
    #           <span class="num"><strong>52.3</strong></span>
    #           <span class="pop_rank">(14<span>番人気</span>)</span>
    #       </div>
    #   </td>
    # </tr>
    for tr in soup.select("tr"):
        num_td = tr.select_one("td.num")
        horse_td = tr.select_one("td.horse")

        if not num_td or not horse_td:
            continue

        num_match = re.search(
            r"\d+",
            num_td.get_text(" ", strip=True),
        )
        if not num_match:
            continue

        horse_no = int(num_match.group())
        if not 1 <= horse_no <= 18:
            continue

        name_tag = horse_td.select_one(".name")
        horse_name = (
            name_tag.get_text(" ", strip=True)
            if name_tag
            else ""
        )

        odds_tag = horse_td.select_one(".odds strong")
        if not odds_tag:
            continue

        odds_text = odds_tag.get_text(" ", strip=True)
        try:
            jra_odds = float(odds_text)
        except ValueError:
            continue

        popularity: int | None = None
        pop_tag = horse_td.select_one(".pop_rank")
        if pop_tag:
            pop_match = re.search(
                r"\d+",
                pop_tag.get_text(" ", strip=True),
            )
            if pop_match:
                popularity = int(pop_match.group())

        rows.append(
            {
                "horse_no": horse_no,
                "horse_name": horse_name,
                "jra_odds": jra_odds,
                "popularity": popularity,
            }
        )

    # 同一馬番の重複を除き、馬番順にする。
    by_no: dict[int, dict[str, Any]] = {}
    for row in rows:
        by_no[row["horse_no"]] = row

    result = [
        by_no[no]
        for no in sorted(by_no)
    ]

    if not result:
        raise RuntimeError(
            "JRAページから単勝オッズを1頭も抽出できませんでした。"
        )

    return result


def merge_jra_odds(
    rows: list[dict[str, Any]],
    race_id_column: str,
    jra_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    TARGET/JRAデータを18桁レースIDの末尾2桁（馬番）で結合する。

    元データの各行は変更せず、以下の列を追加:
      実オッズ
      人気

    race_id_column:
        18桁のTARGETレースIDが入っている列名
    """
    jra_by_no = {
        int(row["horse_no"]): row
        for row in jra_rows
    }

    merged: list[dict[str, Any]] = []

    for source_row in rows:
        row = dict(source_row)

        raw_id = str(row.get(race_id_column, "")).strip()

        if re.fullmatch(r"\d{18}", raw_id):
            horse_no = int(raw_id[-2:])
            jra = jra_by_no.get(horse_no)

            if jra is not None:
                row["実オッズ"] = jra["jra_odds"]
                row["人気"] = jra["popularity"]
            else:
                row["実オッズ"] = None
                row["人気"] = None
        else:
            row["実オッズ"] = None
            row["人気"] = None

        merged.append(row)

    return merged
