"""固定8条件のMATCH番号をWeb表示用コピーへだけ追加する。"""
_ORDER = (22, 18, 17, 1, 2, 3, 4, 8)


def add_s2_screen_comments(frame, record):
    display = frame.copy()
    if not record or record.get('status') != 'EVALUATED':
        return display
    report = record.get('report') or {}
    if (report.get('status') != 'EVALUATED' or report.get('research_only') is not True
            or report.get('prospective_ready') is not False
            or report.get('prospective_verified') is not False):
        return display
    matches = {}
    for item in report.get('condition_audit', []):
        entry = item.get('entry_id', '')
        number = item.get('condition_number')
        if (item.get('state') == 'MATCH' and item.get('and_passed') is True
                and number in _ORDER and item.get('race_id') == str(entry)[:16]):
            matches.setdefault(entry, set()).add(number)
    for index, row in frame.iterrows():
        numbers = matches.get(row.get('レースID'), set())
        if numbers:
            text = ' / '.join(f'No.{number}' for number in _ORDER if number in numbers)
            label = f'<span style="color: #7c3aed; font-weight: bold;">【{text}】</span>'
            current = str(row.get('総合評価・コース相性判定', '') or '')
            if label not in current:
                display.at[index, '総合評価・コース相性判定'] = f'{label} {current}'.strip()
    return display
