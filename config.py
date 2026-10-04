"""現行の既定設定と、将来のDB設定読込の境界。"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


KOL_SELECTED_JOCKEYS = {
    "C.ルメール", "戸崎圭太", "松山弘平", "横山武史", "坂井瑠星",
    "川田将雅", "丹内祐次", "岩田望来", "横山和生", "高杉吏麒",
    "北村友一", "武豊", "団野大成", "鮫島克駿", "菅原明良",
    "荻野極", "三浦皇成", "西村淳也", "藤岡佑介", "岩田康誠",
    "横山典弘", "D.レーン", "池添謙一", "C.デムーロ", "J.モレイラ",
    "丸山元気", "浜中俊", "R.キング",
}


KOL_JOCKEY_ALIASES = {
    "ルメール": "C.ルメール", "レーン": "D.レーン",
    "C.デム": "C.デムーロ", "モレイラ": "J.モレイラ", "キング": "R.キング",
}


WAKUBAN_COLORS = {
    1: "#FEFEFE", 2: "#222222", 3: "#CA4943", 4: "#3653A3",
    5: "#E0CB56", 6: "#6DAD57", 7: "#D28D3F", 8: "#CD687A",
}



@dataclass(frozen=True)
class KolSettings:
    enabled: bool = True
    maximum: Decimal = Decimal("50")
    divergence_min: Decimal = Decimal("150")
    divergence_max: Decimal = Decimal("450")
    popularity_min: int = 5
    jockeys: frozenset[str] = frozenset(KOL_SELECTED_JOCKEYS)


@dataclass(frozen=True)
class FupSettings:
    enabled: bool = True
    minimum: float = 6
    maximum: float = 7
    popularity_min: int = 1
    popularity_max: int = 2
    venues: frozenset[str] = frozenset({"阪神", "京都", "中山", "東京", "中京"})
    classes: tuple[str, ...] = ("未勝利", "1勝クラス", "2勝クラス", "3勝クラス")
    comment: str = "★F-UP特注★"


@dataclass(frozen=True)
class IndexSettings:
    arms: float = 110
    arms2: float = 120
    tua_strong: float = 220
    tua_candidate: float = 200
    s_strong: float = 60
    s_candidate: float = 55
    f_strong: float = 70
    f_candidate: float = 65
    training_count_max: int = 4
    training_min: float = 5
    training_rank_max: int = 3
    axis_score: int = 4
    candidate_score: int = 2
    standard_points: int = 1
    strong_points: int = 2


@dataclass(frozen=True)
class CourseSettings:
    win_return_min: float = 100
    place_rate_min: float = 60
    rank_max: int = 3
    triple_score: int = 3
    single_score: int = 1


@dataclass(frozen=True)
class Condition:
    """設定として保持できる単純な条件。複数条件はANDで評価する。"""
    field: str
    operator: str
    value: object


@dataclass(frozen=True)
class SpecialRule:
    key: str
    comment: str
    conditions: tuple[Condition, ...]
    score: int = 1
    enabled: bool = True


def _conditions(**fields):
    return tuple(Condition(name, op, value) for name, (op, value) in fields.items())


# 順序は既存コメントの表示順を維持する。
DEFAULT_SPECIAL_RULES = (
    SpecialRule("kyoto_1600", "★京都芝1600特注★", _conditions(
        venue=("eq", "京都"), surface=("eq", "芝"), distance=("eq", 1600),
        arms=("ge", 100), F=("ge", 65))),
    SpecialRule("tokyo_2000", "★東京芝2000馬体重480㎏以上特注★", _conditions(
        venue=("eq", "東京"), surface=("eq", "芝"), distance=("eq", 2000), F=("ge", 70))),
    SpecialRule("hanshin_1600", "★阪神芝1600特注★", _conditions(
        venue=("eq", "阪神"), surface=("eq", "芝"), distance=("eq", 1600),
        arms_rank=("le", 3), F=("ge", 60), frame=("in", (2, 4, 5, 6, 7)))),
    SpecialRule("nakayama_2000", "★中山芝2000特注★", _conditions(
        venue=("eq", "中山"), surface=("eq", "芝"), distance=("eq", 2000),
        frame=("in", (1, 2, 3, 4, 8)), F_rank=("eq", 1))),
    SpecialRule("nakayama_1600", "★中山芝1600特注★", _conditions(
        venue=("eq", "中山"), surface=("eq", "芝"), distance=("eq", 1600),
        frame=("in", (1, 2, 3, 4)), S_rank=("eq", 1))),
    SpecialRule("sand", "★特注砂食★", _conditions(
        surface=("eq", "ダ"), condition=("not_contains_any", ("未勝利", "新馬")),
        frame=("in", (6, 7, 8)), S_rank=("eq", 1))),
    SpecialRule("f72", "★特注F72★", _conditions(
        surface=("eq", "ダ"), frame=("eq", 8), F=("ge", 72), distance=("ne", 1200))),
)


@dataclass(frozen=True)
class AnalysisSettings:
    kol: KolSettings = field(default_factory=KolSettings)
    fup: FupSettings = field(default_factory=FupSettings)
    index: IndexSettings = field(default_factory=IndexSettings)
    course: CourseSettings = field(default_factory=CourseSettings)
    special_rules: tuple[SpecialRule, ...] = DEFAULT_SPECIAL_RULES


DEFAULT_SETTINGS = AnalysisSettings()


class SettingsProvider(Protocol):
    """将来のDBアダプターも、同じload()で設定全体を返す。"""
    def load(self) -> AnalysisSettings: ...


@dataclass(frozen=True)
class LocalSettingsProvider:
    settings: AnalysisSettings = DEFAULT_SETTINGS

    def load(self) -> AnalysisSettings:
        return self.settings


def load_settings(provider: SettingsProvider | None = None) -> AnalysisSettings:
    settings = (provider or LocalSettingsProvider()).load()
    if not isinstance(settings, AnalysisSettings):
        raise TypeError("設定読込はAnalysisSettingsを返す必要があります")
    if (not all(value.is_finite() for value in (
            settings.kol.maximum, settings.kol.divergence_min, settings.kol.divergence_max))
            or settings.kol.maximum <= 0 or settings.kol.divergence_min > settings.kol.divergence_max
            or settings.kol.popularity_min < 1
            or settings.fup.minimum > settings.fup.maximum
            or settings.fup.popularity_min < 1
            or settings.fup.popularity_min > settings.fup.popularity_max):
        raise ValueError("判定条件の下限・上限が不正です")
    keys = [rule.key for rule in settings.special_rules]
    if len(keys) != len(set(keys)):
        raise ValueError("狙い目のキーが重複しています")
    for rule in settings.special_rules:
        if rule.key in {"kol", "fup"} or not rule.key or not rule.conditions:
            raise ValueError("狙い目のキーまたは条件が不正です")
        for condition in rule.conditions:
            if condition.operator not in {"eq", "ne", "ge", "le", "in", "not_contains_any"}:
                raise ValueError(f"未対応の判定演算子: {condition.operator}")
    return settings
