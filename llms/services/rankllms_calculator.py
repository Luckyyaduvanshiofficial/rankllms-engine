"""Transparent RankLLMs composite scoring.

The index combines only independently published quality measurements. Missing
signals are omitted and the remaining weights are renormalized; there are no
name-based score guesses, ELO/unit conversions, or speed/context bonuses.
"""

from __future__ import annotations

import math
from typing import Mapping


RANKLLMS_WEIGHTS = {
    'intelligence_index': 0.35,
    'coding_index': 0.30,
    'agentic_index': 0.15,
    'gpqa_diamond': 0.10,
    'terminalbench': 0.10,
}


def normalize_percentage(value: object) -> float | None:
    """Convert a percent or fraction to 0–100; preserve missing/invalid values."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or number > 100:
        return None
    return number * 100.0 if number <= 1.0 else number


def _valid_index(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or number > 100:
        return None
    return number


def calculate_rankllms_index(
    coding_index: float | None = None,
    agentic_index: float | None = None,
    swe_bench_score: float | None = None,
    raw_intelligence: float | None = None,
    tokens_per_second: float | None = None,
    context_length: int | None = None,
    *,
    gpqa_diamond: float | None = None,
    terminalbench_score: float | None = None,
    components: Mapping[str, object] | None = None,
) -> float | None:
    """Return the weighted 0–100 score using available, verified components.

    ``raw_intelligence`` and ``swe_bench_score`` remain accepted for call
    compatibility. SWE-Bench is not treated as TerminalBench, and throughput
    and context are accepted for source compatibility but do not affect ranking.
    """
    values = dict(components or {})
    values.setdefault('intelligence_index', raw_intelligence)
    values.setdefault('coding_index', coding_index)
    values.setdefault('agentic_index', agentic_index)
    values.setdefault('gpqa_diamond', gpqa_diamond)
    values.setdefault('terminalbench', terminalbench_score)

    score_sum = 0.0
    weight_sum = 0.0
    for name, weight in RANKLLMS_WEIGHTS.items():
        raw = values.get(name)
        score = normalize_percentage(raw) if name in {'gpqa_diamond', 'terminalbench'} else _valid_index(raw)
        if score is None:
            continue
        score_sum += score * weight
        weight_sum += weight

    if not weight_sum:
        return None
    return round(score_sum / weight_sum, 1)
