"""Build a separate, reproducible sire snapshot without modifying existing DBs."""
import argparse
from contextlib import closing
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import unicodedata

from cushion_stats import cushion_band, normalize_date, normalize_horse_id, readonly_connection
from sire_stats import SCHEMA_VERSION, normalize_sire

VENUES = dict(zip(('01','02','03','04','05','06','07','08','09','10'),
                  ('札幌','函館','福島','新潟','東京','中山','中京','京都','阪神','小倉')))


def publish_new(temporary, output):
    # Windows rename is atomic on the same volume and refuses an existing target.
    # POSIX rename replaces files, so use a no-replace hard link there instead.
    if os.name == 'nt':
        os.rename(temporary, output)
    else:
        os.link(temporary, output)


def read_sire_entrants(csv_path):
    raw = Path(csv_path).read_bytes()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('cp932')
    entrants, dates, seen_ids, seen_horses = [], set(), set(), set()
    for row in csv.reader(io.StringIO(text, newline='')):
        if not row:
            continue
        if len(row) < 18 or not re.fullmatch(r'[0-9]{18}', row[15]):
            raise ValueError('16列目TARGET ID・17列目血統登録番号・18列目騎手が必要です')
        target = row[15]
        horse = normalize_horse_id(row[16])
        if target in seen_ids or horse in seen_horses:
            raise ValueError('出馬表の出走IDまたは血統登録番号が重複しています')
        seen_ids.add(target)
        seen_horses.add(horse)
        dates.add(normalize_date(target[:8]))
        venue = VENUES.get(target[8:10])
        if not venue:
            raise ValueError('未対応の競馬場コードです: ' + target[8:10])
        distance = int(row[3])
        if distance <= 0 or int(row[5]) != int(target[-2:]):
            raise ValueError('距離またはTARGET IDと馬番の対応を確認してください')
        entrants.append(dict(horse_id=horse, target_id=target, horse_no=int(row[5]),
                             horse_name=row[7].strip(), sire_name=normalize_sire(row[19]) if len(row)>19 else '',
                             venue=venue, distance=distance, surface=row[2].strip()))
    if len(dates) != 1:
        raise ValueError('出馬表は単一開催日で指定してください')
    return entrants, dates.pop(), hashlib.sha256(raw).hexdigest()


def create_sire_snapshot(source_path, output_path, csv_path):
    started = time.perf_counter()
    source, output = Path(source_path).resolve(), Path(output_path).resolve()
    if output.exists() or output == source or output == Path(csv_path).resolve():
        raise ValueError('既存ファイルを上書きしません。新しい保存先を指定してください')
    entrants, day, csv_hash = read_sire_entrants(csv_path)
    db, temp_path = readonly_connection(source), None
    try:
        db.execute('BEGIN')
        first, last = db.execute('SELECT MIN(race_date),MAX(race_date) FROM races').fetchone()
        names = {normalize_sire(row[0]) for row in db.execute('SELECT DISTINCT sire_name FROM race_horses') if normalize_sire(row[0])}
        names.update(e['sire_name'] for e in entrants if e['sire_name'])
        canonical = {}
        for name in names:
            key = unicodedata.normalize('NFKC', name)
            if key in canonical and canonical[key] != name:
                raise ValueError(f'種牡馬名の表記衝突を確認してください: {name} / {canonical[key]}')
            canonical[key] = name
        for entrant in entrants:
            rows = db.execute('''SELECT DISTINCT h.sire_name FROM race_horses h JOIN races r USING(race_id)
                WHERE h.horse_registration_number=? AND r.race_date<?''', (entrant['horse_id'], day)).fetchall()
            known = {normalize_sire(row[0]) for row in rows if normalize_sire(row[0])}
            if len(known) > 1:
                raise ValueError('同じ血統登録番号に複数の父名があります: ' + entrant['horse_id'])
            if known and entrant['sire_name'] and entrant['sire_name'] not in known:
                raise ValueError('出馬表と元DBの父名が一致しません: ' + entrant['horse_id'])
            entrant['sire_source'] = 'ENTRANT_CSV_COLUMN20' if entrant['sire_name'] else ('SOURCE_DB_REGISTRATION' if known else 'UNKNOWN')
            entrant['sire_name'] = entrant['sire_name'] or next(iter(known), '')
        scopes = {(e['sire_name'],e['venue'],e['distance']) for e in entrants if e['surface']=='芝' and e['sire_name']}
        fd, temp_path = tempfile.mkstemp(prefix='.sire-', suffix='.sqlite', dir=output.parent)
        os.close(fd)
        with closing(sqlite3.connect(temp_path)) as dest, dest:
            dest.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            dest.execute('''CREATE TABLE entrant_sires(horse_registration_number TEXT PRIMARY KEY,
                target_id TEXT UNIQUE NOT NULL,horse_name TEXT,sire_name TEXT,sire_source TEXT)''')
            dest.executemany('INSERT INTO entrant_sires VALUES (?,?,?,?,?)',
                             [(e['horse_id'],e['target_id'],e['horse_name'],e['sire_name'],e['sire_source']) for e in entrants])
            dest.execute('CREATE TABLE scopes(sire_name TEXT,venue TEXT,distance INTEGER,PRIMARY KEY(sire_name,venue,distance))')
            dest.executemany('INSERT INTO scopes VALUES (?,?,?)', sorted(scopes))
            dest.execute('''CREATE TABLE sire_history(target_id TEXT PRIMARY KEY,race_id TEXT NOT NULL,
                horse_registration_number TEXT NOT NULL,sire_name TEXT NOT NULL,race_date TEXT NOT NULL,
                venue TEXT,surface TEXT,distance INTEGER,cushion_value REAL,cushion_band INTEGER,
                cushion_status TEXT,finish_position INTEGER,finish_status TEXT,bet_eligible INTEGER,
                win_return_yen REAL,place_return_yen REAL)''')
            dest.execute('CREATE TABLE anomalies(target_id TEXT,reason TEXT)')
            count, invalid = 0, 0
            for sire, venue, distance in sorted(scopes):
                sql = '''SELECT h.target_id,h.race_id,h.horse_registration_number,h.sire_name,r.race_date,
                    r.venue,r.surface,r.distance,r.cushion_value,r.cushion_status,h.finish_position,
                    h.finish_status,h.bet_eligible,h.win_return_yen,h.place_return_yen
                    FROM race_horses h JOIN races r USING(race_id) WHERE h.sire_name=?
                    AND r.venue=? AND r.surface='芝' AND r.distance=? AND r.race_date<?'''
                for row in db.execute(sql, (sire,venue,distance,day)):
                    try:
                        normalize_horse_id(row['horse_registration_number'])
                    except ValueError:
                        raise ValueError('産駒の血統登録番号欠損・形式不正: ' + row['target_id'])
                    band = None
                    if row['cushion_value'] is not None:
                        try:
                            band = cushion_band(row['cushion_value'])
                        except ValueError:
                            dest.execute('INSERT INTO anomalies VALUES (?,?)', (row['target_id'],'invalid_cushion'))
                            invalid += 1
                    values = tuple(row)
                    dest.execute('INSERT INTO sire_history VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', values[:9]+(band,)+values[9:])
                    count += 1
            dest.execute('CREATE INDEX ix_sire_course_band_date ON sire_history(sire_name,venue,distance,cushion_band,race_date)')
            metadata = dict(schema_version=SCHEMA_VERSION,target_date=day,source_first_date=first or '',
                            source_last_date=last or '',source_path=str(source),
                            source_size=str(source.stat().st_size),source_mtime_ns=str(source.stat().st_mtime_ns),
                            entrant_csv=str(Path(csv_path).resolve()),entrant_csv_sha256=csv_hash,
                            generated_at=datetime.now(timezone.utc).isoformat(),
                            requested_horses=str(len(entrants)),unknown_sires=str(sum(not e['sire_name'] for e in entrants)),
                            history_rows=str(count),scopes=str(len(scopes)),cushion_anomalies=str(invalid),
                            sire_identity='exact_name_trim_only_no_fuzzy_matching',
                            course_policy='venue+turf+distance; no rail or inner/outer filter',
                            source_policy='JRA_PDF_VERIFIED+CSV_PROVIDED; optional official_only',
                            stake_yen='100',generation_seconds=f'{time.perf_counter()-started:.3f}',
                            validation='unique_runner_ids; date<target; integrity_check')
            dest.executemany('INSERT INTO metadata VALUES (?,?)', metadata.items())
            if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('生成DBの整合性検証に失敗しました')
        # Publish only a completed, verified new file. Never replace a good DB.
        publish_new(temp_path, output)
        return metadata
    finally:
        db.close()
        if temp_path is not None:
            Path(temp_path).unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--entrants', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(create_sire_snapshot(args.source,args.output,args.entrants),ensure_ascii=False,indent=2))
