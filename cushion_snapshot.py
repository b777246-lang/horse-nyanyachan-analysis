"""Export selected entrants' per-run history from a read-only source DB."""
import argparse
from contextlib import closing
import csv
import json
import io
import os
from pathlib import Path
import sqlite3
import tempfile

from cushion_stats import cushion_band, normalize_date, normalize_horse_id, readonly_connection

COLUMNS = ('horse_registration_number', 'target_id', 'race_id', 'horse_number', 'horse_name',
           'finish_position', 'finish_status', 'bet_eligible', 'win_return_yen', 'place_return_yen',
           'race_date', 'venue', 'surface', 'distance', 'course', 'track_condition', 'track_condition_raw',
           'cushion_value', 'cushion_status')


def create_snapshot(source_path, output_path, horse_ids, race_date):
    source, output = Path(source_path).resolve(), Path(output_path).resolve()
    if source == output or output.exists():
        raise ValueError('既存DBを上書きしません。新しい出力先を指定してください')
    ids = list(dict.fromkeys(normalize_horse_id(v) for v in horse_ids))
    day = normalize_date(race_date)
    if not ids:
        raise ValueError('出走馬が指定されていません')
    source_db = readonly_connection(source)
    temp_path = None
    try:
        source_db.execute('BEGIN')
        last_date = source_db.execute('SELECT MAX(race_date) FROM races').fetchone()[0]
        first_date = source_db.execute('SELECT MIN(race_date) FROM races').fetchone()[0]
        fd, temp_path = tempfile.mkstemp(prefix='.cushion-', suffix='.sqlite', dir=output.parent)
        os.close(fd)
        # sqlite3 context managers commit/rollback but do not close the file.
        with closing(sqlite3.connect(temp_path)) as destination, destination:
            destination.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            destination.execute('CREATE TABLE requested_horses (horse_registration_number TEXT PRIMARY KEY)')
            destination.executemany('INSERT INTO requested_horses VALUES (?)', [(horse,) for horse in ids])
            destination.execute('''CREATE TABLE history (
                horse_registration_number TEXT NOT NULL, target_id TEXT PRIMARY KEY, race_id TEXT NOT NULL,
                horse_number INTEGER, horse_name TEXT, finish_position INTEGER, finish_status TEXT,
                bet_eligible INTEGER, win_return_yen REAL, place_return_yen REAL, race_date TEXT NOT NULL,
                venue TEXT, surface TEXT, distance INTEGER, course TEXT, track_condition TEXT,
                track_condition_raw TEXT, cushion_value REAL, cushion_status TEXT, cushion_band INTEGER)''')
            destination.execute('CREATE TABLE anomalies (target_id TEXT, reason TEXT, original_value TEXT)')
            count, anomalies = 0, 0
            select = ','.join('h.' + c for c in COLUMNS[:10]) + ',' + ','.join('r.' + c for c in COLUMNS[10:])
            for start in range(0, len(ids), 500):
                batch = ids[start:start + 500]
                sql = f"SELECT {select} FROM race_horses h JOIN races r USING(race_id) WHERE h.horse_registration_number IN ({','.join('?' for _ in batch)}) AND r.race_date < ?"
                for row in source_db.execute(sql, (*batch, day)):
                    band = None
                    if row['cushion_value'] is not None:
                        try:
                            band = cushion_band(row['cushion_value'])
                        except ValueError:
                            destination.execute('INSERT INTO anomalies VALUES (?,?,?)', (row['target_id'], 'invalid_cushion', str(row['cushion_value'])))
                            anomalies += 1
                    destination.execute(f"INSERT INTO history VALUES ({','.join('?' for _ in range(20))})", (*row, band))
                    count += 1
            destination.execute('CREATE INDEX ix_history_horse_date ON history(horse_registration_number,race_date)')
            metadata = {'schema_version': '1', 'target_date': day, 'source_first_date': first_date or '',
                        'source_last_date': last_date or '', 'requested_horses': str(len(ids)),
                        'history_rows': str(count), 'cushion_anomalies': str(anomalies),
                        'stake_yen': '100', 'finish_policy': 'DNF/DISQUALIFIED count as unplaced; actual payouts',
                        'cushion_source_policy': 'JRA_PDF_VERIFIED and CSV_PROVIDED; configurable official-only'}
            destination.executemany('INSERT INTO metadata VALUES (?,?)', metadata.items())
        # Hard link publishes the completed file atomically without overwriting an existing file.
        os.link(temp_path, output)
        return metadata
    finally:
        source_db.close()
        if temp_path is not None:
            Path(temp_path).unlink(missing_ok=True)


def read_entrants(csv_path):
    ids, days = [], set()
    raw = Path(csv_path).read_bytes()
    try:
        decoded = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        decoded = raw.decode('cp932')
    with io.StringIO(decoded, newline='') as stream:
        for row in csv.reader(stream):
            if not row:
                continue
            if len(row) < 18 or len(row[15]) != 18 or not row[15].isascii() or not row[15].isdigit():
                raise ValueError('18列形式の出馬表CSVが必要です（16列目ID・17列目血統登録番号）')
            days.add(normalize_date(row[15][:8]))
            ids.append(normalize_horse_id(row[16]))
    if len(days) != 1:
        raise ValueError('CSVは単一開催日で指定してください')
    return ids, days.pop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--entrants', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    ids, day = read_entrants(args.entrants)
    print(json.dumps(create_snapshot(args.source, args.output, ids, day), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
