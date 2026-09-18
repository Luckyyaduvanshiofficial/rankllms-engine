import re
from typing import List
from llms.models import LLMModel

NON_LLM_KEYWORDS = [
    'flux', 'diffusion', 'midjourney', 'dall-e', 'dalle', 'ideogram', 'recraft', 'imagen',
    'text-embedding', 'bge-', 'embed-', 'embedding', 'rerank',
    'kling', 'runway', 'sora', 'luma', 'pika', 'hunyuan-video',
    'whisper', 'tts', 'elevenlabs', 'speech', 'bark'
]

def is_non_llm_model(name: str, slug: str = '', category: str = 'llm') -> bool:
    """
    Checks if a model is an image generation, video, audio, or embedding model.
    """
    if category in ['image', 'video', 'audio', 'embedding']:
        return True
    combined = f"{name.lower()} {slug.lower()}"
    return any(kw in combined for kw in NON_LLM_KEYWORDS)


def get_clean_model_name(name: str, provider_name: str = '') -> str:
    """
    Cleans up provider prefixes, parenthetical variants, batch/preview tags, and version suffixes.
    Examples:
      'Anthropic: Claude Opus 5 (Adaptive Reasoning, Max Effort)' -> 'Claude Opus 5'
      'OpenAI: GPT-4 Turbo (batch)' -> 'GPT-4 Turbo'
      'OpenAI: GPT-4 Turbo Preview' -> 'GPT-4 Turbo'
      'DeepSeek: R1 0528' -> 'DeepSeek R1'
      'Gemini 3.7 Flash (high)' -> 'Gemini 3.7 Flash'
    """
    # 1. Strip provider prefix e.g. "OpenAI:", "Anthropic:"
    n = re.sub(r'^(Anthropic:|OpenAI:|Google:|Meta:|DeepSeek:|Alibaba:|MoonshotAI:|SpaceXAI:|Z AI:|Nex AGI:|Mistral:|Cohere:|Amazon:|Qwen:)\s*', '', name, flags=re.IGNORECASE)
    
    # 2. Strip parentheticals e.g. (batch), (preview), (high), (reasoning), (ChatGPT)
    n = re.sub(r'\s*\([^)]*\)', '', n)
    
    # 3. Strip colon suffixes e.g. :free, :nitro, :batch, :beta, :online
    n = re.sub(r':[a-zA-Z0-9_-]+', '', n)
    
    # 4. Strip date suffixes e.g. 0528, 0423, 0120, -0125, -1106, 2024-08-06
    n = re.sub(r'-\d{4}-\d{2}-\d{2}', '', n)
    n = re.sub(r'-\d{4,8}', '', n)
    n = re.sub(r'\s+\d{4}$', '', n)
    
    # 5. Strip redundant batch / preview / latest keywords
    n = re.sub(r'\b(preview|batch|latest|thinking|chatgpt)\b', '', n, flags=re.IGNORECASE)
    
    # 6. Ensure clean spacing
    clean = re.sub(r'\s+', ' ', n).strip()
    
    # Special normalization for known models
    clean_lower = clean.lower()
    if clean_lower in ['r1', 'deepseek r1']:
        clean = 'DeepSeek R1'
    elif clean_lower in ['v3', 'deepseek v3']:
        clean = 'DeepSeek V3'
    elif 'gpt-4 turbo' in clean_lower:
        clean = 'GPT-4 Turbo'
    elif clean_lower in ['o3 mini', 'o3-mini']:
        clean = 'o3-mini'
    elif clean_lower in ['o1 mini', 'o1-mini']:
        clean = 'o1-mini'
    elif clean_lower in ['o1 preview', 'o1']:
        clean = 'o1'
    
    return clean or name


def deduplicate_models(models: List[LLMModel], exclude_non_llms: bool = True) -> List[LLMModel]:
    """
    Deduplicates a list of LLMModel objects based on canonical clean name.
    Keeps the canonical variant with the highest RankLLMs Index / Intelligence score.
    Optionally filters out image, video, audio, and embedding models.
    """
    groups = {}
    for m in models:
        # Check non-LLM filter
        if exclude_non_llms and is_non_llm_model(m.name, m.slug, m.category):
            continue

        provider_name = m.provider.name if m.provider else ''
        clean_name = get_clean_model_name(m.name, provider_name).lower()
        
        # Include provider slug in key to prevent collision across different providers
        group_key = f"{m.provider.slug if m.provider else ''}::{clean_name}"

        if group_key not in groups:
            groups[group_key] = m
        else:
            existing = groups[group_key]
            # Priority 1: Higher benchmark intelligence index
            m_score = getattr(getattr(m, 'benchmark', None), 'intelligence_index', 0.0) or 0.0
            ex_score = getattr(getattr(existing, 'benchmark', None), 'intelligence_index', 0.0) or 0.0
            
            # Priority 2: Non-batch over batch
            m_is_batch = 'batch' in m.name.lower() or 'batch' in m.slug.lower()
            ex_is_batch = 'batch' in existing.name.lower() or 'batch' in existing.slug.lower()

            if (m_score > ex_score and not m_is_batch) or (ex_is_batch and not m_is_batch):
                groups[group_key] = m
            elif m_score > ex_score and not ex_is_batch:
                groups[group_key] = m

    return list(groups.values())
