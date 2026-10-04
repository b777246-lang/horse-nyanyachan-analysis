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
