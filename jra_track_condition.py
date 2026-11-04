"""Read the same official JSON used by JRA's baba2025.js; fail closed."""
from datetime import datetime
import json
from urllib.parse import urljoin, urlparse
import requests

from jra_cushion import Tree
from track_conditions import JST, CONDITIONS, make_record, valid_date

INDEX_URL = 'https://www.jra.go.jp/keiba/baba/'
SOURCE_URL = 'https://www.jra.go.jp/JRADB/accessJ.html'


def _request(session, method, url, **kwargs):
    for _ in range(4):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in ('www.jra.go.jp', 'jra.go.jp'):
            raise ValueError('JRA公式以外への転送を停止しました。')
        response = session.request(method, url, timeout=(4, 8), allow_redirects=False, **kwargs)
        if response.is_redirect:
            # Redirected POST semantics must not be guessed.
            if method != 'GET':
                raise ValueError('JRA取得先が変更されています。手動指定してください。')
            url = urljoin(url, response.headers['Location'])
            continue
        response.raise_for_status()
        return response
    raise ValueError('JRAの転送回数が上限を超えました。')


def venue_pages(html):
    tree = Tree(html)
    tabs = [n for n in tree.root.walk() if n.cls('kaisai_tab')]
    if len(tabs) != 1:
        raise ValueError('開催場一覧を確認できません。')
    pages = {}
    for node in tabs[0].walk():
        if node.tag == 'a' and node.text().endswith('競馬場'):
            venue = node.text()[:-3]
            if venue in pages:
                raise ValueError('開催場が重複しています。')
            pages[venue] = urljoin(INDEX_URL, node.attrs.get('href', ''))
    return pages


def course_slot(html):
    nodes = [n for n in Tree(html).root.walk() if n.attrs.get('id') == 'baba']
    if len(nodes) != 1 or nodes[0].attrs.get('data-current-course') not in ('A', 'B', 'C'):
        raise ValueError('開催場の識別情報を確認できません。')
    return nodes[0].attrs['data-current-course']


def select_records(payload, slot, day, venue, *, now=None):
    now = now or datetime.now(JST)
    if not valid_date(day) or day != now.astimezone(JST).strftime('%Y%m%d'):
        raise ValueError('自動取得は日本時間の当日分のみです。手動指定してください。')
    entries = payload.get('kaisai_info')
    if not isinstance(entries, list):
        raise ValueError('JRA馬場状態の形式を確認できません。')
    matches = [r for r in entries if isinstance(r, dict) and r.get('sort') == slot
               and str(r.get('kaisai_ymd', '')) == day]
    if len(matches) != 1:
        raise ValueError('当日の馬場状態が未公表、または開催日を照合できません。')
    result = []
    for surface, field in [('芝', 'ba_s'), ('ダ', 'ba_d')]:
        value = str(matches[0].get(field, '')).strip()
        if value not in CONDITIONS:
            raise ValueError('芝・ダートの馬場状態を確認できません。')
        result.append(make_record(day, venue, surface, value, source='jra', now=now, source_url=SOURCE_URL))
    return result


def fetch_jra_track_conditions(day, venue, *, now=None):
    now = now or datetime.now(JST)
    if not valid_date(day) or day != now.astimezone(JST).strftime('%Y%m%d'):
        raise ValueError('自動取得は日本時間の当日分のみです。手動指定してください。')
    with requests.Session() as session:
        session.headers.update({'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'ja',
                                'Referer': INDEX_URL, 'Cache-Control': 'no-cache'})
        index = _request(session, 'GET', INDEX_URL)
        html = index.content.decode('cp932')
        pages = venue_pages(html)
        if venue not in pages:
            raise ValueError('当週の開催場一覧にありません。手動指定してください。')
        response = _request(session, 'GET', pages[venue])
        slot = course_slot(response.content.decode('cp932'))
        response = _request(session, 'POST', SOURCE_URL, data={'CNAME': 'pw01iwtS3/CD'})
        return select_records(json.loads(response.content.decode('cp932')), slot, day, venue,
                              now=now if now else datetime.now(JST))
