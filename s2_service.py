"""S2の非表示・研究用接続。既存の評価、コメント、表示、出力へ結果を渡さない。"""
import hashlib
from pathlib import Path

STATE_KEY = '_s2_internal_audit'
CONNECTION_VERSION = 's2-hidden-1'
_PACKAGE_FILES = (
    '__init__.py', '__main__.py', 'adapter.py', 'api.py', 'course_registry.py',
    'detector.py', 'storage.py', 'data/formal24.json', 'data/manifest.json',
    'data/manifest.sha256',
)


def _package_signature():
    """判定コード・正本が差し替わったら同一CSVでも古い結果を流用しない。"""
    root = Path(__file__).resolve().parent / 's2_shared'
    digest = hashlib.sha256(CONNECTION_VERSION.encode('ascii'))
    for name in _PACKAGE_FILES:
        digest.update(name.encode('utf-8') + b'\0')
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def update_s2_audit(content, state):
    """全レース・全馬の元CSV bytesを評価し、セッション内に最新入力1件だけ保持。

    S2の入力拒否・読込エラーを旧判定へ伝播しない。CSV切替時は必ず以前の
    結果を置換し、失敗をNO_MATCHや古い正常結果で代替しない。
    """
    if content is None:
        state.pop(STATE_KEY, None)
        return None
    record = {
        'input_sha256': hashlib.sha256(content).hexdigest(),
        'connection_version': CONNECTION_VERSION,
        'package_sha256': None,
        'status': 'ERROR',
        'research_only': True,
        'prospective_ready': False,
        'prospective_verified': False,
        'report': None,
        'error': None,
    }
    try:
        record['package_sha256'] = _package_signature()
        previous = state.get(STATE_KEY)
        if (previous is not None and previous.get('error') is None
                and previous.get('input_sha256') == record['input_sha256']
                and previous.get('package_sha256') == record['package_sha256']
                and previous.get('connection_version') == CONNECTION_VERSION):
            return previous
        # 依存の読込失敗もS2内で扱うため、公開APIをここでimportする。
        from s2_shared import evaluate_csv_bytes
        report = evaluate_csv_bytes(content)
        if (report['research_only'] is not True or report['prospective_ready'] is not False
                or report['prospective_verified'] is not False):
            raise ValueError('S2 research/prospective flags must remain research-only/false')
        record['status'] = report['status']
        record['report'] = report
    except Exception as exc:
        record['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    state[STATE_KEY] = record
    return record
