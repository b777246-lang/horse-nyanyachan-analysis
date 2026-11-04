"""Date/venue/surface-scoped going records shared by Desktop and Web."""
from datetime import datetime, timedelta, timezone
import re

JST = timezone(timedelta(hours=9))
CONDITIONS = ('良', '稍重', '重', '不良')
OPTIONS = ('未取得',) + CONDITIONS
AUTO_MAX_AGE = timedelta(minutes=15)


def valid_date(day):
    try:
        return bool(re.fullmatch(r'[0-9]{8}', str(day))) and datetime.strptime(day, '%Y%m%d') is not None
    except (ValueError, TypeError):
        return False


def make_record(day, venue, surface, value, *, source='manual', now=None, source_url=''):
    if not valid_date(day) or not venue or surface not in ('芝', 'ダ') or value not in CONDITIONS:
        raise ValueError('開催日・競馬場・芝/ダート・馬場状態を確認してください。')
    if source not in ('manual', 'jra'):
        raise ValueError('未対応の取得元です。')
    return dict(race_date=day, venue=venue, surface=surface, value=value, source=source,
                fetched_at=(now or datetime.now(JST)).isoformat(), source_url=source_url)


def record_key(day, venue, surface):
    return (day, venue, surface)


def resolve_record(records, day, venue, surface, *, now=None):
    record = (records or {}).get(record_key(day, venue, surface))
    if not isinstance(record, dict):
        return None
    if any(record.get(k) != v for k, v in [('race_date', day), ('venue', venue), ('surface', surface)]):
        return None
    if record.get('value') not in CONDITIONS:
        return None
    if record.get('source') == 'manual':
        return record
    if record.get('source') != 'jra':
        return None
    try:
        current = now or datetime.now(JST)
        fetched = datetime.fromisoformat(record['fetched_at'])
        if day != current.astimezone(JST).strftime('%Y%m%d'):
            return None
        if not timedelta(0) <= current - fetched <= AUTO_MAX_AGE:
            return None
    except (ValueError, KeyError, TypeError):
        return None
    return record


def going_for(records, day, venue, surface, *, now=None):
    record = resolve_record(records, day, venue, surface, now=now)
    return record['value'] if record else None


def display_going(records, day, venue, surface):
    record = resolve_record(records, day, venue, surface)
    if record is None:
        return '馬場：未取得（馬場条件は判定保留）'
    source = '手動' if record['source'] == 'manual' else 'JRA'
    return f"馬場：{record['value']}（{source} {record['fetched_at'][11:16]}）"


def targets_from_frame(frame):
    """Use TARGET IDs only; missing/mixed dates are never guessed from labels."""
    from data_loader import normalize_main_frame
    venues = dict(zip(('01','02','03','04','05','06','07','08','09','10'),
                      ('札幌','函館','福島','新潟','東京','中山','中京','京都','阪神','小倉')))
    result = set()
    for _, row in normalize_main_frame(frame).iterrows():
        race_id = str(row.get('race_id', '')).strip()
        if re.fullmatch(r'[0-9]{18}(?:\.0)?', race_id) and valid_date(race_id[:8]):
            venue = venues.get(race_id[8:10])
            surface = str(row.get('surface', ''))
            if venue and surface in ('芝', 'ダ'):
                result.add((race_id[:8], venue))
    return sorted(result)
