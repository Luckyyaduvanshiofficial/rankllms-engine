import re
from decimal import Decimal
from django.db import transaction
from llms.models import LLMModel, ModelSpecification, ModelPricing, ModelBenchmark
from llms.services.rankllms_calculator import calculate_rankllms_index
from llms.services.deduplication import is_non_llm_model, get_clean_model_name

def estimate_model_intelligence(name: str, slug: str, context_length: int = 128000) -> float:
    """
    Estimates realistic, calibrated baseline intelligence score for models lacking direct Artificial Analysis evals.
    Prevents unmapped endpoints from getting arbitrarily large or distorted scores.
    """
    combined = f"{name.lower()} {slug.lower()}"
    
    # Flagship reasoning & top-tier models
    if any(k in combined for k in ['opus-5', 'gpt-5', 'grok-4', 'gemini-3']):
        return 92.0
    if any(k in combined for k in ['claude-3-7', 'claude-3.7', 'r1', 'o3-mini', 'o1']):
        return 88.0
    if any(k in combined for k in ['claude-3-5', 'claude-3.5', 'gpt-4o', 'gemini-2', 'deepseek-v3', 'qwen-2.5-max']):
        return 84.0
    if any(k in combined for k in ['gpt-4-turbo', 'gpt-4', 'claude-3-opus', 'mistral-large']):
        return 72.0
    
    # Open-weights parameter tiers
    if any(k in combined for k in ['405b', '236b', 'a95b']):
        return 82.0
    if any(k in combined for k in ['70b', '72b', '67b', '8x22b']):
        return 76.0
    if any(k in combined for k in ['32b', '34b', '8x7b']):
        return 66.0
    if any(k in combined for k in ['14b', '13b', '12b']):
        return 58.0
    if any(k in combined for k in ['7b', '8b', '9b']):
        return 48.0
    if any(k in combined for k in ['3b', '4b']):
        return 36.0
    if any(k in combined for k in ['1b', '1.5b', '2b']):
        return 28.0
    if any(k in combined for k in ['0.5b']):
        return 18.0

    return 52.0  # Default general baseline


def fill_all_nulls():
    """
    Intelligent Null & Missing Data Backfill Service for RankLLMs Engine.
    Ensures 100% of LLMModels have complete Specs, Pricing, and calibrated Benchmark metrics.
    """
    print("[Fill Nulls] Starting database-wide null & missing value backfill...")

    models = list(LLMModel.objects.all())

    existing_specs = {s.model_id: s for s in ModelSpecification.objects.all()}
    existing_pricing = {p.model_id: p for p in ModelPricing.objects.all()}
    existing_benchmarks = {b.model_id: b for b in ModelBenchmark.objects.all()}

    specs_to_create = []
    specs_to_update = []
    pricing_to_create = []
    pricing_to_update = []
    benchmarks_to_create = []
    benchmarks_to_update = []
    models_to_update = []

    filled_specs = 0
    filled_pricing = 0
    filled_benchmarks = 0

    for m in models:
        raw = m.raw_json or {}
        desc = (m.description or '').lower()
        name_lower = (m.name or '').lower()
        slug_lower = (m.slug or '').lower()
        openrouter_id_lower = (m.openrouter_id or '').lower()

        # ----------------------------------------------------
        # 0. Accurate Category Re-classification
        # ----------------------------------------------------
        old_cat = m.category
        if is_non_llm_model(m.name, m.slug):
            if any(k in name_lower or k in slug_lower for k in ['flux', 'diffusion', 'midjourney', 'dall-e', 'dalle', 'recraft', 'ideogram', 'imagen']):
                m.category = 'image'
            elif any(k in name_lower or k in slug_lower for k in ['kling', 'runway', 'sora', 'luma', 'pika']):
                m.category = 'video'
            elif any(k in name_lower or k in slug_lower for k in ['whisper', 'tts', 'speech', 'bark', 'elevenlabs']):
                m.category = 'audio'
            elif any(k in name_lower or k in slug_lower for k in ['embed', 'embedding', 'bge-', 'rerank']):
                m.category = 'embedding'
        
        if m.category != old_cat:
            models_to_update.append(m)

        # ----------------------------------------------------
        # 1. Backfill / Ensure ModelSpecification
        # ----------------------------------------------------
        spec = existing_specs.get(m.id)
        is_new_spec = False
        if not spec:
            spec = ModelSpecification(model=m)
            existing_specs[m.id] = spec
            is_new_spec = True

        # Context Length
        if not spec.context_length or spec.context_length == 0:
            ctx = raw.get('context_length', 0)
            if not ctx:
                if '128k' in openrouter_id_lower or '128k' in name_lower:
                    ctx = 131072
                elif '1m' in openrouter_id_lower or '1m' in name_lower or '1000k' in name_lower:
                    ctx = 1048576
                elif '200k' in openrouter_id_lower or '200k' in name_lower:
                    ctx = 200000
                elif '32k' in openrouter_id_lower or '32k' in name_lower:
                    ctx = 32768
                elif '16k' in openrouter_id_lower or '16k' in name_lower:
                    ctx = 16384
                else:
                    ctx = 4096
            spec.context_length = ctx

        # Max Completion Tokens
        if not spec.max_completion_tokens:
            top_prov = raw.get('top_provider') or {}
            max_out = top_prov.get('max_completion_tokens')
            if not max_out:
                if 'gpt-4' in openrouter_id_lower or 'claude' in openrouter_id_lower:
                    max_out = 4096
                elif 'o1' in openrouter_id_lower or 'o3' in openrouter_id_lower or 'r1' in openrouter_id_lower:
                    max_out = 65536
                else:
                    max_out = min(spec.context_length, 4096)
            spec.max_completion_tokens = max_out

        # Modality & Flags
        if not spec.modality:
            arch = raw.get('architecture') or {}
            spec.modality = arch.get('modality', 'text->text') or 'text->text'

        modality_lower = spec.modality.lower()
        if not spec.is_multimodal:
            spec.is_multimodal = 'image' in modality_lower or 'audio' in modality_lower or 'video' in modality_lower
        if not spec.supports_vision:
            spec.supports_vision = 'image' in modality_lower or 'vision' in desc or 'vision' in name_lower
        if not spec.supports_audio:
            spec.supports_audio = 'audio' in modality_lower
        if not spec.supports_tools:
            spec.supports_tools = 'tool' in desc or 'function' in desc or 'agent' in desc

        if is_new_spec:
            specs_to_create.append(spec)
            filled_specs += 1
        else:
            specs_to_update.append(spec)

        # ----------------------------------------------------
        # 2. Backfill / Ensure ModelPricing
        # ----------------------------------------------------
        pricing = existing_pricing.get(m.id)
        is_new_pricing = False
        if not pricing:
            pricing = ModelPricing(model=m)
            existing_pricing[m.id] = pricing
            is_new_pricing = True

        if pricing.prompt_price_per_1m == Decimal('0') and pricing.completion_price_per_1m == Decimal('0') and not m.is_free:
            pr_data = raw.get('pricing') or {}
            try:
                p_tok = Decimal(str(pr_data.get('prompt', '0') or '0'))
                c_tok = Decimal(str(pr_data.get('completion', '0') or '0'))
                pricing.prompt_price_per_token = p_tok
                pricing.completion_price_per_token = c_tok
                pricing.prompt_price_per_1m = (p_tok * Decimal('1000000')).quantize(Decimal('0.000001'))
                pricing.completion_price_per_1m = (c_tok * Decimal('1000000')).quantize(Decimal('0.000001'))
            except Exception:
                pass

        if is_new_pricing:
            pricing_to_create.append(pricing)
            filled_pricing += 1
        else:
            pricing_to_update.append(pricing)

        # ----------------------------------------------------
        # 3. Backfill / Calibrate ModelBenchmark
        # ----------------------------------------------------
        bm = existing_benchmarks.get(m.id)
        is_new_bm = False
        if not bm:
            bm = ModelBenchmark(model=m)
            existing_benchmarks[m.id] = bm
            is_new_bm = True

        # If model is non-LLM, keep zero benchmarks
        if m.category != 'llm':
            bm.intelligence_index = 0.0
            bm.coding_index = 0.0
            bm.agentic_index = 0.0
        else:
            # If intelligence is missing or zero, interpolate realistically
            if bm.intelligence_index == 0.0:
                bm.intelligence_index = estimate_model_intelligence(m.name, m.slug, spec.context_length)

            if bm.coding_index == 0.0:
                bm.coding_index = round(bm.intelligence_index * 0.94, 1)

            if bm.agentic_index == 0.0:
                bm.agentic_index = round(bm.intelligence_index * 0.88, 1)

            if bm.swe_bench_score == 0.0:
                bm.swe_bench_score = round(bm.coding_index * 0.80, 1)

            if bm.arena_elo == 0.0:
                bm.arena_elo = round(1000.0 + (bm.intelligence_index * 4.2), 1)

        if is_new_bm:
            benchmarks_to_create.append(bm)
            filled_benchmarks += 1
        else:
            benchmarks_to_update.append(bm)

    with transaction.atomic():
        if models_to_update:
            LLMModel.objects.bulk_update(models_to_update, fields=['category'], batch_size=100)

        if specs_to_create:
            ModelSpecification.objects.bulk_create(specs_to_create, ignore_conflicts=True, batch_size=100)
        if specs_to_update:
            ModelSpecification.objects.bulk_update(
                specs_to_update,
                fields=['context_length', 'max_completion_tokens', 'modality', 'is_multimodal', 'supports_vision', 'supports_audio', 'supports_tools'],
                batch_size=100
            )

        if pricing_to_create:
            ModelPricing.objects.bulk_create(pricing_to_create, ignore_conflicts=True, batch_size=100)
        if pricing_to_update:
            ModelPricing.objects.bulk_update(
                pricing_to_update,
                fields=['prompt_price_per_token', 'completion_price_per_token', 'prompt_price_per_1m', 'completion_price_per_1m'],
                batch_size=100
            )

        if benchmarks_to_create:
            ModelBenchmark.objects.bulk_create(benchmarks_to_create, ignore_conflicts=True, batch_size=100)
        if benchmarks_to_update:
            ModelBenchmark.objects.bulk_update(
                benchmarks_to_update,
                fields=['intelligence_index', 'coding_index', 'agentic_index', 'swe_bench_score', 'arena_elo', 'tokens_per_second', 'time_to_first_token'],
                batch_size=100
            )

    print(f"[Fill Nulls] Completed backfill across {len(models)} models.")
    return True
