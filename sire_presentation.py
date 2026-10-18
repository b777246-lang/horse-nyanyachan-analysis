"""Shared Web/Desktop display records for the separate sire tab."""
from cushion_presentation import METRICS

REASONS = dict(sire_unknown='種牡馬不明',invalid_horse_id='血統登録番号未取得・形式不正',
               horse_not_in_snapshot='種牡馬DBの収録対象外',sire_mismatch='出馬表と種牡馬DBの父名が不一致',
               course_not_in_snapshot='種牡馬DBの収録コース外',surface_not_supported='芝のみ対象',
               cushion_unavailable='当日クッション値未取得・判定不可')


def build_sire_records(entrants, report=None, *, venue='', distance=0, unavailable_reason='種牡馬DB未読込'):
    rows = report['horses'] if report else [dict(e,stats=None,reason=None) for e in entrants]
    records = []
    for row in rows:
        stats = row.get('stats')
        reason = REASONS.get(row.get('reason'),row.get('reason') or '') if report else unavailable_reason
        if stats:
            if not stats['starts']:
                reason = '同一芝コース・同区分の産駒成績なし'
            elif stats['starts'] < 5:
                reason = '対象走数が少ないため参考値'
            if stats['issues']:
                reason += ('／' if reason else '') + f"要確認データ{len(stats['issues'])}件"
        record = {'馬番':int(row['horse_no']),'馬名':row['horse_name'],
                  '種牡馬':row.get('sire_name') or '不明',
                  '産駒着別度数':stats['finish_counts'] if stats else '—'}
        record.update({label:stats[key] if stats else None for label,key in METRICS.items()})
        record.update({'対象走数':stats['starts'] if stats else None,'備考':reason})
        records.append(record)
    return sorted(records,key=lambda x:x['馬番'])
