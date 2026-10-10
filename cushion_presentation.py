"""Shared display records for Streamlit and Desktop; no UI imports."""
from cushion_stats import normalize_horse_id

REASONS = {
    'cushion_unavailable': '当日のクッション値未取得',
    'no_matching_history': '同区分の対象過去走なし',
    'horse_not_in_snapshot': '軽量DBの収録対象外',
}
METRICS = {'勝率(%)': 'win_rate', '連対率(%)': 'quinella_rate', '複勝率(%)': 'place_rate',
           '単回収率(%)': 'win_roi', '複回収率(%)': 'place_roi'}


def build_viewer_records(entrants, report=None, unavailable_reason='軽量DB未読込'):
    """Shared display mapping; retain entrants even when IDs/history are missing."""
    stats = {row['horse_id']: row for row in report['horses']} if report else {}
    records = []
    for horse in entrants:
        horse_id = horse.get('horse_id', '')
        try:
            horse_id = normalize_horse_id(horse_id)
            reason = unavailable_reason
        except ValueError:
            horse_id, reason = '', '血統登録番号未取得・形式不正'
        result = stats.get(horse_id)
        if result:
            reason = REASONS.get(result['reason'], '')
            if result['issues']:
                reason = (reason + '／' if reason else '') + f"要確認データ{len(result['issues'])}件"
        record = {'馬番': int(horse['horse_no']), '馬名': horse['horse_name'],
                  '着別度数': result['finish_counts'] if result else '0-0-0-0/0'}
        record.update({label: result[key] if result else None for label, key in METRICS.items()})
        record.update({'対象走数': result['starts'] if result else 0,
                       '中止': result['dnf'] if result else 0, '失格': result['disqualified'] if result else 0,
                       '備考': reason})
        records.append(record)
    return sorted(records, key=lambda row: row['馬番'])
