"""非表示S2接続：元バイト、分離、キャッシュ、失敗時の既存表示・出力を確認。"""
import csv
from copy import deepcopy
import hashlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from data_loader import latest_csv
from s2_service import STATE_KEY, update_s2_audit
from s2_shared import evaluate_csv_bytes
from s2_shared.storage import encode

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = (ROOT / 'tests/fixtures/s2/artificial.csv').read_bytes()


class S2IntegrationTests(unittest.TestCase):
    def test_vendored_runtime_is_byte_identical_to_the_supplied_package(self):
        expected = {}
        for line in (ROOT / 'docs/s2_shared/SHA256SUMS').read_text().splitlines():
            digest, name = line.split('  ', 1)
            if name.startswith('s2_shared/'):
                expected[name] = digest
        actual = {str(path.relative_to(ROOT)) for path in (ROOT / 's2_shared').rglob('*')
                  if path.is_file() and path.suffix in {'.py', '.json', '.sha256'}}
        self.assertEqual(actual, set(expected))
        self.assertEqual(len(expected), 10)
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest, name)

    def test_latest_csv_service_result_equals_unmodified_public_api_canonical_json(self):
        raw = latest_csv().read_bytes()
        state = {}
        record = update_s2_audit(raw, state)
        self.assertEqual(record['status'], 'EVALUATED')
        self.assertEqual(encode(record['report']), encode(evaluate_csv_bytes(raw)))
        self.assertEqual(len(record['report']['condition_audit']), len(list(csv.reader(io.StringIO(raw.decode('cp932'))))) * 8)
        self.assertEqual(record['input_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertTrue(record['research_only'])
        self.assertIs(record['prospective_ready'], False)
        self.assertIs(record['prospective_verified'], False)
        self.assertEqual(list(state), [STATE_KEY])

    def test_original_bytes_are_passed_once_and_reused_only_for_same_input_and_package(self):
        state = {}
        with patch('s2_shared.evaluate_csv_bytes', wraps=evaluate_csv_bytes) as call:
            first = update_s2_audit(SAMPLE, state)
            self.assertIs(update_s2_audit(SAMPLE, state), first)
            call.assert_called_once_with(SAMPLE)
            alternate = SAMPLE.replace(b'\r\n', b'\n')
            self.assertNotEqual(SAMPLE, alternate)
            second = update_s2_audit(alternate, state)
            self.assertNotEqual(first['input_sha256'], second['input_sha256'])
            self.assertEqual(call.call_count, 2)
            with patch('s2_service._package_signature', return_value='changed-package'):
                update_s2_audit(alternate, state)
            self.assertEqual(call.call_count, 3)

    def test_invalid_twenty_column_input_replaces_previous_success_without_zero_filling(self):
        rows = list(csv.reader(io.StringIO(SAMPLE.decode('cp932'))))
        state = {}
        update_s2_audit(SAMPLE, state)
        stream = io.StringIO(newline='')
        csv.writer(stream).writerows([row[:20] for row in rows])
        rejected = update_s2_audit(stream.getvalue().encode('cp932'), state)
        self.assertEqual(rejected['status'], 'INVALID_INPUT')
        self.assertIsNone(rejected['report']['research_result'])
        self.assertNotEqual(rejected['input_sha256'], hashlib.sha256(SAMPLE).hexdigest())
        self.assertIsNone(rejected['error'])
        rows[0][8] = ''
        stream = io.StringIO(newline='')
        csv.writer(stream).writerows(rows)
        rejected = update_s2_audit(stream.getvalue().encode('cp932'), state)
        self.assertEqual(rejected['status'], 'INVALID_INPUT')
        self.assertTrue(all(row['state'] == 'INVALID_INPUT' for row in rejected['report']['condition_audit']))

    def test_evaluation_and_package_read_failures_replace_old_audit_and_can_retry(self):
        state = {}
        update_s2_audit(SAMPLE, state)
        with patch('s2_service._package_signature', side_effect=OSError('package unavailable')):
            record = update_s2_audit(SAMPLE, state)
        self.assertEqual(record['status'], 'ERROR')
        self.assertIsNone(record['report'])
        self.assertEqual(record['error']['type'], 'OSError')
        with patch('s2_shared.evaluate_csv_bytes', side_effect=ValueError('manifest mismatch')):
            record = update_s2_audit(SAMPLE, state)
        self.assertEqual(record['status'], 'ERROR')
        self.assertIsNone(record['report'])
        self.assertIs(record['prospective_verified'], False)
        self.assertEqual(update_s2_audit(SAMPLE, state)['status'], 'EVALUATED')

    def test_prospective_true_from_api_is_not_accepted_or_retained(self):
        for field in ('prospective_ready', 'prospective_verified'):
            report = deepcopy(evaluate_csv_bytes(SAMPLE))
            report[field] = True
            with patch('s2_shared.evaluate_csv_bytes', return_value=report):
                record = update_s2_audit(SAMPLE, {})
            self.assertEqual(record['status'], 'ERROR')
            self.assertIsNone(record['report'])
            self.assertIs(record['prospective_ready'], False)
            self.assertIs(record['prospective_verified'], False)

    def test_no_input_clears_hidden_audit(self):
        state = {}
        update_s2_audit(SAMPLE, state)
        self.assertIsNone(update_s2_audit(None, state))
        self.assertNotIn(STATE_KEY, state)

    def test_auto_load_keeps_full_csv_across_race_sort_and_odds_changes(self):
        raw = latest_csv().read_bytes()
        expected = encode(evaluate_csv_bytes(raw))
        with patch('s2_shared.evaluate_csv_bytes', wraps=evaluate_csv_bytes) as call, patch(
                'cushion_viewer.cached_jra_cushion', return_value=dict(value=None, message='テスト')):
            at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=60).run()
            self.assertFalse(at.exception)
            call.assert_called_once_with(raw)
            self.assertEqual(encode(at.session_state[STATE_KEY]['report']), expected)
            at.get('button_group')[1].set_value('ALL').run()
            next(b for b in at.button if b.label == '🔥 評価点数順にソート').click().run()
            at.session_state['jra_odds_cache'] = {'unrelated': []}
            at.run()
            self.assertFalse(at.exception)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(encode(at.session_state[STATE_KEY]['report']), expected)
            for element in at.markdown:
                self.assertNotIn('S2推奨', element.value)

    def test_uploaded_original_bytes_override_repository_and_rejection_does_not_change_csv(self):
        chosen = {'raw': SAMPLE}
        downloads = {}
        def uploader(label, **kwargs):
            if label.startswith('メイン指数CSV'):
                return io_source(chosen['raw'])
            return None
        def capture(**kwargs):
            downloads[kwargs['file_name']] = kwargs['data']
            return False
        with patch('streamlit.sidebar.file_uploader', side_effect=uploader), patch(
                'streamlit.download_button', side_effect=capture), patch(
                'cushion_viewer.cached_jra_cushion', return_value=dict(value=None, message='テスト')):
            at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=60).run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state[STATE_KEY]['input_sha256'], hashlib.sha256(SAMPLE).hexdigest())
            self.assertEqual(encode(at.session_state[STATE_KEY]['report']), encode(evaluate_csv_bytes(SAMPLE)))
            initial_csv = downloads['horse_analysis_result.csv']
            rows = list(csv.reader(io.StringIO(SAMPLE.decode('cp932'))))
            stream = io.StringIO(newline='')
            csv.writer(stream).writerows([r[:20] for r in rows])
            chosen['raw'] = stream.getvalue().encode('cp932')
            at.run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state[STATE_KEY]['status'], 'INVALID_INPUT')
            self.assertIsNone(at.session_state[STATE_KEY]['report']['research_result'])
            self.assertEqual(downloads['horse_analysis_result.csv'], initial_csv)
            self.assertFalse(at.error)

    def test_s2_error_in_app_does_not_change_existing_downloads_or_show_error(self):
        downloads = {}
        def capture(**kwargs):
            downloads[kwargs['file_name']] = kwargs['data']
            return False
        with patch('streamlit.download_button', side_effect=capture), patch(
                'cushion_viewer.cached_jra_cushion', return_value=dict(value=None, message='テスト')):
            at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=60).run()
            expected = dict(downloads)
            at.session_state[STATE_KEY] = None
            with patch('s2_shared.evaluate_csv_bytes', side_effect=RuntimeError('isolated failure')):
                at.run()
            self.assertFalse(at.exception)
            self.assertFalse(at.error)
            self.assertEqual(at.session_state[STATE_KEY]['status'], 'ERROR')
            self.assertIsNone(at.session_state[STATE_KEY]['report'])
            self.assertEqual(downloads, expected)
            at.run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state[STATE_KEY]['status'], 'EVALUATED')
            self.assertEqual(downloads, expected)


def io_source(raw):
    source = io.BytesIO(raw)
    source.name = 'artificial.csv'
    return source


if __name__ == '__main__':
    unittest.main()
