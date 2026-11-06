"""Streamlit going controls, evaluated before special signals and exports."""
from datetime import datetime
from track_condition_schedule import run_scheduled
from jra_track_condition import fetch_jra_track_conditions
from track_conditions import (OPTIONS, JST, targets_from_frame, resolve_record,
                               record_key, make_record)


def render_track_conditions(st, frame):
    # Initialize new sessions only; preserve a user's explicit OFF choice.
    st.session_state.setdefault('going_auto_enabled', True)
    targets = targets_from_frame(frame)
    records = st.session_state.setdefault('track_conditions', {})
    # Expired official records must not be reused by a later rerun/export.
    for key in list(records):
        if not resolve_record(records, *key):
            records.pop(key, None)
    with st.sidebar.expander('馬場状態の取得・指定', expanded=True):
        st.caption('未取得の馬場条件は判定保留。芝とダートを別々に管理します。')
        if not targets:
            st.warning('TARGETレースIDから開催日・競馬場を確認できません。')
            return records
        day, venue = st.selectbox('開催日・競馬場', targets,
                                  format_func=lambda x:f'{x[0]} {x[1]}', key='going_target')
        prefix=f'going_{day}_{venue}'
        if st.button('JRA当日分を取得', key=prefix+'_fetch'):
            for surface in ('芝','ダ'):
                records.pop(record_key(day,venue,surface),None)
            try:
                for record in fetch_jra_track_conditions(day,venue):
                    records[record_key(day,venue,record['surface'])]=record
                st.success('JRA公式から取得しました。')
            except Exception as error:
                st.warning(str(error))
        for surface in ('芝','ダ'):
            record=resolve_record(records,day,venue,surface)
            label='ダート' if surface=='ダ' else '芝'
            if record:
                source='手動' if record['source']=='manual' else 'JRA公式・15分で失効'
                st.write(f"{label}：{record['value']}（{source} / {record['fetched_at'][11:16]}）")
            else:
                st.write(f'{label}：未取得（馬場条件は判定保留）')
        with st.form(prefix+'_manual'):
            values={surface:st.selectbox('手動：'+('ダート' if surface=='ダ' else '芝'),
                                          OPTIONS,key=prefix+'_'+surface) for surface in ('芝','ダ')}
            applied=st.form_submit_button('手動指定を適用')
        if applied:
            st.session_state['going_auto_enabled'] = False
            for surface,value in values.items():
                records.pop(record_key(day,venue,surface),None)
                if value!=OPTIONS[0]:records[record_key(day,venue,surface)]=make_record(day,venue,surface,value)
            st.rerun()
        st.caption('手動指定は選んだ日・競馬場の全レースに適用。天候変化時は再取得してください。')
        st.markdown('**15分おきの自動取得**')
        st.checkbox('9:30～16:30に自動取得する', key='going_auto_enabled')
        st.caption('日本時間9:30開始、15分おき、最終取得16:30（1開催場につき1日29回の取得枠）。')
        st.caption('対象：CSVに含まれる当日の全開催場。実行に最大約30秒の遅れがあります。')
        st.caption('画面を開いている間に動作します。iPhoneの画面ロック・他アプリへの切替・通信切断中の実行は保証されません。再開時は最新分だけ取得します。')
        st.caption('手動指定を適用すると自動取得を停止します。失敗時は旧値を使わず、次の15分枠で再試行します。')

        @st.fragment(run_every='30s' if st.session_state.get('going_auto_enabled') else None)
        def auto_tick():
            if run_scheduled(st.session_state, targets, fetch_jra_track_conditions):
                # Refresh the entire analysis and exports, not just the sidebar.
                st.rerun()
            if st.session_state.get('going_auto_enabled'):
                st.caption('自動取得：有効 / '+st.session_state.get('going_auto_status','指定時間帯の開始を待っています。'))
            else:
                st.caption('自動取得：停止中')

        auto_tick()
    return records
