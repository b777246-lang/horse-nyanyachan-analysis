from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

JRA_HOME_URL = "https://www.jra.go.jp/"
JRA_ACCESS_URL = "https://www.jra.go.jp/JRADB/accessD.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

PLACE_CODES = {
    "札幌": "01", "函館": "02", "福島": "03", "新潟": "04", "東京": "05",
    "中山": "06", "中京": "07", "京都": "08", "阪神": "09", "小倉": "10",
}


def _decode(response: requests.Response) -> str:
    return response.content.decode("cp932", errors="replace")


def _doaction(anchor) -> tuple[str, str] | None:
    onclick = anchor.get("onclick", "")
    m = re.search(
        r"doAction\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)",
        onclick,
    )
    return m.groups() if m else None


def _new_session(timeout: int) -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    home = session.get(JRA_HOME_URL, timeout=timeout, allow_redirects=True)
    home.raise_for_status()
    session.headers.update({"Referer": home.url})
    return session


def _get_meeting_select(session: requests.Session, timeout: int) -> tuple[str, str]:
    """
    JRAトップからJRADBへ入り、開催選択ページを取得する。
    検証済みのJRA側開催選択cnameを入口として使用する。
    末尾は出馬表HTMLから確認したJRA自身の開催選択値。
    """
    # v4検証でJRA出馬表の「開催選択」doActionから確認した値
    meeting_cname = "pw01dli00/F3"
    session.headers.update({
        "Referer": JRA_HOME_URL,
        "Origin": "https://www.jra.go.jp",
    })
    r = session.post(
        JRA_ACCESS_URL,
        data={"cname": meeting_cname},
        timeout=timeout,
        allow_redirects=True,
    )
    r.raise_for_status()
    html = _decode(r)
    if "パラメータエラー" in html:
        raise RuntimeError("JRA開催選択ページでパラメータエラーになりました。")
    return r.url, html


def _find_race_select_cname(
    html: str,
    base_url: str,
    date_yyyymmdd: str,
    venue_name: str,
) -> tuple[str, str]:
    place = PLACE_CODES.get(venue_name)
    if not place:
        raise ValueError(f"JRA場所コードを特定できません: {venue_name}")

    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[str, str, str]] = []

    for a in soup.find_all("a"):
        parsed = _doaction(a)
        if not parsed:
            continue
        action_path, cname = parsed
        if "pw01drl" not in cname:
            continue

        # JRA自身が生成する開催リンクには pw01drl0 / pw01drl1 の両形式がある。
        # TARGET場所05に対しJRA側は005。開催場を完全一致で照合する。
        if not re.match(rf"^pw01drl[01]{int(place):03d}", cname):
            continue
        if date_yyyymmdd not in cname:
            continue

        candidates.append(
            (urljoin(base_url, action_path), cname, a.get_text(" ", strip=True))
        )

    if not candidates:
        raise RuntimeError(
            f"JRA開催選択ページに {date_yyyymmdd} {venue_name} の開催が見つかりません。"
        )

    # 同日・同場は通常1候補。複数なら安全のため曖昧として止める。
    unique = {(u, c): (u, c, t) for u, c, t in candidates}
    candidates = list(unique.values())
    if len(candidates) != 1:
        texts = " / ".join(x[2] for x in candidates)
        raise RuntimeError(
            f"JRA開催候補を一意に決められません ({len(candidates)}件): {texts}"
        )

    return candidates[0][0], candidates[0][1]


def _get_race_select_page(
    session: requests.Session,
    action_url: str,
    cname: str,
    referer: str,
    timeout: int,
) -> tuple[str, str]:
    session.headers.update({
        "Referer": referer,
        "Origin": "https://www.jra.go.jp",
    })
    r = session.post(
        action_url,
        data={"cname": cname},
        timeout=timeout,
        allow_redirects=True,
    )
    r.raise_for_status()
    html = _decode(r)
    if "パラメータエラー" in html:
        raise RuntimeError("JRAレース選択ページでパラメータエラーになりました。")
    return r.url, html


def _find_race_url(
    html: str,
    base_url: str,
    date_yyyymmdd: str,
    venue_name: str,
    race_no: int,
) -> str:
    place = PLACE_CODES.get(venue_name)
    if not place:
        raise ValueError(f"JRA場所コードを特定できません: {venue_name}")

    soup = BeautifulSoup(html, "html.parser")
    candidates = []

    # JRAの正規出馬表URLの構造を、実際に取得した12Rリンクに合わせて照合。
    pattern = re.compile(
        r"pw01dde(?:10?|01)"
        + re.escape(place)
        + r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})/([0-9A-F]{2})",
        re.I,
    )

    for a in soup.find_all("a", href=True):
        href = a["href"]
        absolute = urljoin(base_url, href)
        if "accessD.html?CNAME=" not in absolute:
            continue

        m = pattern.search(absolute)
        if not m:
            continue

        _year, _kai, _day_no, rno, date, _suffix = m.groups()
        if date == date_yyyymmdd and int(rno) == int(race_no):
            candidates.append(absolute)

    candidates = list(dict.fromkeys(candidates))
    if not candidates:
        raise RuntimeError(
            f"JRAレース選択ページに {venue_name}{race_no}R の出馬表URLが見つかりません。"
        )
    if len(candidates) > 1:
        raise RuntimeError(
            f"{venue_name}{race_no}R のJRA出馬表URLが複数見つかりました。"
        )
    return candidates[0]


def _extract_win_odds(html: str) -> list[dict[str, Any]]:
    if "パラメータエラー" in html:
        raise RuntimeError("JRAからパラメータエラーページが返されました。")
    if "単勝オッズ" not in html:
        raise RuntimeError("JRAページに単勝オッズが見つかりません。")

    soup = BeautifulSoup(html, "html.parser")
    by_no: dict[int, dict[str, Any]] = {}

    for tr in soup.select("tr"):
        num_td = tr.select_one("td.num")
        horse_td = tr.select_one("td.horse")
        if not num_td or not horse_td:
            continue

        m = re.search(r"\d+", num_td.get_text(" ", strip=True))
        if not m:
            continue
        horse_no = int(m.group())
        if not 1 <= horse_no <= 18:
            continue

        odds_tag = horse_td.select_one(".odds strong")
        if not odds_tag:
            continue
        try:
            jra_odds = float(odds_tag.get_text(" ", strip=True))
        except ValueError:
            continue

        name_tag = horse_td.select_one(".name")
        horse_name = name_tag.get_text(" ", strip=True) if name_tag else ""

        popularity = None
        pop_tag = horse_td.select_one(".pop_rank")
        if pop_tag:
            pm = re.search(r"\d+", pop_tag.get_text(" ", strip=True))
            if pm:
                popularity = int(pm.group())

        by_no[horse_no] = {
            "horse_no": horse_no,
            "horse_name": horse_name,
            "jra_odds": jra_odds,
            "popularity": popularity,
        }

    if not by_no:
        raise RuntimeError("JRAページから単勝オッズを1頭も抽出できませんでした。")

    return [by_no[n] for n in sorted(by_no)]


def fetch_jra_win_odds_auto(
    date_yyyymmdd: str,
    venue_name: str,
    race_no: int,
    timeout: int = 20,
) -> tuple[list[dict[str, Any]], str]:
    """
    日付・開催場・RだけでJRA公式から単勝オッズを自動取得。
    URL末尾 /XX は推測せず、JRAの開催選択→レース選択から取得する。

    return:
        (odds_rows, resolved_race_url)
    """
    date_yyyymmdd = re.sub(r"\D", "", str(date_yyyymmdd))
    if not re.fullmatch(r"\d{8}", date_yyyymmdd):
        raise ValueError("日付はYYYYMMDDの8桁で指定してください。")
    race_no = int(race_no)
    if not 1 <= race_no <= 12:
        raise ValueError("レース番号は1～12Rで指定してください。")

    session = _new_session(timeout)

    meeting_url, meeting_html = _get_meeting_select(session, timeout)
    action_url, race_select_cname = _find_race_select_cname(
        meeting_html, meeting_url, date_yyyymmdd, venue_name
    )

    race_select_url, race_select_html = _get_race_select_page(
        session, action_url, race_select_cname, meeting_url, timeout
    )

    race_url = _find_race_url(
        race_select_html, race_select_url, date_yyyymmdd, venue_name, race_no
    )

    session.headers.update({"Referer": race_select_url})
    r = session.get(race_url, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    odds_rows = _extract_win_odds(_decode(r))
    return odds_rows, r.url


# 既存テスト/互換用途: URLを直接渡す方式も残す。
def fetch_jra_win_odds(race_url: str, timeout: int = 20) -> list[dict[str, Any]]:
    session = _new_session(timeout)
    r = session.get(race_url, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return _extract_win_odds(_decode(r))
