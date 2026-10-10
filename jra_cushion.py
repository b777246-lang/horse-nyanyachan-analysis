"""JRA official cushion retrieval; parser adapted from the supplied extract script."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlparse

import requests
from cushion_stats import cushion_band, normalize_date

SOURCE_URL = 'https://www.jra.go.jp/keiba/baba/_data_cushion.html'
JST = timezone(timedelta(hours=9), name='Asia/Tokyo')

class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children, self.parts = tag, dict(attrs), [], []
    def text(self):
        return ''.join(x.text() if isinstance(x, Node) else x for x in self.parts).strip()
    def walk(self):
        yield self
        for n in self.children:
            yield from n.walk()
    def cls(self, name):
        return name in self.attrs.get('class', '').split()


class Tree(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)
    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs)
        self.stack[-1].children.append(n)
        self.stack[-1].parts.append(n)
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.stack.append(n)
    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break
    def handle_data(self, data):
        self.stack[-1].parts.append(data)


def extract(html):
    tree = Tree(html)
    roots = [n for n in tree.root.walk() if n.attrs.get('id') == 'cushion_data_list']
    if len(roots) != 1:
        raise ValueError('cushion_data_listを一意に確認できません')
    rows = []
    for block in roots[0].children:
        units = [n for n in block.children if n.cls('unit')]
        if not units:
            continue
        venue = block.attrs.get('title', '').strip()
        if not venue:
            raise ValueError('競馬場titleがありません。位置からは推測しません')
        for unit in units:
            fields = {}
            for key in ('time', 'cushion'):
                matches = [n for n in unit.children if n.cls(key)]
                if len(matches) != 1:
                    raise ValueError(f'{venue}: {key}が一意ではありません')
                fields[key] = matches[0].text()
            m = re.fullmatch(r'(\d{1,2})月(\d{1,2})日[（(]([月火水木金土日])曜[）)]\s*(\d{1,2})時(\d{1,2})分', fields['time'])
            if not m:
                raise ValueError('未確認の測定日時形式: ' + fields['time'])
            month, day, weekday, hour, minute = m.groups()
            datetime(2000, int(month), int(day), int(hour), int(minute))
            if not re.fullmatch(r'\d+(?:\.\d+)?', fields['cushion']) or Decimal(fields['cushion']) <= 0:
                raise ValueError('数値形式を確認できません: ' + fields['cushion'])
            rows.append({'venue': venue, 'source_block': block.attrs.get('id',''),
                         'measurement_text': fields['time'], 'year': '', 'year_status': '未確認',
                         'month': int(month), 'day': int(day), 'weekday': weekday,
                         'hour': int(hour), 'minute': int(minute), 'cushion': fields['cushion']})
    if not rows:
        raise ValueError('測定レコードがありません')
    seen = set()
    for row in rows:
        key = (row['venue'], row['measurement_text'])
        if key in seen:
            raise ValueError('測定日時が重複しています: ' + str(key))
        seen.add(key)
    return rows



def select_current_record(rows, race_date, venue, fetched_at):
    """The page has no year: only a fresh response for today's JST date is accepted."""
    day = normalize_date(race_date)
    now = fetched_at.astimezone(JST)
    base = {'value': None, 'source_url': SOURCE_URL, 'fetched_at': now.isoformat(),
            'race_date': day, 'venue': venue, 'year_basis': '取得日の日本時間・月日・曜日による照合（公表HTMLに年なし）'}
    if day != now.strftime('%Y%m%d'):
        return dict(base, status='date_unavailable', message='自動取得は日本時間の当日開催のみ対応します。過去・翌日の値は手動で指定してください。')
    matches = [row for row in rows if row['venue'] == venue and (row['month'], row['day']) == (now.month, now.day)]
    if not matches:
        return dict(base, status='not_published', message='当日分は未公表、または掲載されていません。午前9時過ぎ以降に再取得してください。')
    for row in matches:
        if row['weekday'] != '月火水木金土日'[now.weekday()]:
            raise ValueError('測定日の曜日が当日と一致しません')
        cushion_band(row['cushion'])
        if (row['hour'], row['minute']) > (now.hour, now.minute):
            raise ValueError('測定時刻が取得時刻より未来です')
    chosen = max(matches, key=lambda row: (row['hour'], row['minute']))
    return dict(base, value=chosen['cushion'], status='available', message='',
                measurement_text=chosen['measurement_text'])


def fetch_jra_cushion(race_date, venue, *, now=None):
    fetched_at = now or datetime.now(timezone.utc)
    # Reject historical/future requests before any network operation.
    if normalize_date(race_date) != fetched_at.astimezone(JST).strftime('%Y%m%d'):
        return select_current_record([], race_date, venue, fetched_at)
    url = SOURCE_URL
    with requests.Session() as session:
        session.headers.update({'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'ja'})
        for _ in range(6):
            parsed = urlparse(url)
            if parsed.scheme != 'https' or parsed.hostname not in {'www.jra.go.jp', 'jra.go.jp'}:
                raise ValueError('JRA公式以外への転送を停止しました')
            response = session.get(url, timeout=(5, 15), allow_redirects=False)
            if response.is_redirect:
                url = urljoin(url, response.headers['Location'])
                continue
            response.raise_for_status()
            rows = extract(response.content.decode('cp932', errors='strict'))
            result = select_current_record(rows, race_date, venue, now or datetime.now(timezone.utc))
            result['source_url'] = url
            return result
    raise ValueError('JRAのリダイレクト回数が上限を超えました')
