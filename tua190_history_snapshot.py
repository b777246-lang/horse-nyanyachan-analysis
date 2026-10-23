"""Create a date-scoped, append-free history DB for TUA190_DIRT Web evaluation."""
import argparse
from contextlib import closing
import csv
import hashlib
import io
import os
from pathlib import Path
import sqlite3
import tempfile

from s2_shared.adapter import convert_bytes


def _sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def create_snapshot(source_path, csv_path, output_path):
    source, csv_path, output = map(lambda value: Path(value).resolve(),
                                   (source_path, csv_path, output_path))
    if output.exists() or output in (source, csv_path):
        raise ValueError('既存ファイルを上書きしません。新しい保存先を指定してください。')
    raw = csv_path.read_bytes()
    converted = convert_bytes(raw)
    if not converted['complete']:
        raise ValueError('元21列CSVが不正です: ' + str(converted['errors'][:3]))
    doc = converted['document']
    dates = sorted({race['date'] for race in doc['races']})
    if len(dates) != 1:
        raise ValueError('Web用軽量DBは単一開催日のCSVで生成してください。')
    horse_ids = sorted({horse['horse_id'] for race in doc['races'] for horse in race['horses']})
    target_date = dates[0]
    source_stat = source.stat()
    if Path(str(source) + '-wal').exists():
        raise ValueError('元DBにWALが存在するため、単一ファイルの同一性を保証できません。')
    source_sha = _sha_file(source)
    src = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    src.row_factory = sqlite3.Row
    src.execute('PRAGMA query_only=ON')
    temp_path = None
    try:
        first_date = src.execute('SELECT MIN(race_date) FROM races').fetchone()[0]
        latest_prior = src.execute(
            'SELECT MAX(race_date) FROM races WHERE race_date < ?', (target_date,)
        ).fetchone()[0]
        fd, temp_path = tempfile.mkstemp(prefix='.tua190-', suffix='.sqlite', dir=output.parent)
        os.close(fd)
        with closing(sqlite3.connect(temp_path)) as dst, dst:
            dst.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            dst.execute('CREATE TABLE requested_horses '
                        '(horse_registration_number TEXT PRIMARY KEY)')
            dst.executemany('INSERT INTO requested_horses VALUES (?)',
                            ((horse_id,) for horse_id in horse_ids))
            dst.execute('''CREATE TABLE history (
                horse_registration_number TEXT NOT NULL,target_id TEXT PRIMARY KEY,
                race_id TEXT NOT NULL,race_date TEXT NOT NULL,surface TEXT,
                finish_position INTEGER,popularity INTEGER,finish_status TEXT NOT NULL)''')
            rows = 0
            for start in range(0, len(horse_ids), 500):
                batch = horse_ids[start:start + 500]
                marks = ','.join('?' for _ in batch)
                sql = f'''SELECT h.horse_registration_number,h.target_id,h.race_id,
                                 r.race_date,r.surface,h.finish_position,h.popularity,h.finish_status
                          FROM race_horses h JOIN races r USING(race_id)
                          WHERE h.horse_registration_number IN ({marks}) AND r.race_date<?'''
                selected = src.execute(sql, (*batch, target_date)).fetchall()
                dst.executemany('INSERT INTO history VALUES (?,?,?,?,?,?,?,?)',
                                (tuple(row) for row in selected))
                rows += len(selected)
            dst.execute('CREATE INDEX ix_tua190_history_horse_date '
                        'ON history(horse_registration_number,race_date)')
            metadata = {
                'schema_version': 'tua190-history-1', 'target_date': target_date,
                'input_dates': ','.join(dates), 'input_csv_sha256': hashlib.sha256(raw).hexdigest(),
                'source_db_sha256': source_sha, 'source_db_bytes': str(source.stat().st_size),
                'source_first_date': first_date or '', 'source_latest_prior_date': latest_prior or '',
                'requested_horses': str(len(horse_ids)), 'history_rows': str(rows),
                'career_policy': 'JRA flat turf+dirt starts before target; CANCELLED/EXCLUDED excluded',
                'previous_policy': 'latest JRA actual start; NULL finish/popularity is UNCONFIRMED',
                'research_only': 'true', 'prospective_ready': 'false',
                'prospective_verified': 'false',
            }
            dst.executemany('INSERT INTO metadata VALUES (?,?)', metadata.items())
        # Publish without replacing an existing file on both Windows and POSIX.
        after = source.stat()
        if (after.st_size != source_stat.st_size or after.st_mtime_ns != source_stat.st_mtime_ns
                or _sha_file(source) != source_sha):
            raise ValueError('軽量DB生成中に元DBが変更されました。')
        if csv_path.read_bytes() != raw:
            raise ValueError('軽量DB生成中に元21列CSVが変更されました。')
        os.link(temp_path, output)
        Path(temp_path).unlink()
        temp_path = None
        return {**metadata, 'output_path': str(output),
                'output_sha256': _sha_file(output)}
    finally:
        src.close()
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='TUA190_DIRT用・日付時点履歴軽量DB')
    parser.add_argument('source_db')
    parser.add_argument('csv21')
    parser.add_argument('output')
    args = parser.parse_args(argv)
    result = create_snapshot(args.source_db, args.csv21, args.output)
    print('\n'.join(f'{key}: {value}' for key, value in result.items()))


if __name__ == '__main__':
    main()
