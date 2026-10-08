"""Presentation cleanup and conservative catalog identity helpers."""

import re
import unicodedata
from typing import List

from llms.models import LLMModel


NON_LLM_CATEGORIES = {'image', 'video', 'audio', 'embedding'}


def is_non_llm_model(name: str, slug: str = '', category: str = 'llm') -> bool:
    """Only trust an explicit source category; names are not a type system."""
    return str(category or '').casefold() in NON_LLM_CATEGORIES


def get_clean_model_name(name: str, provider_name: str = '') -> str:
    """Remove an explicit matching provider label without erasing model identity."""
    original = str(name or '').strip()
    clean = unicodedata.normalize('NFKC', original)
    if provider_name:
        prefix = str(provider_name).strip()
        if prefix and clean.casefold().startswith(f'{prefix.casefold()}:'):
            clean = clean[len(prefix) + 1:].strip()
    return re.sub(r'\s+', ' ', clean) or original


def deduplicate_models(models: List[LLMModel], exclude_non_llms: bool = False) -> List[LLMModel]:
    """Remove only duplicate copies of the same provider-scoped source ID.

    Similar names, date suffixes, previews, effort labels, and release versions
    remain separate unless ingestion has an explicit source identity mapping.
    """
    unique = {}
    for model in models:
        if exclude_non_llms and is_non_llm_model(model.name, model.slug, model.category):
            continue
        provider = (model.provider.slug if model.provider_id else '').casefold().strip()
        source_id = unicodedata.normalize('NFKC', model.openrouter_id or '').casefold().strip()
        key = (provider, source_id or f'db:{model.pk}')
        unique.setdefault(key, model)
    return list(unique.values())
