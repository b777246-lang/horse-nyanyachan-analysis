"""独立した旧推奨・事前特注の結果から、既存UI／CSV用の値を互換合成する。"""
from dataclasses import dataclass

from config import DEFAULT_SETTINGS
from legacy_recommendations import LegacyRecommendation, recommendation_label
from signals import SignalMatch


@dataclass(frozen=True)
class RecommendationParts:
    legacy: LegacyRecommendation
    specials: tuple[SignalMatch, ...]


@dataclass(frozen=True)
class CompatibleRecommendation:
    score: int
    evaluation: str


def compose_compatible_recommendation(parts, *, settings=DEFAULT_SETTINGS):
    """特注の結果だけを使用し、条件の再判定・文字列の逆解析は行わない。"""
    score = parts.legacy.score + sum(match.score for match in parts.specials)
    comments = [match.comment for match in parts.specials if match.comment]
    comments.extend(parts.legacy.highlights)
    if parts.legacy.course_comment:
        comments.append(parts.legacy.course_comment)
    evaluation = ''
    if comments:
        label = recommendation_label(parts.legacy, score,
                                     additional_attention=bool(parts.specials), settings=settings)
        evaluation = label + ' / '.join(comments)
    return CompatibleRecommendation(score, evaluation)
