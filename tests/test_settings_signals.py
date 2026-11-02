from dataclasses import replace
from decimal import Decimal
import unittest

from config import (Condition, DEFAULT_SETTINGS, LocalSettingsProvider, SpecialRule,
                    load_settings)
from signals import (DEFAULT_REGISTRY, SignalDefinition, fup_matches,
                     kol_alert_matches)


class SettingsAndSignalsTests(unittest.TestCase):
    def test_kol_boundaries_missing_values_and_jockey_normalization(self):
        for odds, expected in [('25', True), ('55', True), ('24.9999', False),
                               ('55.0001', False), ('NaN', False), ('', False)]:
            with self.subTest(odds=odds):
                self.assertEqual(kol_alert_matches('10', odds, 5, 'ルメール'), expected)
        self.assertFalse(kol_alert_matches('50', '125', 5, 'ルメール'))
        self.assertFalse(kol_alert_matches('10', '25', 4, 'ルメール'))
        self.assertFalse(kol_alert_matches('10', '25', 5.5, 'ルメール'))
        self.assertFalse(kol_alert_matches('10', '25', 5, '未登録騎手'))

    def test_provider_changes_thresholds_without_changing_default_settings(self):
        settings = replace(DEFAULT_SETTINGS, kol=replace(DEFAULT_SETTINGS.kol,
                           divergence_min=Decimal('200')))
        loaded = load_settings(LocalSettingsProvider(settings))
        self.assertFalse(kol_alert_matches(10, 25, 5, 'ルメール', settings=loaded))
        self.assertTrue(kol_alert_matches(10, 25, 5, 'ルメール'))

    def test_fup_uses_numeric_data_and_configured_thresholds(self):
        row = {'venue': '東京', '条件': '２勝ｸﾗｽ 芝1600', '厩舎F-UP2': 6, '人気': 2}
        self.assertTrue(fup_matches(row))
        self.assertFalse(fup_matches(dict(row, 人気=3)))
        self.assertFalse(fup_matches(dict(row, **{'厩舎F-UP2': '<td class="rank-1">4</td>'})))
        settings = replace(DEFAULT_SETTINGS, fup=replace(DEFAULT_SETTINGS.fup, minimum=7))
        self.assertFalse(fup_matches(row, settings))

    def test_new_simple_and_custom_signals_can_be_added_without_ui_changes(self):
        simple = SpecialRule('new_test', '★新狙い目★', (Condition('arms', 'ge', 150),))
        settings = load_settings(LocalSettingsProvider(replace(DEFAULT_SETTINGS,
                                special_rules=DEFAULT_SETTINGS.special_rules + (simple,))))
        self.assertEqual([m.key for m in DEFAULT_REGISTRY.evaluate({'arms': 150}, settings)],
                         ['new_test'])
        registry = DEFAULT_REGISTRY.with_signal(SignalDefinition(
            'custom_test', lambda row, settings: row.get('custom_score', 0) > 3,
            '★独自計算★'))
        self.assertEqual([m.key for m in registry.evaluate({'custom_score': 4})], ['custom_test'])
        self.assertEqual(DEFAULT_REGISTRY.evaluate({'custom_score': 4}), ())

    def test_fukushima_dirt_1150_requires_s_at_least_55_and_rank_one_or_two(self):
        row = dict(venue='福島', surface='ダ', distance=1150, S=55, S_rank=1)
        def matched(data):
            return [m for m in DEFAULT_REGISTRY.evaluate(data) if m.key == 'fukushima_dirt_1150']
        for rank in (1, 2):
            result = matched(dict(row, S_rank=rank))
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].comment, '★福島ダ1150特注★')
            self.assertEqual(result[0].score, 1)
        for changes in (dict(S=54.999), dict(S_rank=3), dict(S_rank=0),
                        dict(surface='芝'), dict(distance=1200), dict(venue='東京')):
            with self.subTest(changes=changes):
                self.assertEqual(matched(dict(row, **changes)), [])
        self.assertEqual(matched({k: v for k, v in row.items() if k != 'S'}), [])

    def test_fukushima_special_uses_actual_ranks_and_existing_html_csv_path(self):
        import pandas as pd
        from analysis import analyze_csv
        from formatting import format_analysis_frame
        from export import format_target_frame, build_target_csv
        rows = [['福1', '未勝利', 'ダ', '1150', '1', str(n), '', f'試験馬{n}',
                 '10', '10', '10', str(s), '10', '1', '10',
                 f'2026110703010101{n:02d}', f'20230000{n:02d}', '騎手', '3', '父', '']
                for n, s in enumerate((60, 55, 55, 54), 1)]
        batch = analyze_csv(pd.DataFrame(rows), {}, {})
        self.assertEqual([note['ranks']['S'] for note in batch.notes.values()], [1, 2, 2, 4])
        self.assertEqual(batch.frame['総合評価・コース相性判定'].str.contains('★福島ダ1150特注★', regex=False).tolist(), [True, True, True, False])
        display = format_analysis_frame(batch.frame, batch.notes)
        self.assertIn('<span style="color: #ff4b4b; font-weight: bold;">★福島ダ1150特注★</span>', display.iloc[0]['総合評価・コース相性判定'])
        csv = build_target_csv(format_target_frame(batch.frame))
        self.assertIn('福島ダ1150特注', csv)
        self.assertNotIn('<span', csv)
        for idx in range(3):
            parts = batch.recommendations[idx]
            self.assertEqual(parts.specials[0].key, 'fukushima_dirt_1150')
            self.assertEqual(batch.frame.iloc[idx]['score'], parts.legacy.score + 1)

    def test_invalid_settings_are_rejected(self):
        invalid = replace(DEFAULT_SETTINGS, kol=replace(DEFAULT_SETTINGS.kol,
                          divergence_min=Decimal('500')))
        with self.assertRaises(ValueError):
            load_settings(LocalSettingsProvider(invalid))
        invalid = replace(DEFAULT_SETTINGS, special_rules=(
            SpecialRule('invalid', 'test', (Condition('arms', 'unknown', 1),)),))
        with self.assertRaises(ValueError):
            load_settings(LocalSettingsProvider(invalid))


if __name__ == '__main__':
    unittest.main()
