"""Optional Streamlit adapter for the cloud maintainer; no JRA fetch here."""
from pathlib import Path
from cushion_presentation import METRICS
from sire_stats import get_sire_stats
from sire_presentation import build_sire_records


def render_sire_tab(entrants, day, value, *, venue, distance, surface='芝',
                    snapshot_path=None, official_only=False):
    """Call inside a new st.tabs tab, passing the existing panel's current value."""
    import pandas as pd
    import streamlit as st
    if surface != '芝':
        st.info('芝レースのみ対象です。')
        return
    path = Path(snapshot_path) if snapshot_path else Path(__file__).resolve().parent / f'sire_history_{day}.sqlite'
    report, reason = None, f'種牡馬DBがありません。{path.name} をapp.pyと同じフォルダに配置してください。'
    if path.is_file():
        st.caption(f'種牡馬DBを自動読込：{path.name}')
        try:
            report = get_sire_stats(path,entrants,day,value,venue=venue,distance=distance,
                                    surface=surface,official_only=official_only)
        except Exception as exc:
            reason = f'種牡馬DBを利用できません：{exc}'
    records = build_sire_records(entrants,report,venue=venue,distance=distance,unavailable_reason=reason)
    if report:
        meta = report['metadata']
        st.caption(f"元DB収録期間：{meta['source_first_date']}～{meta['source_last_date']} ／ 対象日前の芝・同一競馬場・同距離・同区分")
    else:
        st.info(reason)
    st.caption('取消・除外は対象外、中止・失格は着外に含みます。内外・A/B/C/Dは分けず、走数5未満は参考値として表示します。')
    frame = pd.DataFrame(records)
    st.dataframe(frame.style.format({label:'{:.1f}' for label in METRICS},na_rep='—'),
                 hide_index=True,width='stretch',key='sire_stats_table')
    return records
