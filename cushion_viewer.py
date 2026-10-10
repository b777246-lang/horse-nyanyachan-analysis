"""Streamlit cushion panel and shared presentation records."""
from pathlib import Path
import re
import sqlite3
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import requests
from jra_cushion import fetch_jra_cushion

from cushion_stats import BAND_LABELS, cushion_band, get_cushion_stats, normalize_date, normalize_horse_id

from cushion_presentation import METRICS, build_viewer_records


@st.cache_data(ttl=120, show_spinner=False)
def _cached_jra_cushion(day, venue, observation_date):
    return fetch_jra_cushion(day, venue)


def cached_jra_cushion(day, venue):
    # Change cache identity at Japanese midnight, even within the TTL.
    observation_date = datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y%m%d')
    return _cached_jra_cushion(day, venue, observation_date)


cached_jra_cushion.clear = _cached_jra_cushion.clear


def render_cushion_panel(view_df, main_frame, venue, race_no):
    with st.expander('🌱 クッション値別 過去成績', expanded=False):
        if race_no == 'ALL':
            st.info('レース番号を選択すると、出走全馬のクッション値別成績を表示します。')
            return
        selected = main_frame.loc[view_df['original_index'].tolist()]
        if set(selected['surface'].astype(str).str.strip()) != {'芝'}:
            st.info('ダートレースは芝クッション値別成績の対象外です。')
            return
        ids = selected['race_id'].fillna('').astype(str).str.strip()
        days = {value[:8] for value in ids if re.fullmatch(r'[0-9]{18}', value)}
        if len(days) != 1 or not ids.str.fullmatch(r'[0-9]{18}').all():
            st.warning('開催日を確認できません。16列目の18桁レースIDを確認してください。')
            return
        try:
            day = normalize_date(days.pop())
        except ValueError as exc:
            st.warning(str(exc))
            return
        st.caption(f'{day[:4]}/{day[4:6]}/{day[6:]} {venue}{race_no}R')
        entrants = [{'horse_no': row['horse_no'], 'horse_name': row['horse_name'],
                     'horse_id': row['horse_id']} for _, row in selected.iterrows()]
        upload = st.file_uploader('クッション値履歴の軽量DB', type=['sqlite', 'sqlite3', 'db'], key='cushion_snapshot_upload')
        local_path = Path(f'cushion_history_{day}.sqlite')
        mode = st.radio('クッション値の取得方法', ['JRA自動取得', '手動入力'], horizontal=True, key='cushion_input_mode')
        if st.button('🔄 クッション値を再取得', key='cushion_refresh', disabled=mode != 'JRA自動取得'):
            cached_jra_cushion.clear()
        st.caption('手動指定する場合は取得方法を切り替え、当日の公表値を入力してください。')
        value_text = st.text_input('当日のクッション値', key=f'cushion_value_{day}_{venue}', placeholder='例：9.2', disabled=mode != '手動入力')
        official_only = st.checkbox('JRA公式照合済みの過去走のみ', key='cushion_official_only')
        value = None
        if mode == 'JRA自動取得':
            try:
                with st.spinner('JRAのクッション値を確認しています'):
                    fetched = cached_jra_cushion(day, venue)
                value = fetched['value']
                if value is not None:
                    st.caption(f"JRA測定日時：{fetched['measurement_text']} ／ 取得日時：{fetched['fetched_at']}")
                    st.caption(fetched['year_basis'])
                    st.markdown(f"[JRA取得元]({fetched['source_url']})")
                else:
                    st.info(fetched['message'])
            except (requests.RequestException, ValueError, UnicodeError, KeyError) as exc:
                st.warning(f'JRAクッション値を取得できません：{exc}。再取得または手動入力をご利用ください。')
        elif value_text.strip():
            try:
                band = cushion_band(value_text.strip())
                value = value_text.strip()

            except ValueError as exc:
                st.warning(str(exc))
        else:
            st.info('当日のクッション値は未取得です。公表前の値や前開催日の値では代用しません。')
        if value is not None:
            st.write(f'クッション値：{value}　適用区分：{BAND_LABELS[cushion_band(value) - 1]}')
        report = None
        reason = '軽量DB未読込'
        valid_ids = []
        for horse in entrants:
            try:
                valid_ids.append(normalize_horse_id(horse['horse_id']))
            except ValueError:
                pass
        try:
            if upload is not None:
                if upload.size > 32 * 1024 * 1024:
                    raise ValueError('軽量DBは32MB以内で指定してください。元の巨大DBではなく、生成した軽量DBを使用してください。')
                with tempfile.TemporaryDirectory(prefix='cushion-viewer-') as folder:
                    path = Path(folder) / 'history.sqlite'
                    path.write_bytes(upload.getvalue())
                    report = get_cushion_stats(path, valid_ids, day, value, official_only=official_only)
            elif local_path.is_file():
                report = get_cushion_stats(local_path, valid_ids, day, value, official_only=official_only)
            else:
                st.info('前日に生成した軽量DBを選択するか、当日用の軽量DBをアプリと同じフォルダに配置してください。')
        except (ValueError, sqlite3.Error, OSError, KeyError) as exc:
            reason = '軽量DBを利用できません'
            st.warning(f'{reason}：{exc}')
        if report:
            metadata = report['metadata']
            first, last = metadata.get('source_first_date', ''), metadata.get('source_last_date', '')
            st.caption(f'過去DB収録期間：{first}～{last} ／ 集計は{day}より前の芝・同区分のみ')
            if last and last < day:
                st.caption(f'収録最終日：{last}。それ以降の未収録走は含まれません。')
            st.caption('中止・失格は着外として集計。CSV提供値は公式照合済み値と区別して保持しています。')
        records = build_viewer_records(entrants, report, reason)
        frame = pd.DataFrame(records)
        sort_by = st.selectbox('成績の表示順', ['馬番'] + list(METRICS) + ['対象走数'], key='cushion_sort')
        frame = frame.sort_values([sort_by, '馬番'] if sort_by != '馬番' else ['馬番'],
                                  ascending=[False, True] if sort_by != '馬番' else True, na_position='last')
        st.dataframe(frame.style.format({label: '{:.1f}' for label in METRICS}, na_rep='—'),
                     hide_index=True, width='stretch', key='cushion_stats_table')
        st.caption('列見出しでも並べ替えできます。表が横幅に収まらない場合は横スクロールしてください。')
