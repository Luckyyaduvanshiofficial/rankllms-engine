import math
from typing import Dict, Any

def calculate_rankllms_index(
    coding_index: float = 0.0,
    agentic_index: float = 0.0,
    swe_bench_score: float = 0.0,
    raw_intelligence: float = 0.0,
    tokens_per_second: float = 0.0,
    context_length: int = 128000
) -> float:
    """
    Official RankLLMs Index Calculation Formula.
    
    Formula:
    RankLLMs Index = (0.35 * Coding) + (0.30 * Agentic) + (0.20 * Base Evaluation) + (0.15 * Efficiency & Context)
    
    Returns a normalized 0-100 composite score representing overall model real-world utility.
    """
    # 1. Base Evaluation Component (20%)
    base_score = raw_intelligence if raw_intelligence > 0.0 else max(coding_index, agentic_index)
    if base_score == 0.0:
        return 0.0

    # 2. Coding Component (35%)
    coding = coding_index if coding_index > 0.0 else (base_score * 0.96)

    # 3. Agentic Component (30%)
    agentic = agentic_index if agentic_index > 0.0 else (base_score * 0.88)

    # 4. Efficiency & Context Component (15%)
    speed_factor = min((tokens_per_second / 150.0) * 100.0, 100.0) if tokens_per_second > 0 else 50.0
    context_factor = min((math.log10(max(context_length, 4096)) / 6.0) * 100.0, 100.0)
    efficiency_score = (0.6 * speed_factor) + (0.4 * context_factor)

    # Weighted Sum Formula
    composite_index = (
        (0.35 * coding) +
        (0.30 * agentic) +
        (0.20 * base_score) +
        (0.15 * efficiency_score)
    )

    return round(composite_index, 1)
