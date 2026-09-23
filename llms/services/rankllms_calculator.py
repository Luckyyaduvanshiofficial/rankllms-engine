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
    RankLLMs Index = (0.30 * Intelligence) + (0.40 * Coding) + (0.10 * Agentic) + (0.10 * SWE-Bench) + (0.10 * Efficiency & Context)

    Returns a normalized 0-100 composite score representing overall real-world model capability.
    """
    base_intel = raw_intelligence if raw_intelligence > 0.0 else max(coding_index, agentic_index)
    if base_intel == 0.0:
        return 0.0

    # 1. Intelligence (30%)
    intel_component = base_intel

    # 2. Coding (40%) — primary signal for coding-focused releases
    coding_component = coding_index if coding_index > 0.0 else (base_intel * 0.94)

    # 3. Agentic & Tool Execution (10%)
    agentic_component = agentic_index if agentic_index > 0.0 else (base_intel * 0.88)

    # 4. SWE-Bench / Software Engineering (10%)
    swe_component = swe_bench_score if swe_bench_score > 0.0 else (coding_component * 0.80)

    # 5. Efficiency & Context Scaling (10%)
    speed_factor = min((tokens_per_second / 120.0) * 100.0, 100.0) if tokens_per_second > 0 else 50.0
    context_factor = min((math.log10(max(context_length, 4096)) / 6.0) * 100.0, 100.0)
    efficiency_component = (0.5 * speed_factor) + (0.5 * context_factor)

    # Composite weighted calculation
    composite = (
        (0.30 * intel_component) +
        (0.40 * coding_component) +
        (0.10 * agentic_component) +
        (0.10 * swe_component) +
        (0.10 * efficiency_component)
    )

    return round(min(composite, 99.5), 1)
