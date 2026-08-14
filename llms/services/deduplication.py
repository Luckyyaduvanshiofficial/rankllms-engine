import re
from typing import List
from llms.models import LLMModel

def get_clean_model_name(name: str) -> str:
    """
    Cleans up provider prefixes, parenthetical variants, and version suffixes.
    Example: 'Anthropic: Claude Opus 5 (Adaptive Reasoning, Max Effort)' -> 'Claude Opus 5'
    """
    n = re.sub(r'^(Anthropic:|OpenAI:|Google:|Meta:|DeepSeek:|Alibaba:|MoonshotAI:|SpaceXAI:)\s*', '', name, flags=re.IGNORECASE)
    n = re.sub(r'\s*\([^)]*\)', '', n)
    n = re.sub(r':.*$', '', n)
    n = re.sub(r'-\d{4}-\d{2}-\d{2}', '', n)
    return n.strip()

def deduplicate_models(models: List[LLMModel]) -> List[LLMModel]:
    """
    Deduplicates a list of LLMModel objects based on clean base name.
    Keeps the variant with the highest RankLLMs Index / Intelligence score.
    """
    groups = {}
    for m in models:
        clean_name = get_clean_model_name(m.name).lower()
        if clean_name not in groups:
            groups[clean_name] = m
        else:
            existing = groups[clean_name]
            # Priority: Higher benchmark intelligence index
            m_score = getattr(getattr(m, 'benchmark', None), 'intelligence_index', 0.0)
            ex_score = getattr(getattr(existing, 'benchmark', None), 'intelligence_index', 0.0)
            if m_score > ex_score:
                groups[clean_name] = m

    return list(groups.values())
