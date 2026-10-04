"""狙い目の登録と生データの判定。UI・HTML・DB接続には依存しない。"""
from dataclasses import dataclass
from typing import Callable, Mapping

from config import AnalysisSettings, DEFAULT_SETTINGS
from values import decimal_value, normalize_jockey


def kol_divergence(kol_odds, actual_odds):
    kol, actual = decimal_value(kol_odds), decimal_value(actual_odds)
    if kol is None or actual is None or kol <= 0 or actual <= 0:
        return None
    return (actual - kol) / kol * 100


def kol_alert_matches(kol_odds, actual_odds, popularity, jockey, *, settings=DEFAULT_SETTINGS):
    kol, actual, rank = map(decimal_value, (kol_odds, actual_odds, popularity))
    rule = settings.kol
    return (
        rule.enabled and kol is not None and actual is not None and rank is not None
        and 0 < kol < rule.maximum and actual > 0
        # 除算や表示用の丸めを行わず、境界を含めて判定する。
        and kol * (100 + rule.divergence_min) <= actual * 100
        <= kol * (100 + rule.divergence_max)
        and rank >= rule.popularity_min and rank == rank.to_integral_value()
        and normalize_jockey(jockey) in rule.jockeys
    )


def fup_matches(row, settings=DEFAULT_SETTINGS):
    rule = settings.fup
    condition = str(row.get("条件", "")).replace("１", "1").replace("２", "2").replace("３", "3").replace("ｸﾗｽ", "クラス")
    fup = decimal_value(row.get("厩舎F-UP2", ""))
    popularity = decimal_value(row.get("人気", ""))
    return (
        rule.enabled and row.get("venue") in rule.venues
        and any(name in condition for name in rule.classes)
        and fup is not None and rule.minimum <= fup <= rule.maximum
        and popularity is not None and rule.popularity_min <= popularity <= rule.popularity_max
    )


def condition_matches(condition, row):
    if condition.field not in row:
        return False
    actual = row[condition.field]
    expected = condition.value
    if condition.operator == "eq":
        return actual == expected
    if condition.operator == "ne":
        return actual != expected
    if condition.operator == "ge":
        return actual >= expected
    if condition.operator == "le":
        return actual <= expected
    if condition.operator == "in":
        return actual in expected
    if condition.operator == "not_contains_any":
        return not any(value in str(actual) for value in expected)
    raise ValueError(f"未対応の判定演算子: {condition.operator}")


@dataclass(frozen=True)
class SignalMatch:
    key: str
    comment: str
    score: int = 0


@dataclass(frozen=True)
class SignalDefinition:
    key: str
    predicate: Callable[[Mapping, AnalysisSettings], bool]
    comment: str = ""
    score: int = 0
    stage: str = "pre"


@dataclass(frozen=True)
class SignalRegistry:
    definitions: tuple[SignalDefinition, ...] = ()

    def with_signal(self, definition):
        if definition.key in {item.key for item in self.definitions}:
            raise ValueError(f"狙い目のキーが重複しています: {definition.key}")
        return SignalRegistry(self.definitions + (definition,))

    def evaluate(self, row, settings=DEFAULT_SETTINGS, *, stage="pre"):
        if {definition.key for definition in self.definitions} & {rule.key for rule in settings.special_rules}:
            raise ValueError("設定と登録処理で狙い目のキーが重複しています")
        matches = []
        if stage == "pre":
            for rule in settings.special_rules:
                if rule.enabled and all(condition_matches(c, row) for c in rule.conditions):
                    matches.append(SignalMatch(rule.key, rule.comment, rule.score))
        for definition in self.definitions:
            if definition.stage == stage and definition.predicate(row, settings):
                comment = settings.fup.comment if definition.key == "fup" else definition.comment
                matches.append(SignalMatch(definition.key, comment, definition.score))
        return tuple(matches)


DEFAULT_REGISTRY = SignalRegistry((
    SignalDefinition("kol", lambda row, settings: kol_alert_matches(
        row.get("KOLオッズ", ""), row.get("実オッズ", ""), row.get("人気", ""),
        row.get("騎手", ""), settings=settings), stage="live"),
    SignalDefinition("fup", fup_matches, stage="live"),
))


def filter_kol_horses(frame, *, settings=DEFAULT_SETTINGS):
    mask = frame.apply(lambda row: kol_alert_matches(
        row.get("KOLオッズ", ""), row.get("実オッズ", ""), row.get("人気", ""),
        row.get("騎手", ""), settings=settings), axis=1)
    return frame.loc[mask].copy()


def add_live_comments(frame, *, settings=DEFAULT_SETTINGS, registry=DEFAULT_REGISTRY):
    """生データの判定結果をプレーンテキストで追加する。スコアは変更しない。"""
    result = frame.copy()
    for idx, row in frame.iterrows():
        current = str(row.get("総合評価・コース相性判定", "") or "")
        for match in registry.evaluate(row, settings, stage="live"):
            if match.comment and match.comment not in current:
                current = f"{match.comment} {current}".strip()
        result.at[idx, "総合評価・コース相性判定"] = current
    return result
