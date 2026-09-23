import re
from decimal import Decimal
from django.db import transaction
from llms.models import ORModel, ORBench, AAModel, AABench, RankIndex


def normalize_slug(s: str) -> str:
    """
    Normalizes model IDs, slugs, and names into a canonical key.
    """
    if not s:
        return ''
    s = s.lower().strip()
    if '/' in s:
        s = s.split('/')[-1]
    s = s.split(':')[0]
    # Remove version dates like -20241022 or -0613
    s = re.sub(r'-\d{8}$', '', s)
    s = re.sub(r'[^a-z0-9]', '', s)
    return s


def extract_provider(name: str, slug: str, or_id: str, creator: str) -> str:
    """
    Derives clean provider name.
    """
    combined = f"{name} {slug} {or_id} {creator}".lower()
    if 'anthropic' in combined or 'claude' in combined:
        return 'Anthropic'
    elif 'openai' in combined or 'gpt' in combined or 'o1' in combined or 'o3' in combined:
        return 'OpenAI'
    elif 'google' in combined or 'gemini' in combined or 'gemma' in combined:
        return 'Google'
    elif 'deepseek' in combined:
        return 'DeepSeek'
    elif 'meta' in combined or 'llama' in combined:
        return 'Meta'
    elif 'mistral' in combined or 'mixtral' in combined or 'codestral' in combined or 'ministral' in combined:
        return 'Mistral'
    elif 'x-ai' in combined or 'grok' in combined or 'xai' in combined:
        return 'xAI'
    elif 'qwen' in combined or 'alibaba' in combined:
        return 'Qwen / Alibaba'
    elif 'cohere' in combined or 'command' in combined:
        return 'Cohere'
    elif 'amazon' in combined or 'nova' in combined:
        return 'Amazon'
    elif 'nvidia' in combined or 'nemotron' in combined:
        return 'NVIDIA'
    elif 'microsoft' in combined or 'phi' in combined:
        return 'Microsoft'
    elif creator and creator != 'Independent':
        return creator
    elif '/' in or_id:
        return or_id.split('/')[0].capitalize()
    return 'Independent'


def is_open_weight_model(name: str, slug: str, or_id: str) -> bool:
    s = f"{name} {slug} {or_id}".lower()
    open_keywords = [
        'llama', 'deepseek', 'qwen', 'mistral', 'mixtral', 'gemma',
        'phi', 'nemotron', 'starcoder', 'codellama', 'olmo', 'smollm',
        'hermes', 'openhermes', 'wizardlm', 'command-r', 'kimi', 'gpt-oss'
    ]
    return any(k in s for k in open_keywords)


def merge_and_build_rankindex():
    """
    Merges all 4 source tables (ormodels, orbench, aamodels, aabanch)
    into the master unified table 'rankindex'.
    """
    print("[RankIndex] 1. Loading data from 4 source tables...")
    or_models = list(ORModel.objects.all())
    or_benches = list(ORBench.objects.all())
    aa_models = list(AAModel.objects.all())
    aa_benches = list(AABench.objects.all())

    # Build lookup dictionaries
    or_model_dict = {}
    for m in or_models:
        k1 = normalize_slug(m.openrouter_id)
        k2 = normalize_slug(m.name)
        if k1:
            or_model_dict[k1] = m
        if k2 and k2 not in or_model_dict:
            or_model_dict[k2] = m

    aa_model_dict = {}
    for m in aa_models:
        k1 = normalize_slug(m.slug)
        k2 = normalize_slug(m.name)
        if k1:
            aa_model_dict[k1] = m
        if k2 and k2 not in aa_model_dict:
            aa_model_dict[k2] = m

    aa_bench_dict = {}
    for b in aa_benches:
        k1 = normalize_slug(b.model_slug)
        k2 = normalize_slug(b.model_name)
        if k1:
            aa_bench_dict[k1] = b
        if k2 and k2 not in aa_bench_dict:
            aa_bench_dict[k2] = b

    or_bench_dict = {}
    for b in or_benches:
        k1 = normalize_slug(b.model_permaslug)
        k2 = normalize_slug(b.display_name)
        for k in [k1, k2]:
            if k:
                if k not in or_bench_dict:
                    or_bench_dict[k] = []
                or_bench_dict[k].append(b)

    # Collect all unique canonical items
    canonical_items = {}

    # Pass 1: Process Artificial Analysis models & evaluations (High quality benchmark source)
    for m in aa_models:
        k = normalize_slug(m.slug) or normalize_slug(m.name)
        if not k:
            continue

        b_item = aa_bench_dict.get(k)
        or_m = or_model_dict.get(k)
        or_b_list = or_bench_dict.get(k, [])

        slug_val = m.slug or k
        name_val = m.name or (or_m.name if or_m else slug_val)
        prov = extract_provider(name_val, slug_val, or_m.openrouter_id if or_m else '', m.creator_name)

        # Context & Pricing
        ctx = m.context_window or (or_m.context_length if or_m else 0)
        p_in = m.prompt_price_per_1m or (or_m.prompt_price_per_1m if or_m else Decimal('0'))
        p_out = m.completion_price_per_1m or (or_m.completion_price_per_1m if or_m else Decimal('0'))

        # Benchmark fields from AA
        intel = b_item.intelligence_index if b_item else 0.0
        coding = b_item.coding_index if b_item else 0.0
        math_i = b_item.math_index if b_item else 0.0
        tb_hard = b_item.terminalbench_hard if b_item else None
        tb_v2 = b_item.terminalbench_v2_1 if b_item else None
        gpqa = b_item.gpqa if b_item else None
        mmlu = b_item.mmlu_pro if b_item else None
        hle = b_item.hle if b_item else None
        livecode = b_item.livecodebench if b_item else None
        scicode = b_item.scicode if b_item else None
        math500 = b_item.math_500 if b_item else None
        aime25 = b_item.aime_25 if b_item else None
        ifbench = b_item.ifbench if b_item else None
        lcr = b_item.lcr if b_item else None
        tau2 = b_item.tau2 if b_item else None
        tau_b = b_item.tau_banking if b_item else None
        tps = b_item.tokens_per_second if b_item else 0.0
        ttft = b_item.time_to_first_token if b_item else 0.0

        # Check OpenRouter Benchmarks for extra Design Arena ELO or GPQA accuracy
        da_elo = None
        da_win = None
        for ob in or_b_list:
            if ob.source == 'design-arena' and ob.elo:
                if da_elo is None or ob.elo > da_elo:
                    da_elo = ob.elo
                    da_win = ob.win_rate
            elif ob.source == 'openrouter' and ob.accuracy and gpqa is None:
                gpqa = ob.accuracy

        sources_list = ['artificial-analysis']
        if or_m:
            sources_list.append('openrouter')
        if da_elo:
            sources_list.append('design-arena')

        canonical_items[k] = {
            'canonical_slug': slug_val,
            'name': name_val,
            'provider': prov,
            'author_slug': m.creator_slug or (or_m.author if or_m else ''),
            'openrouter_id': or_m.openrouter_id if or_m else '',
            'aa_slug': m.slug,
            'description': or_m.description if (or_m and or_m.description) else f"{name_val} by {prov}.",
            'release_date': m.release_date,
            'is_open_weight': is_open_weight_model(name_val, slug_val, or_m.openrouter_id if or_m else ''),
            'is_free': (p_in == Decimal('0') and p_out == Decimal('0')),
            'intelligence_index': intel,
            'coding_index': coding,
            'math_index': math_i,
            'terminalbench_hard': tb_hard,
            'terminalbench_v2_1': tb_v2,
            'gpqa_diamond': gpqa,
            'mmlu_pro': mmlu,
            'hle': hle,
            'livecodebench': livecode,
            'scicode': scicode,
            'math_500': math500,
            'aime_25': aime25,
            'design_arena_elo': da_elo,
            'design_arena_win_rate': da_win,
            'ifbench': ifbench,
            'lcr': lcr,
            'tau2': tau2,
            'tau_banking': tau_b,
            'context_length': ctx,
            'max_output_tokens': m.max_output_tokens,
            'prompt_price_per_1m': p_in,
            'completion_price_per_1m': p_out,
            'tokens_per_second': tps,
            'time_to_first_token': ttft,
            'has_openrouter': bool(or_m),
            'has_artificial_analysis': True,
            'has_design_arena': bool(da_elo),
            'sources': sources_list,
            'raw_data': {
                'aa_model': m.raw_json,
                'or_model': or_m.raw_json if or_m else None,
            }
        }

    # Pass 2: Process OpenRouter models that weren't in AA
    for m in or_models:
        k = normalize_slug(m.openrouter_id) or normalize_slug(m.name)
        if not k or k in canonical_items:
            continue

        slug_val = m.canonical_slug or m.openrouter_id.replace('/', '-')
        name_val = m.name or slug_val
        prov = extract_provider(name_val, slug_val, m.openrouter_id, m.author)
        or_b_list = or_bench_dict.get(k, [])

        da_elo = None
        da_win = None
        gpqa_acc = None
        intel_val = 0.0
        code_val = 0.0

        for ob in or_b_list:
            if ob.source == 'design-arena' and ob.elo:
                if da_elo is None or ob.elo > da_elo:
                    da_elo = ob.elo
                    da_win = ob.win_rate
            elif ob.source == 'openrouter' and ob.accuracy:
                gpqa_acc = ob.accuracy
            elif ob.source == 'artificial-analysis':
                if ob.intelligence_index:
                    intel_val = ob.intelligence_index
                if ob.coding_index:
                    code_val = ob.coding_index

        sources_list = ['openrouter']
        if da_elo:
            sources_list.append('design-arena')

        canonical_items[k] = {
            'canonical_slug': slug_val,
            'name': name_val,
            'provider': prov,
            'author_slug': m.author,
            'openrouter_id': m.openrouter_id,
            'aa_slug': '',
            'description': m.description or f"{name_val} frontier AI model by {prov}.",
            'release_date': None,
            'is_open_weight': is_open_weight_model(name_val, slug_val, m.openrouter_id),
            'is_free': m.is_free,
            'intelligence_index': intel_val,
            'coding_index': code_val,
            'math_index': 0.0,
            'terminalbench_hard': None,
            'terminalbench_v2_1': None,
            'gpqa_diamond': gpqa_acc,
            'mmlu_pro': None,
            'hle': None,
            'livecodebench': None,
            'scicode': None,
            'math_500': None,
            'aime_25': None,
            'design_arena_elo': da_elo,
            'design_arena_win_rate': da_win,
            'ifbench': None,
            'lcr': None,
            'tau2': None,
            'tau_banking': None,
            'context_length': m.context_length,
            'max_output_tokens': None,
            'prompt_price_per_1m': m.prompt_price_per_1m,
            'completion_price_per_1m': m.completion_price_per_1m,
            'tokens_per_second': 0.0,
            'time_to_first_token': 0.0,
            'has_openrouter': True,
            'has_artificial_analysis': False,
            'has_design_arena': bool(da_elo),
            'sources': sources_list,
            'raw_data': {
                'or_model': m.raw_json
            }
        }

    # Pass 3: Calculate unified RankLLMs Composite Index (0-100)
    print(f"[RankIndex] 2. Computing composite RankLLMs Index across {len(canonical_items)} unique models...")
    items_list = list(canonical_items.values())

    for item in items_list:
        intel = float(item['intelligence_index'] or 0.0)
        code = float(item['coding_index'] or (item['livecodebench'] * 100 if item['livecodebench'] else 0.0))
        gpqa = float(item['gpqa_diamond'] * 100 if item['gpqa_diamond'] else 0.0)
        tb = float(item['terminalbench_hard'] * 100 if item['terminalbench_hard'] else (item['terminalbench_v2_1'] * 100 if item['terminalbench_v2_1'] else 0.0))
        aime = float(item['aime_25'] * 100 if item['aime_25'] else (item['math_index'] or 0.0))
        elo = float(item['design_arena_elo'] or 0.0)

        # Coding-weighted composite: newer models win on coding focus.
        # code 40%, intel 30%, tb 10%, gpqa 10%, aime 5%, elo 5% (renormalized over present scores)
        score_parts = 0.0
        weight_sum = 0.0
        if intel > 0:
            score_parts += (intel * 1.4) * 0.30  # AA intelligence is 0-70 scale
            weight_sum += 0.30
        if code > 0:
            score_parts += code * 0.40
            weight_sum += 0.40
        if gpqa > 0:
            score_parts += gpqa * 0.10
            weight_sum += 0.10
        if tb > 0:
            score_parts += tb * 0.10
            weight_sum += 0.10
        if aime > 0:
            score_parts += aime * 0.05
            weight_sum += 0.05
        if elo > 0:
            score_parts += ((elo - 1000) / 5.0) * 0.05  # Map 1400 ELO to ~80 score
            weight_sum += 0.05

        calc_index = (score_parts / weight_sum) if weight_sum > 0 else 0.0

        item['rankllms_index'] = round(min(100.0, max(0.0, calc_index)), 1)

    # Sort and assign ranks (coding as first tiebreak so coding-strong models rise)
    items_list.sort(key=lambda x: (x['rankllms_index'], x['coding_index'], x['intelligence_index']), reverse=True)
    for idx, item in enumerate(items_list):
        item['rank_overall'] = idx + 1

    # Assign coding rank
    by_coding = sorted(items_list, key=lambda x: (x['coding_index'] or (x['livecodebench'] or 0.0), x['rankllms_index']), reverse=True)
    for idx, item in enumerate(by_coding):
        item['rank_coding'] = idx + 1

    # Assign reasoning rank
    by_reasoning = sorted(items_list, key=lambda x: (x['gpqa_diamond'] or 0.0, x['aime_25'] or 0.0, x['rankllms_index']), reverse=True)
    for idx, item in enumerate(by_reasoning):
        item['rank_reasoning'] = idx + 1

    # Assign value rank (Intelligence per total cost)
    by_value = sorted(items_list, key=lambda x: (x['rankllms_index'] / max(0.05, float(x['prompt_price_per_1m'] + x['completion_price_per_1m'])), x['rankllms_index']), reverse=True)
    for idx, item in enumerate(by_value):
        item['rank_value'] = idx + 1

    # Bulk insert into rankindex table
    print(f"[RankIndex] 3. Saving {len(items_list)} merged models into 'rankindex' table...")
    rankindex_objects = [
        RankIndex(
            canonical_slug=item['canonical_slug'],
            name=item['name'],
            provider=item['provider'],
            author_slug=item['author_slug'],
            openrouter_id=item['openrouter_id'],
            aa_slug=item['aa_slug'],
            description=item['description'],
            release_date=item['release_date'],
            is_open_weight=item['is_open_weight'],
            is_free=item['is_free'],
            rankllms_index=item['rankllms_index'],
            rank_overall=item['rank_overall'],
            rank_coding=item['rank_coding'],
            rank_reasoning=item['rank_reasoning'],
            rank_value=item['rank_value'],
            intelligence_index=item['intelligence_index'],
            coding_index=item['coding_index'],
            math_index=item['math_index'],
            terminalbench_hard=item['terminalbench_hard'],
            terminalbench_v2_1=item['terminalbench_v2_1'],
            gpqa_diamond=item['gpqa_diamond'],
            mmlu_pro=item['mmlu_pro'],
            hle=item['hle'],
            livecodebench=item['livecodebench'],
            scicode=item['scicode'],
            math_500=item['math_500'],
            aime_25=item['aime_25'],
            design_arena_elo=item['design_arena_elo'],
            design_arena_win_rate=item['design_arena_win_rate'],
            ifbench=item['ifbench'],
            lcr=item['lcr'],
            tau2=item['tau2'],
            tau_banking=item['tau_banking'],
            context_length=item['context_length'],
            max_output_tokens=item['max_output_tokens'],
            prompt_price_per_1m=item['prompt_price_per_1m'],
            completion_price_per_1m=item['completion_price_per_1m'],
            tokens_per_second=item['tokens_per_second'],
            time_to_first_token=item['time_to_first_token'],
            has_openrouter=item['has_openrouter'],
            has_artificial_analysis=item['has_artificial_analysis'],
            has_design_arena=item['has_design_arena'],
            sources=item['sources'],
            raw_data=item['raw_data']
        )
        for item in items_list
    ]

    with transaction.atomic():
        RankIndex.objects.all().delete()
        RankIndex.objects.bulk_create(rankindex_objects, batch_size=250)

    print(f"[RankIndex] Successfully created {len(rankindex_objects)} rows in 'rankindex' table!")
    return {
        "status": "success",
        "total_merged_models": len(rankindex_objects),
        "source_ormodels": len(or_models),
        "source_orbench": len(or_benches),
        "source_aamodels": len(aa_models),
        "source_aabanch": len(aa_benches)
    }
