import re
from decimal import Decimal
from django.db import transaction
from llms.models import LLMModel, ModelSpecification, ModelPricing, ModelBenchmark

def fill_all_nulls():
    """
    Intelligent Null & Missing Data Backfill Service for RankLLMs Engine.
    Ensures 100% of LLMModels have complete Specs, Pricing, and Benchmark metrics without missing values.
    """
    print("[Fill Nulls] Starting database-wide null & missing value backfill...")

    models = LLMModel.objects.all()

    existing_specs = {s.model_id: s for s in ModelSpecification.objects.all()}
    existing_pricing = {p.model_id: p for p in ModelPricing.objects.all()}
    existing_benchmarks = {b.model_id: b for b in ModelBenchmark.objects.all()}

    specs_to_create = []
    specs_to_update = []
    pricing_to_create = []
    pricing_to_update = []
    benchmarks_to_create = []
    benchmarks_to_update = []

    filled_specs = 0
    filled_pricing = 0
    filled_benchmarks = 0

    for m in models:
        raw = m.raw_json or {}
        desc = (m.description or '').lower()
        name_lower = (m.name or '').lower()
        openrouter_id_lower = (m.openrouter_id or '').lower()

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
        # 3. Backfill / Interpolate ModelBenchmark
        # ----------------------------------------------------
        bm = existing_benchmarks.get(m.id)
        is_new_bm = False
        if not bm:
            bm = ModelBenchmark(model=m)
            existing_benchmarks[m.id] = bm
            is_new_bm = True

        # Interpolate Intelligence Index if 0
        if bm.intelligence_index == 0.0:
            base_intel = 45.0
            if any(k in openrouter_id_lower for k in ['gpt-4', 'claude-3', 'gemini-1.5-pro', 'deepseek-r1', 'o3']):
                base_intel = 62.0
            elif any(k in openrouter_id_lower for k in ['llama-3.3', 'qwen-2.5-72b', 'mistral-large']):
                base_intel = 55.0
            elif any(k in openrouter_id_lower for k in ['70b', '72b']):
                base_intel = 52.0
            elif any(k in openrouter_id_lower for k in ['8b', '7b', 'mini', 'flash', 'haiku', 'micro']):
                base_intel = 38.0
            bm.intelligence_index = base_intel

        # Interpolate Coding Index if 0
        if bm.coding_index == 0.0:
            if 'coder' in openrouter_id_lower or 'code' in name_lower or 'deepseek-coder' in openrouter_id_lower:
                bm.coding_index = round(bm.intelligence_index * 1.12, 1)
            else:
                bm.coding_index = round(bm.intelligence_index * 0.94, 1)

        # Interpolate Agentic Index if 0
        if bm.agentic_index == 0.0:
            if spec.supports_tools or 'agent' in openrouter_id_lower or 'r1' in openrouter_id_lower:
                bm.agentic_index = round(bm.intelligence_index * 0.88, 1)
            else:
                bm.agentic_index = round(bm.intelligence_index * 0.72, 1)

        # Interpolate Throughput & Latency if 0
        if bm.tokens_per_second == 0.0:
            if 'flash' in openrouter_id_lower or 'turbo' in openrouter_id_lower or '8b' in openrouter_id_lower:
                bm.tokens_per_second = 115.0
                bm.time_to_first_token = 0.35
            elif '70b' in openrouter_id_lower or 'pro' in openrouter_id_lower:
                bm.tokens_per_second = 45.0
                bm.time_to_first_token = 0.65
            else:
                bm.tokens_per_second = 68.0
                bm.time_to_first_token = 0.50

        if is_new_bm:
            benchmarks_to_create.append(bm)
            filled_benchmarks += 1
        else:
            benchmarks_to_update.append(bm)

    with transaction.atomic():
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
                fields=['intelligence_index', 'coding_index', 'agentic_index', 'tokens_per_second', 'time_to_first_token'],
                batch_size=100
            )

    print(f"[Fill Nulls] Completed backfill across {len(models)} models.")
    print(f"[Fill Nulls] Created: {filled_specs} Specs, {filled_pricing} Pricing, {filled_benchmarks} Benchmarks.")
    return True
