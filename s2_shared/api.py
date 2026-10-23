"""Non-writing public API around the pinned adapter and detector."""
import csv
import io
from decimal import Decimal

from . import adapter, detector


def _parents(details, ranks):
    out = {}
    for side, parent in details.items():
        item = dict(parent)
        rank = ranks.get(parent['index_code'], {}).get('rank')
        # A/B/C share the same all-registered competition rank. B/C add cutoffs.
        item['abc_ranks'] = {model: rank for model in ('A', 'B', 'C')}
        failures = []
        if parent['passed'] is False:
            if not parent['rank_min'] <= parent['rank'] <= parent['rank_max']:
                failures.append('RANK_OUTSIDE_1_TO_3')
            threshold = parent['threshold']
            if threshold is not None and Decimal(parent['raw_value']) < Decimal(threshold):
                failures.append('VALUE_BELOW_THRESHOLD')
        item['failure_reasons'] = failures
        out[side] = item
    return out


def evaluate_csv_bytes(content, *, metadata=None):
    """Accept complete CP932 CSV21 bytes; return all eight audits for every horse.

    Invalid CSV never enters the detector. No files, network, UI or odds are used.
    Missing official roster/acquisition evidence never becomes prospective proof.
    """
    if not isinstance(content, bytes):
        raise TypeError('content must be bytes; use evaluate_csv_text or evaluate_rows')
    # Both original manifest byte hashes are verified even for rejected input.
    definitions = detector.definitions()
    conversion = adapter.convert_bytes(content, metadata)
    validation = {k: v for k, v in conversion.items() if k != 'document'}
    envelope = {
        'package_version': '1.0.0',
        'run_kind': 'retrospective_test',
        'research_only': True,
        'prospective_ready': False,
        'prospective_verified': False,
        'status': 'EVALUATED' if conversion['complete'] else 'INVALID_INPUT',
        'validation': validation,
        'research_result': None,
        'condition_audit': [],
    }
    doc = conversion['document']
    if not conversion['complete']:
        # Keep identifiable horses as indeterminate, never as negative matches.
        for race in (doc or {}).get('races', []):
            for horse in race['horses']:
                for definition in definitions:
                    details = {}
                    for side, parent in definition['parents'].items():
                        details[side] = {
                            'index_code': parent['code'], 'model': parent['model'],
                            'raw_value': horse['indexes'][parent['code']]['raw_value'],
                            'rank': None, 'rank_min': 1, 'rank_max': 3,
                            'threshold': parent['threshold'],
                            'operator': parent['value_operator'], 'passed': None,
                        }
                    envelope['condition_audit'].append({
                        'race_id': race['race_id'], 'entry_id': horse['entry_id'],
                        'horse_id': horse['horse_id'], 'horse_no': horse['horse_no'],
                        'condition_number': definition['number'],
                        'condition_id': definition['condition_id'],
                        'state': 'INVALID_INPUT', 'and_passed': None,
                        'parents': _parents(details, {}),
                        'failure_reasons': [],
                        'indeterminate_reasons': ['CSV_VALIDATION_FAILED'],
                    })
        return envelope
    provenance = {
        'input_csv_sha256': doc['source']['sha256'],
        'formal_manifest_sha256': detector.FORMAL_SHA,
        'eight_manifest_sha256': detector.EIGHT_SHA,
        'input_adapter_version': doc['adapter_version'],
        'metadata_registry_version': doc['registry_version'],
    }
    result = detector.evaluate_document(doc, defs=definitions, provenance=provenance)
    rank_map = {h['entry_id']: h['indexes'] for h in result['all_registered_ranks']}
    for horse in result['horse_conditions']:
        details = _parents(horse['parents'], rank_map[horse['entry_id']])
        record = dict(horse)
        record['parents'] = details
        record['failure_reasons'] = [
            side + ':' + reason
            for side, parent in details.items() for reason in parent['failure_reasons']
        ]
        record['indeterminate_reasons'] = (
            [horse['reason']] if horse['state'] in ('UNCONFIRMED', 'INVALID_INPUT') else []
        )
        envelope['condition_audit'].append(record)
    envelope['research_result'] = result
    return envelope


def evaluate_csv_text(content, *, metadata=None):
    """Accept original CSV text; no float coercion, whitespace stripping or filling."""
    if not isinstance(content, str):
        raise TypeError('content must be str')
    return evaluate_csv_bytes(content.encode('cp932'), metadata=metadata)


def evaluate_rows(rows, *, metadata=None):
    """Accept 21 original strings per row; numeric/float cells are rejected."""
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\r\n')
    for row in rows:
        if not isinstance(row, (list, tuple)) or any(not isinstance(v, str) for v in row):
            raise TypeError('each row must contain original string cells')
        writer.writerow(row)
    return evaluate_csv_text(stream.getvalue(), metadata=metadata)
