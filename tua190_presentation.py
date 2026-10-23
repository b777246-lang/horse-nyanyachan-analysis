"""Web出馬表だけに追加条件を表示する。元データ・CSV・HTML出力は変更しない。"""
LABEL = '【TUA190_DIRT・研究条件】'
_LABEL_HTML = f'<span style="color: #7c3aed; font-weight: bold;">{LABEL}</span>'


def add_tua190_screen_comments(frame, record):
    display = frame.copy()
    if not record or record.get('status') != 'EVALUATED':
        return display
    report = record.get('report') or {}
    if (report.get('status') != 'EVALUATED' or report.get('research_only') is not True
            or report.get('prospective_ready') is not False
            or report.get('prospective_verified') is not False):
        return display
    ids = {row['entry_id'] for row in report.get('audit', [])
           if row.get('condition_id') == 'TUA190_DIRT' and row.get('state') == 'MATCH'
           and row.get('and_passed') is True and row.get('race_id') == str(row.get('entry_id', ''))[:16]}
    for index, row in frame.iterrows():
        if row.get('レースID') in ids:
            current = str(row.get('総合評価・コース相性判定', '') or '')
            if LABEL not in current:
                display.at[index, '総合評価・コース相性判定'] = f'{_LABEL_HTML} {current}'.strip()
    return display
