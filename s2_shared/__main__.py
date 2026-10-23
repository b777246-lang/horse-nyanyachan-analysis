"""Research CLI; read CP932 CSV from file or stdin, write audit JSON to stdout."""
import argparse
from pathlib import Path
import sys

from . import evaluate_csv_bytes
from .storage import encode


def main():
    parser = argparse.ArgumentParser(description='研究・照合専用。実運用への接続なし。')
    parser.add_argument('csv', help='CP932 CSV21 path, or - for stdin')
    args = parser.parse_args()
    raw = sys.stdin.buffer.read() if args.csv == '-' else Path(args.csv).read_bytes()
    result = evaluate_csv_bytes(raw)
    sys.stdout.buffer.write(encode(result) + b'\n')
    return 0 if result['status'] == 'EVALUATED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
