from typing import List, Optional
from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel, Field
from ninja import NinjaAPI, Query, Schema
from django.shortcuts import get_object_or_404
from django.db.models import Q, Count, F
from .models import (
    Provider, LLMModel, ModelSpecification, ModelPricing,
    ModelBenchmark, WeeklyTop10Ranking, PricingHistory,
    DailyModelRanking, AppRanking, TaskClassification, APIKey,
    ORModel, ORBench, AAModel, AABench, RankIndex, ModelsDevModel
)

from .services.openrouter_sync import sync_openrouter_models
from .services.sync_all import run_master_sync
from .services.deduplication import deduplicate_models, get_clean_model_name
from .services.openrouter_benchmarks_service import fetch_openrouter_unified_benchmarks



api = NinjaAPI(
    title="RankLLMs Engine API",
    version="1.0.0",
    description=(
        "Free high-performance API powering LLM leaderboards, open-weights rankings, "
        "model comparisons, and weekly top 10 charts. "
        "Data sources: OpenRouter, Artificial Analysis, and models.dev. "
        "Product: https://rankllms.com · Maintainer: https://codaipro.com"
    ),
    docs_url="/docs"
)


# Pydantic Schemas

class ProviderSchema(Schema):
    id: int
    name: str
    slug: str
    website: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[str] = None
    model_count: Optional[int] = None


class ModelSpecSchema(Schema):
    context_length: int
    max_completion_tokens: Optional[int] = None
    modality: str
    tokenizer: str
    instruct_type: Optional[str] = None
    is_multimodal: bool
    supports_vision: bool
    supports_audio: bool
    supports_tools: bool
    supports_json_schema: bool


class ModelPricingSchema(Schema):
    prompt_price_per_1m: Decimal
    completion_price_per_1m: Decimal
    image_price: Decimal
    request_price: Decimal


class ModelBenchmarkSchema(Schema):
    rankllms_index: float
    intelligence_index: float
    coding_index: float
    agentic_index: float
    swe_bench_score: float
    human_eval_score: float
    mmlu_score: float
    arena_elo: float
    tokens_per_second: float
    time_to_first_token: float

    @staticmethod
    def resolve_rankllms_index(obj):
        return getattr(obj, 'intelligence_index', 0.0)



class PricingHistorySchema(Schema):
    prompt_price_per_1m: Decimal
    completion_price_per_1m: Decimal
    recorded_at: datetime


class LLMModelDetailSchema(Schema):
    id: int
    openrouter_id: str
    slug: str
    name: str
    category: str
    provider: ProviderSchema
    description: str
    is_open_weight: bool
    license: str
    is_free: bool
    is_active: bool
    created_at_openrouter: Optional[datetime] = None
    spec: Optional[ModelSpecSchema] = None
    pricing: Optional[ModelPricingSchema] = None
    benchmark: Optional[ModelBenchmarkSchema] = None
    price_history: List[PricingHistorySchema]
    last_synced_at: datetime

    @staticmethod
    def resolve_price_history(obj):
        return list(obj.price_history.all()[:10])


class WeeklyTop10Schema(Schema):
    year: int
    week_number: int
    category: str
    category_display: str = Field(..., alias="get_category_display")
    rank: int
    openrouter_id: str = Field(..., alias="model.openrouter_id")
    model_name: str = Field(..., alias="model.name")
    provider_name: str = Field(..., alias="model.provider.name")
    highlight_reason: str

    @staticmethod
    def resolve_category_display(obj):
        return obj.get_category_display()

    @staticmethod
    def resolve_openrouter_id(obj):
        return obj.model.openrouter_id

    @staticmethod
    def resolve_model_name(obj):
        return obj.model.name

    @staticmethod
    def resolve_provider_name(obj):
        return obj.model.provider.name


class AppRankingSchema(Schema):
    rank: int
    app_id: int
    app_name: str
    total_tokens: int
    total_requests: int
    updated_at: datetime


class TaskClassificationSchema(Schema):
    tag: str
    display_name: str
    macro_category: str
    usage_share: float
    token_share: float
    top_models_share: List[dict]


class SyncResponseSchema(Schema):
    status: str
    summary: dict


class ModelFilterSchema(Schema):
    search: Optional[str] = None
    provider: Optional[str] = None
    category: Optional[str] = None
    is_open_weight: Optional[bool] = None
    is_free: Optional[bool] = None
    supports_vision: Optional[bool] = None
    supports_tools: Optional[bool] = None
    min_context: Optional[int] = None
    max_prompt_price_1m: Optional[float] = None
    ordering: Optional[str] = "-rankllms_index"
    dedup: bool = True
    limit: int = Field(50, ge=1, le=1000)

    offset: int = Field(0, ge=0)




class APIKeyCreateSchema(Schema):
    name: str = Field(..., example="RankLLMs Frontend")
    tier: str = Field("free", example="free")


class APIKeyResponseSchema(Schema):
    id: int
    key: str
    name: str
    tier: str
    is_active: bool
    total_requests: int
    created_at: datetime



# API Endpoints

@api.post("/keys/generate", response=APIKeyResponseSchema, tags=["API Key Manager"])
def generate_api_key(request, payload: APIKeyCreateSchema):
    """
    Generate a new Developer API Key (rk_live_...).
    """
    tier = payload.tier.lower() if payload.tier.lower() in ['free', 'pro', 'admin'] else 'free'
    api_key_obj = APIKey.generate_key(name=payload.name, tier=tier)
    return api_key_obj


@api.get("/keys", response=List[APIKeyResponseSchema], tags=["API Key Manager"])
def list_api_keys(request):
    """
    List all active API keys and their usage statistics.
    """
    return list(APIKey.objects.filter(is_active=True).order_by('-created_at'))


@api.get("/health", tags=["System"])

def health_check(request):
    """
    System health status and Neon DB connection check.
    """
    return {
        "status": "healthy",
        "database": "Neon PostgreSQL",
        "total_models": LLMModel.objects.count(),
        "total_providers": Provider.objects.count(),
        "timestamp": datetime.now()
    }


@api.get("/providers", response=List[ProviderSchema], tags=["Providers"])
def list_providers(request):
    """
    List AI providers with active model counts.
    """
    return Provider.objects.annotate(model_count=Count('models')).filter(is_active=True)


@api.get("/models", response=dict, tags=["Models Catalog"])
def list_models(request, filters: ModelFilterSchema = Query(...)):
    """
    Query, search, and filter AI models with specs, pricing, and benchmark indices.
    """
    qs = LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark').filter(is_active=True)

    if filters.search:
        qs = qs.filter(
            Q(name__icontains=filters.search) |
            Q(openrouter_id__icontains=filters.search) |
            Q(description__icontains=filters.search) |
            Q(provider__name__icontains=filters.search)
        )

    if filters.provider:
        qs = qs.filter(Q(provider__slug=filters.provider) | Q(provider__name__icontains=filters.provider))

    if filters.category:
        qs = qs.filter(category=filters.category)

    if filters.is_open_weight is not None:
        qs = qs.filter(is_open_weight=filters.is_open_weight)

    if filters.is_free is not None:
        qs = qs.filter(is_free=filters.is_free)

    if filters.supports_vision is not None:
        qs = qs.filter(spec__supports_vision=filters.supports_vision)

    if filters.supports_tools is not None:
        qs = qs.filter(spec__supports_tools=filters.supports_tools)

    if filters.min_context is not None:
        qs = qs.filter(spec__context_length__gte=filters.min_context)

    if filters.max_prompt_price_1m is not None:
        qs = qs.filter(pricing__prompt_price_per_1m__lte=filters.max_prompt_price_1m)

    # Ordering mapping defaulting to most intelligent models at top
    order_map = {
        'rankllms_index': F('benchmark__intelligence_index').desc(nulls_last=True),
        '-rankllms_index': F('benchmark__intelligence_index').desc(nulls_last=True),
        'intelligence_index': F('benchmark__intelligence_index').desc(nulls_last=True),
        '-intelligence_index': F('benchmark__intelligence_index').desc(nulls_last=True),
        'coding_index': F('benchmark__coding_index').desc(nulls_last=True),
        '-coding_index': F('benchmark__coding_index').desc(nulls_last=True),
        'agentic_index': F('benchmark__agentic_index').desc(nulls_last=True),
        '-agentic_index': F('benchmark__agentic_index').desc(nulls_last=True),
        'swe_bench': F('benchmark__swe_bench_score').desc(nulls_last=True),
        '-swe_bench': F('benchmark__swe_bench_score').desc(nulls_last=True),
        'prompt_price': F('pricing__prompt_price_per_1m').asc(nulls_last=True),
        '-prompt_price': F('pricing__prompt_price_per_1m').desc(nulls_last=True),
        'context_length': F('spec__context_length').desc(nulls_last=True),
        '-context_length': F('spec__context_length').desc(nulls_last=True),
        'name': 'name',
        '-name': '-name',
    }

    sort_field = order_map.get(filters.ordering, F('benchmark__intelligence_index').desc(nulls_last=True))
    qs = qs.order_by(sort_field, F('benchmark__coding_index').desc(nulls_last=True))

    all_models = list(qs)
    if filters.dedup:
        all_models = deduplicate_models(all_models)

    total = len(all_models)
    models = all_models[filters.offset:filters.offset + filters.limit]


    items = []
    for m in models:
        spec = getattr(m, 'spec', None)
        pricing = getattr(m, 'pricing', None)
        benchmark = getattr(m, 'benchmark', None)

        items.append({
            "id": m.id,
            "openrouter_id": m.openrouter_id,
            "slug": m.slug,
            "name": get_clean_model_name(m.name, m.provider.name) if filters.dedup else m.name,
            "category": m.category,
            "provider_slug": m.provider.slug,
            "provider_name": m.provider.name,
            "is_open_weight": m.is_open_weight,
            "license": m.license,
            "is_free": m.is_free,
            "context_length": spec.context_length if spec else 0,
            "prompt_price_per_1m": pricing.prompt_price_per_1m if pricing else Decimal('0'),
            "completion_price_per_1m": pricing.completion_price_per_1m if pricing else Decimal('0'),
            "rankllms_index": benchmark.intelligence_index if benchmark else 0.0,
            "intelligence_index": benchmark.intelligence_index if benchmark else 0.0,
            "coding_index": benchmark.coding_index if benchmark else 0.0,
            "agentic_index": benchmark.agentic_index if benchmark else 0.0,
            "swe_bench_score": benchmark.swe_bench_score if benchmark else 0.0,
            "arena_elo": benchmark.arena_elo if benchmark else 0.0,
            "last_synced_at": m.last_synced_at
        })

    return {
        "total": total,
        "limit": filters.limit,
        "offset": filters.offset,
        "items": items
    }


@api.get("/models/cards", response=List[dict], tags=["Static Cards API"])
def get_model_cards_for_static_site(request, limit: int = 200, dedup: bool = True):
    """
    Dedicated Model Cards Export API endpoint.
    Returns structured model cards array matching LLMModel TypeScript interface for Astro & Next.js static site generation (SSG).
    """
    qs = LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark').filter(is_active=True, category='llm')
    qs = qs.order_by(F('benchmark__intelligence_index').desc(nulls_last=True), F('benchmark__coding_index').desc(nulls_last=True))

    all_models = list(qs)
    if dedup:
        all_models = deduplicate_models(all_models)

    models = all_models[:limit]
    cards = []

    for m in models:
        spec = getattr(m, 'spec', None)
        pricing = getattr(m, 'pricing', None)
        bm = getattr(m, 'benchmark', None)

        desc = m.description if m.description else f"{m.name} is a high-performance AI model developed by {m.provider.name}."

        strengths = []
        if bm and bm.coding_index >= 70:
            strengths.append("Exceptional Code Generation")
        if bm and bm.agentic_index >= 65:
            strengths.append("Advanced Agentic Tool Use")
        if spec and spec.context_length >= 128000:
            strengths.append(f"Huge {spec.context_length // 1000}K Context Window")
        if m.is_free:
            strengths.append("100% Free API Access")
        if m.is_open_weight:
            strengths.append("Open-Weight / Self-Hostable")
        if spec and spec.supports_vision:
            strengths.append("Multimodal Vision")
        if not strengths:
            strengths = ["Fast Latency", "General Instruction Following"]

        cards.append({
            "id": m.slug or m.openrouter_id.replace('/', '-'),
            "openrouter_id": m.openrouter_id,
            "name": get_clean_model_name(m.name),
            "provider": m.provider.name,
            "category": m.category,
            "isOpenWeight": m.is_open_weight,
            "isFree": m.is_free,
            "contextWindow": spec.context_length if spec else 128000,
            "inputPricePerM": float(pricing.prompt_price_per_1m) if pricing else 0.0,
            "outputPricePerM": float(pricing.completion_price_per_1m) if pricing else 0.0,
            "rankllmsIndex": bm.intelligence_index if bm else 0.0,
            "intelligenceIndex": bm.intelligence_index if bm else 0.0,
            "codingIndex": bm.coding_index if bm else 0.0,
            "agenticIndex": bm.agentic_index if bm else 0.0,
            "sweBenchScore": bm.swe_bench_score if bm else 0.0,
            "humanEvalScore": bm.human_eval_score if bm else 0.0,
            "mmluScore": bm.mmlu_score if bm else 0.0,
            "arenaElo": bm.arena_elo if bm else 0.0,
            "speedTps": bm.tokens_per_second if bm else 0.0,
            "timeToFirstToken": bm.time_to_first_token if bm else 0.0,
            "releaseDate": m.created_at_openrouter.strftime("%Y-%m-%d") if m.created_at_openrouter else "2024-01-01",
            "description": desc,
            "strengths": strengths
        })

    return cards


@api.get("/leaderboard", response=dict, tags=["Page 1: LLM Leaderboard"])

def get_main_leaderboard(
    request,
    sort_by: str = "intelligence",
    dedup: bool = True,
    exclude_nulls: bool = True,
    limit: int = Field(200, ge=1, le=1000)
):
    """
    Main LLM Leaderboard API.
    Ranks models by Intelligence Index (primary) then Coding Index (secondary) by default.
    Supports sorting by Coding Index, SWE-bench, Agentic Index, Context, or Price.
    With exclude_nulls=true (default), only models with verified Intelligence AND Coding scores are ranked.
    """
    qs = LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark').filter(is_active=True, category='llm')

    if exclude_nulls:
        qs = qs.filter(benchmark__intelligence_index__gt=0, benchmark__coding_index__gt=0)

    if sort_by == "coding":
        qs = qs.order_by(F('benchmark__coding_index').desc(nulls_last=True), F('benchmark__intelligence_index').desc(nulls_last=True))
    elif sort_by == "swe_bench":
        qs = qs.order_by(F('benchmark__swe_bench_score').desc(nulls_last=True), F('benchmark__coding_index').desc(nulls_last=True))
    elif sort_by == "agentic":
        qs = qs.order_by(F('benchmark__agentic_index').desc(nulls_last=True), F('benchmark__intelligence_index').desc(nulls_last=True))
    elif sort_by == "context":
        qs = qs.order_by(F('spec__context_length').desc(nulls_last=True), F('benchmark__intelligence_index').desc(nulls_last=True))
    elif sort_by == "cost":
        qs = qs.filter(is_free=False, pricing__prompt_price_per_1m__gt=0).order_by(F('pricing__prompt_price_per_1m').asc(nulls_last=True))
    else:
        qs = qs.order_by(F('benchmark__intelligence_index').desc(nulls_last=True), F('benchmark__coding_index').desc(nulls_last=True))


    all_models = list(qs)
    if dedup:
        all_models = deduplicate_models(all_models)
    models = all_models[:limit]

    rankings = []
    for idx, m in enumerate(models, start=1):
        spec = getattr(m, 'spec', None)
        pricing = getattr(m, 'pricing', None)
        benchmark = getattr(m, 'benchmark', None)

        rankings.append({
            "rank": idx,
            "id": m.id,
            "openrouter_id": m.openrouter_id,
            "slug": m.slug,
            "name": get_clean_model_name(m.name) if dedup else m.name,
            "provider": m.provider.name,
            "is_open_weight": m.is_open_weight,
            "license": m.license,
            "rankllms_index": benchmark.intelligence_index if benchmark else 0.0,
            "intelligence_index": benchmark.intelligence_index if benchmark else 0.0,
            "coding_index": benchmark.coding_index if benchmark else 0.0,

            "agentic_index": benchmark.agentic_index if benchmark else 0.0,
            "swe_bench_score": benchmark.swe_bench_score if benchmark else 0.0,
            "context_length": spec.context_length if spec else 0,
            "prompt_price_per_1m": pricing.prompt_price_per_1m if pricing else Decimal('0'),
            "completion_price_per_1m": pricing.completion_price_per_1m if pricing else Decimal('0'),
            "is_free": m.is_free,
            "is_multimodal": spec.is_multimodal if spec else False,
            "supports_vision": spec.supports_vision if spec else False,
        })

    return {
        "sort_by": sort_by,
        "dedup": dedup,
        "exclude_nulls": exclude_nulls,
        "count": len(rankings),
        "rankings": rankings
    }


@api.get("/benchmarks", response=dict, tags=["Benchmarks API"])
def get_benchmarks_catalog(request, sort_by: str = "rankllms_index", dedup: bool = True, limit: int = Field(50, ge=1, le=1000), offset: int = 0):
    """
    Dedicated Benchmarks API endpoint.
    Returns model benchmark evaluation matrix sorted by rankllms_index (default), coding_index, agentic_index, swe_bench, arena_elo, or speed.
    """
    qs = LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark').filter(is_active=True, category='llm')

    order_map = {
        'rankllms_index': F('benchmark__intelligence_index').desc(nulls_last=True),
        '-rankllms_index': F('benchmark__intelligence_index').desc(nulls_last=True),
        'intelligence_index': F('benchmark__intelligence_index').desc(nulls_last=True),
        'coding_index': F('benchmark__coding_index').desc(nulls_last=True),
        '-coding_index': F('benchmark__coding_index').desc(nulls_last=True),
        'agentic_index': F('benchmark__agentic_index').desc(nulls_last=True),
        '-agentic_index': F('benchmark__agentic_index').desc(nulls_last=True),
        'swe_bench': F('benchmark__swe_bench_score').desc(nulls_last=True),
        '-swe_bench': F('benchmark__swe_bench_score').desc(nulls_last=True),
        'arena_elo': F('benchmark__arena_elo').desc(nulls_last=True),
        'speed': F('benchmark__tokens_per_second').desc(nulls_last=True),
        'latency': F('benchmark__time_to_first_token').asc(nulls_last=True),
    }

    sort_field = order_map.get(sort_by, F('benchmark__intelligence_index').desc(nulls_last=True))
    qs = qs.order_by(sort_field, F('benchmark__coding_index').desc(nulls_last=True))

    all_models = list(qs)
    if dedup:
        all_models = deduplicate_models(all_models)

    total = len(all_models)
    models = all_models[offset:offset + limit]

    items = []
    for idx, m in enumerate(models, start=offset + 1):
        spec = getattr(m, 'spec', None)
        pricing = getattr(m, 'pricing', None)
        benchmark = getattr(m, 'benchmark', None)

        items.append({
            "rank": idx,
            "id": m.id,
            "openrouter_id": m.openrouter_id,
            "slug": m.slug,
            "name": get_clean_model_name(m.name, m.provider.name) if dedup else m.name,
            "provider": m.provider.name,
            "category": m.category,
            "is_open_weight": m.is_open_weight,
            "context_length": spec.context_length if spec else 0,
            "pricing": {
                "prompt_price_per_1m": float(pricing.prompt_price_per_1m) if pricing else 0.0,
                "completion_price_per_1m": float(pricing.completion_price_per_1m) if pricing else 0.0,
                "is_free": m.is_free,
            },
            "benchmarks": {
                "rankllms_index": benchmark.intelligence_index if benchmark else 0.0,
                "intelligence_index": benchmark.intelligence_index if benchmark else 0.0,
                "coding_index": benchmark.coding_index if benchmark else 0.0,
                "agentic_index": benchmark.agentic_index if benchmark else 0.0,
                "swe_bench_score": benchmark.swe_bench_score if benchmark else 0.0,
                "mmlu_score": benchmark.mmlu_score if benchmark else 0.0,
                "human_eval_score": benchmark.human_eval_score if benchmark else 0.0,
                "arena_elo": benchmark.arena_elo if benchmark else 0.0,
                "tokens_per_second": benchmark.tokens_per_second if benchmark else 0.0,
                "time_to_first_token": benchmark.time_to_first_token if benchmark else 0.0,
            }
        })

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort_by": sort_by,
        "dedup": dedup,
        "items": items
    }


@api.get("/benchmarks/openrouter", response=dict, tags=["Benchmarks API"])
def get_openrouter_benchmarks(
    request,
    source: str = "all",
    benchmark_type: str = "all",
    category: str = "all",
    arena: str = "all",
    sort_by: str = "score",
    sort_dir: str = "desc",
    search: str = "",
    limit: int = Field(100, ge=1, le=1500),
    offset: int = 0
):
    """
    OpenRouter Unified Benchmarks Endpoint.
    Aggregates empirical evaluations from:
    1. 'openrouter' (GPQA Diamond, Tau-bench, search evals, Math)
    2. 'design-arena' (Design Arena ELO & Win Rates across webapps, mobile, graphicdesign, fullstack, etc.)
    3. 'artificial-analysis' (Intelligence, Coding, and Agentic indices)
    """
    raw_data = fetch_openrouter_unified_benchmarks()

    # Sources breakdown
    sources_breakdown = {}
    for item in raw_data:
        src = item.get("source", "unknown")
        sources_breakdown[src] = sources_breakdown.get(src, 0) + 1

    # Filter
    filtered = []
    search_lower = search.strip().lower()

    for item in raw_data:
        item_source = item.get("source", "")
        if source != "all" and item_source != source:
            continue

        item_bm_type = item.get("benchmark_type", "")
        if benchmark_type != "all" and item_bm_type != benchmark_type:
            continue

        item_category = item.get("category", "")
        if category != "all" and item_category != category:
            continue

        item_arena = item.get("arena", "")
        if arena != "all" and item_arena != arena:
            continue

        if search_lower:
            display_name = (item.get("display_name") or "").lower()
            slug = (item.get("model_permaslug") or "").lower()
            cat = (item.get("category") or "").lower()
            bm_t = (item.get("benchmark_type") or "").lower()
            if not (search_lower in display_name or search_lower in slug or search_lower in cat or search_lower in bm_t):
                continue

        filtered.append(item)

    # Sorting
    def get_sort_key(x):
        if sort_by == "name":
            return (x.get("display_name") or x.get("model_permaslug") or "").lower()
        elif sort_by == "accuracy":
            return float(x.get("accuracy") or 0.0)
        elif sort_by == "elo":
            return float(x.get("elo") or 0.0)
        elif sort_by == "win_rate":
            return float(x.get("win_rate") or 0.0)
        elif sort_by == "intelligence":
            return float(x.get("intelligence_index") or 0.0)
        elif sort_by == "coding":
            return float(x.get("coding_index") or 0.0)
        elif sort_by == "price":
            pricing = x.get("pricing") or {}
            return float(pricing.get("prompt") or 0.0)
        else: # "score" / default
            # Dynamic composite primary score based on source
            if x.get("accuracy") is not None:
                return float(x.get("accuracy")) * 100.0
            elif x.get("elo") is not None:
                return float(x.get("elo"))
            elif x.get("intelligence_index") is not None:
                return float(x.get("intelligence_index"))
            return 0.0

    reverse = (sort_dir.lower() == "desc")
    if sort_by == "name":
        filtered.sort(key=get_sort_key, reverse=reverse)
    else:
        filtered.sort(key=get_sort_key, reverse=reverse)

    total = len(filtered)
    paginated = filtered[offset:offset + limit]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "source": source,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "sources_breakdown": sources_breakdown,
        "items": paginated
    }


@api.get("/leaderboard/open-weights", response=dict, tags=["Page 2: Open-LLM Leaderboard"])

def get_open_llm_leaderboard(request, sort_by: str = "intelligence", limit: int = 50):
    """
    Open LLM Leaderboard API (Ranks ONLY Open-Source / Open-Weight models like DeepSeek, Llama, Qwen, Mistral).
    """
    qs = LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark').filter(
        is_active=True, category='llm', is_open_weight=True
    )

    if sort_by == "coding":
        qs = qs.order_by('-benchmark__coding_index', '-benchmark__intelligence_index')
    elif sort_by == "swe_bench":
        qs = qs.order_by('-benchmark__swe_bench_score', '-benchmark__coding_index')
    else:
        qs = qs.order_by('-benchmark__intelligence_index', '-benchmark__coding_index')

    models = qs[:limit]
    rankings = []
    for idx, m in enumerate(models, start=1):
        spec = getattr(m, 'spec', None)
        pricing = getattr(m, 'pricing', None)
        benchmark = getattr(m, 'benchmark', None)

        rankings.append({
            "rank": idx,
            "id": m.id,
            "openrouter_id": m.openrouter_id,
            "slug": m.slug,
            "name": m.name,
            "provider": m.provider.name,
            "license": m.license,
            "intelligence_index": benchmark.intelligence_index if benchmark else 0.0,
            "coding_index": benchmark.coding_index if benchmark else 0.0,
            "agentic_index": benchmark.agentic_index if benchmark else 0.0,
            "context_length": spec.context_length if spec else 0,
            "prompt_price_per_1m": pricing.prompt_price_per_1m if pricing else Decimal('0'),
            "completion_price_per_1m": pricing.completion_price_per_1m if pricing else Decimal('0'),
            "is_free": m.is_free,
        })

    return {
        "title": "Open LLM & Open-Weight Leaderboard",
        "sort_by": sort_by,
        "count": len(rankings),
        "rankings": rankings
    }


@api.get("/compare", response=dict, tags=["Page 3: Dynamic Comparison Page"])
def compare_models(request, ids: Optional[str] = None, model_a: Optional[str] = None, model_b: Optional[str] = None):
    """
    Dynamic Comparison API (Returns side-by-side specs, pricing, and benchmark indices formatted for charts and agents).
    Supports either ?ids=model1,model2 or ?model_a=model1&model_b=model2.
    """
    model_ids = []
    if ids:
        model_ids.extend([item.strip() for item in ids.split(',') if item.strip()])
    if model_a:
        model_ids.append(model_a.strip())
    if model_b:
        model_ids.append(model_b.strip())

    # Remove duplicates while preserving order
    unique_ids = []
    for mid in model_ids:
        if mid not in unique_ids:
            unique_ids.append(mid)

    if not unique_ids:
        return {"error": "Please provide model IDs in 'ids' or 'model_a' and 'model_b' parameters"}

    # Flexible matching against slug, openrouter_id, or numeric ID
    q_filter = Q()
    for mid in unique_ids:
        q_filter |= Q(slug__iexact=mid) | Q(openrouter_id__iexact=mid) | Q(slug__icontains=mid) | Q(name__icontains=mid)
        if mid.isdigit():
            q_filter |= Q(id=int(mid))

    models = LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark').filter(q_filter)

    models_list = []
    for m in models:
        spec = getattr(m, 'spec', None)
        pricing = getattr(m, 'pricing', None)
        benchmark = getattr(m, 'benchmark', None)

        models_list.append({
            "id": m.id,
            "openrouter_id": m.openrouter_id,
            "slug": m.slug,
            "name": get_clean_model_name(m.name, m.provider.name),
            "provider": m.provider.name,
            "is_open_weight": m.is_open_weight,
            "license": m.license,
            "description": m.description,
            "specs": {
                "context_length": spec.context_length if spec else 0,
                "max_completion_tokens": spec.max_completion_tokens if spec else None,
                "modality": spec.modality if spec else "",
                "is_multimodal": spec.is_multimodal if spec else False,
                "supports_vision": spec.supports_vision if spec else False,
                "supports_tools": spec.supports_tools if spec else False,
            },
            "pricing": {
                "prompt_price_per_1m": pricing.prompt_price_per_1m if pricing else Decimal('0'),
                "completion_price_per_1m": pricing.completion_price_per_1m if pricing else Decimal('0'),
                "is_free": m.is_free,
            },
            "benchmarks": {
                "rankllms_index": benchmark.intelligence_index if benchmark else 0.0,
                "intelligence_index": benchmark.intelligence_index if benchmark else 0.0,
                "coding_index": benchmark.coding_index if benchmark else 0.0,
                "agentic_index": benchmark.agentic_index if benchmark else 0.0,
                "swe_bench_score": benchmark.swe_bench_score if benchmark else 0.0,
                "arena_elo": benchmark.arena_elo if benchmark else 0.0,
            }
        })

    # Determine winners if 2 models
    winner = {}
    if len(models_list) >= 2:
        m1, m2 = models_list[0], models_list[1]
        m1_intel = m1['benchmarks']['intelligence_index']
        m2_intel = m2['benchmarks']['intelligence_index']
        winner['overall'] = m1['name'] if m1_intel >= m2_intel else m2['name']

        m1_code = m1['benchmarks']['coding_index']
        m2_code = m2['benchmarks']['coding_index']
        winner['coding'] = m1['name'] if m1_code >= m2_code else m2['name']

        m1_price = float(m1['pricing']['prompt_price_per_1m'])
        m2_price = float(m2['pricing']['prompt_price_per_1m'])
        winner['value'] = m1['name'] if m1_price <= m2_price else m2['name']

    return {
        "count": len(models_list),
        "winner": winner,
        "models": models_list
    }


@api.get("/top-10", response=dict, tags=["Page 4: Weekly Top 10 Models"])
def get_weekly_top_10(request, category: str = "coding"):
    """
    Weekly Top 10 Models API across categories (coding, writing_reasoning, open_source, cost_effective, overall).
    """
    curated = WeeklyTop10Ranking.objects.select_related('model', 'model__provider', 'model__benchmark', 'model__pricing', 'model__spec').filter(
        category=category
    ).order_by('-year', '-week_number', 'rank')[:10]

    top_10 = []
    if curated.exists():
        for r in curated:
            m = r.model
            spec = getattr(m, 'spec', None)
            pricing = getattr(m, 'pricing', None)
            benchmark = getattr(m, 'benchmark', None)

            top_10.append({
                "rank": r.rank,
                "openrouter_id": m.openrouter_id,
                "name": m.name,
                "provider": m.provider.name,
                "highlight_reason": r.highlight_reason,
                "intelligence_index": benchmark.intelligence_index if benchmark else 0.0,
                "coding_index": benchmark.coding_index if benchmark else 0.0,
                "prompt_price_per_1m": pricing.prompt_price_per_1m if pricing else Decimal('0'),
                "completion_price_per_1m": pricing.completion_price_per_1m if pricing else Decimal('0'),
            })
    else:
        # Auto-calculate Top 10 from benchmark scores if curated list not set yet
        qs = LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark').filter(is_active=True, category='llm')

        if category == "coding":
            qs = qs.order_by('-benchmark__coding_index', '-benchmark__intelligence_index')
        elif category == "open_source":
            qs = qs.filter(is_open_weight=True).order_by('-benchmark__intelligence_index')
        elif category == "cost_effective":
            qs = qs.filter(is_free=False, pricing__prompt_price_per_1m__gt=0).order_by('pricing__prompt_price_per_1m')
        else:
            qs = qs.order_by('-benchmark__intelligence_index')

        for idx, m in enumerate(qs[:10], start=1):
            spec = getattr(m, 'spec', None)
            pricing = getattr(m, 'pricing', None)
            benchmark = getattr(m, 'benchmark', None)

            top_10.append({
                "rank": idx,
                "openrouter_id": m.openrouter_id,
                "name": m.name,
                "provider": m.provider.name,
                "highlight_reason": f"Auto-ranked #{idx} by {category}",
                "intelligence_index": benchmark.intelligence_index if benchmark else 0.0,
                "coding_index": benchmark.coding_index if benchmark else 0.0,
                "prompt_price_per_1m": pricing.prompt_price_per_1m if pricing else Decimal('0'),
                "completion_price_per_1m": pricing.completion_price_per_1m if pricing else Decimal('0'),
            })

    return {
        "category": category,
        "top_10": top_10
    }


@api.get("/models/{path:identifier}", response=LLMModelDetailSchema, tags=["Models Catalog"])
def get_model_detail(request, identifier: str):
    """
    Get detailed breakdown of a single AI model by openrouter_id, slug, or DB ID.
    """
    identifier_clean = identifier.strip()
    if identifier_clean.isdigit():
        model = get_object_or_404(LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark'), id=int(identifier_clean))
    else:
        model = LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark').filter(
            Q(openrouter_id__iexact=identifier_clean) | 
            Q(slug__iexact=identifier_clean) | 
            Q(openrouter_id__iexact=identifier_clean.replace('-', '/'))
        ).first()
        if not model:
            model = get_object_or_404(LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark'), openrouter_id__icontains=identifier_clean)
    return model


@api.get("/apps", response=List[AppRankingSchema], tags=["Analytics & Usage"])
def list_app_rankings(request):
    """
    Returns top AI applications ranked by total token usage.
    """
    return AppRanking.objects.all()[:50]


@api.get("/task-share", response=List[TaskClassificationSchema], tags=["Analytics & Usage"])
def list_task_classifications(request):
    """
    Returns task classification market share (Workflow Execution, Code Gen, Debugging).
    """
    return TaskClassification.objects.all()


@api.post("/sync", response=dict, tags=["Admin & Data Sync"])
def trigger_master_sync(request):
    """
    Manually trigger full master data sync (OpenRouter + Artificial Analysis + Null Backfill).
    """
    report = run_master_sync()
    return {
        "status": "success",
        "summary": report
    }


# ================= DEDICATED SOURCE ENDPOINTS (ormodels, orbench, aamodels, aabanch) =================

@api.get("/ormodels", response=dict, tags=["Dedicated Raw Tables"])
def list_ormodels(
    request,
    search: str = "",
    author: str = "",
    is_free: Optional[bool] = None,
    sort_by: str = "name",
    sort_dir: str = "asc",
    limit: int = Field(100, ge=1, le=1000),
    offset: int = 0
):
    """
    Direct endpoint for 'ormodels' table (OpenRouter Models Catalog).
    """
    qs = ORModel.objects.all()

    if search:
        s = search.strip()
        qs = qs.filter(Q(name__icontains=s) | Q(openrouter_id__icontains=s) | Q(description__icontains=s))

    if author:
        qs = qs.filter(author__iexact=author.strip())

    if is_free is not None:
        qs = qs.filter(is_free=is_free)

    # Sorting
    order_fields = {
        'name': 'name',
        'context_length': 'context_length',
        'prompt_price': 'prompt_price_per_1m',
        'completion_price': 'completion_price_per_1m',
        'author': 'author',
    }
    field = order_fields.get(sort_by, 'name')
    prefix = '-' if sort_dir.lower() == 'desc' else ''
    qs = qs.order_by(f"{prefix}{field}")

    total = qs.count()
    items = list(qs[offset:offset + limit].values(
        'id', 'openrouter_id', 'name', 'canonical_slug', 'author', 'description',
        'context_length', 'prompt_price_per_1m', 'completion_price_per_1m',
        'is_free', 'architecture', 'top_provider', 'pricing', 'created_at', 'updated_at'
    ))

    return {
        "table": "ormodels",
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "items": items
    }


@api.get("/orbench", response=dict, tags=["Dedicated Raw Tables"])
def list_orbench(
    request,
    source: str = "all",
    benchmark_type: str = "all",
    category: str = "all",
    search: str = "",
    sort_by: str = "score",
    sort_dir: str = "desc",
    limit: int = Field(100, ge=1, le=1500),
    offset: int = 0
):
    """
    Direct endpoint for 'orbench' table (OpenRouter Unified Benchmarks).
    """
    qs = ORBench.objects.all()

    if source != "all":
        qs = qs.filter(source=source.strip())

    if benchmark_type != "all":
        qs = qs.filter(benchmark_type__icontains=benchmark_type.strip())

    if category != "all":
        qs = qs.filter(category__icontains=category.strip())

    if search:
        s = search.strip()
        qs = qs.filter(Q(display_name__icontains=s) | Q(model_permaslug__icontains=s) | Q(category__icontains=s) | Q(benchmark_type__icontains=s))

    # Sources breakdown
    sources_breakdown = {
        'openrouter': ORBench.objects.filter(source='openrouter').count(),
        'design-arena': ORBench.objects.filter(source='design-arena').count(),
        'artificial-analysis': ORBench.objects.filter(source='artificial-analysis').count(),
    }

    # Sorting
    prefix = '-' if sort_dir.lower() == 'desc' else ''
    if sort_by == 'accuracy':
        qs = qs.order_by(f"{prefix}accuracy")
    elif sort_by == 'elo':
        qs = qs.order_by(f"{prefix}elo")
    elif sort_by == 'win_rate':
        qs = qs.order_by(f"{prefix}win_rate")
    elif sort_by == 'intelligence':
        qs = qs.order_by(f"{prefix}intelligence_index")
    elif sort_by == 'coding':
        qs = qs.order_by(f"{prefix}coding_index")
    elif sort_by == 'name':
        qs = qs.order_by(f"{prefix}display_name")
    else: # score
        if prefix == '-':
            qs = qs.order_by(F('accuracy').desc(nulls_last=True), F('elo').desc(nulls_last=True), F('intelligence_index').desc(nulls_last=True))
        else:
            qs = qs.order_by(F('accuracy').asc(nulls_last=True), F('elo').asc(nulls_last=True), F('intelligence_index').asc(nulls_last=True))

    total = qs.count()
    items = list(qs[offset:offset + limit].values(
        'id', 'model_permaslug', 'display_name', 'source', 'benchmark_type',
        'accuracy', 'elo', 'win_rate', 'category', 'arena', 'intelligence_index',
        'coding_index', 'agentic_index', 'avg_cost_per_task', 'total_tasks',
        'tournament_stats', 'pricing', 'updated_at'
    ))

    return {
        "table": "orbench",
        "total": total,
        "limit": limit,
        "offset": offset,
        "source": source,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "sources_breakdown": sources_breakdown,
        "items": items
    }


@api.get("/aamodels", response=dict, tags=["Dedicated Raw Tables"])
def list_aamodels(
    request,
    search: str = "",
    creator: str = "",
    sort_by: str = "name",
    sort_dir: str = "asc",
    limit: int = Field(100, ge=1, le=1000),
    offset: int = 0
):
    """
    Direct endpoint for 'aamodels' table (Artificial Analysis Models Catalog).
    """
    qs = AAModel.objects.all()

    if search:
        s = search.strip()
        qs = qs.filter(Q(name__icontains=s) | Q(slug__icontains=s) | Q(creator_name__icontains=s))

    if creator:
        qs = qs.filter(creator_name__icontains=creator.strip())

    order_fields = {
        'name': 'name',
        'creator': 'creator_name',
        'context_window': 'context_window',
        'prompt_price': 'prompt_price_per_1m',
        'completion_price': 'completion_price_per_1m',
        'release_date': 'release_date',
    }
    field = order_fields.get(sort_by, 'name')
    prefix = '-' if sort_dir.lower() == 'desc' else ''
    qs = qs.order_by(f"{prefix}{field}")

    total = qs.count()
    items = list(qs[offset:offset + limit].values(
        'id', 'slug', 'name', 'creator_name', 'creator_slug', 'release_date',
        'model_type', 'context_window', 'max_output_tokens', 'prompt_price_per_1m',
        'completion_price_per_1m', 'modalities', 'updated_at'
    ))

    return {
        "table": "aamodels",
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "items": items
    }


@api.get("/aabanch", response=dict, tags=["Dedicated Raw Tables"])
def list_aabanch(
    request,
    search: str = "",
    creator: str = "",
    sort_by: str = "intelligence",
    sort_dir: str = "desc",
    limit: int = Field(100, ge=1, le=1000),
    offset: int = 0
):
    """
    Direct endpoint for 'aabanch' table (Artificial Analysis Benchmark Evaluations).
    """
    qs = AABench.objects.all()

    if search:
        s = search.strip()
        qs = qs.filter(Q(model_name__icontains=s) | Q(model_slug__icontains=s) | Q(creator_name__icontains=s))

    if creator:
        qs = qs.filter(creator_name__icontains=creator.strip())

    order_fields = {
        'intelligence': 'intelligence_index',
        'coding': 'coding_index',
        'math': 'math_index',
        'terminalbench_hard': 'terminalbench_hard',
        'terminalbench_v2_1': 'terminalbench_v2_1',
        'gpqa': 'gpqa',
        'mmlu_pro': 'mmlu_pro',
        'hle': 'hle',
        'livecodebench': 'livecodebench',
        'scicode': 'scicode',
        'math_500': 'math_500',
        'aime': 'aime',
        'aime_25': 'aime_25',
        'ifbench': 'ifbench',
        'lcr': 'lcr',
        'tau2': 'tau2',
        'tau_banking': 'tau_banking',
        'speed': 'tokens_per_second',
        'latency': 'time_to_first_token',
        'name': 'model_name',
    }
    field = order_fields.get(sort_by, 'intelligence_index')
    prefix = '-' if sort_dir.lower() == 'desc' else ''
    qs = qs.order_by(f"{prefix}{field}")

    total = qs.count()
    items = list(qs[offset:offset + limit].values(
        'id', 'model_slug', 'model_name', 'creator_name', 'intelligence_index',
        'coding_index', 'math_index', 'terminalbench_hard', 'terminalbench_v2_1',
        'gpqa', 'mmlu_pro', 'hle', 'livecodebench', 'scicode', 'math_500',
        'aime', 'aime_25', 'ifbench', 'lcr', 'tau2', 'tau_banking',
        'tokens_per_second', 'time_to_first_token', 'updated_at'
    ))

    return {
        "table": "aabanch",
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "items": items
    }


# ================= MERGED MASTER TABLE API: rankindex =================

@api.get("/rankindex", response=dict, tags=["RankIndex Master Table"])
def list_rankindex(
    request,
    search: str = "",
    provider: str = "",
    is_open_weight: Optional[bool] = None,
    is_free: Optional[bool] = None,
    sort_by: str = "rank",
    sort_dir: str = "asc",
    limit: int = Field(100, ge=1, le=1000),
    offset: int = 0
):
    """
    Direct endpoint for 'rankindex' master table.
    Unified matrix merged from ormodels, orbench, aamodels, and aabanch.
    """
    qs = RankIndex.objects.all()

    if search:
        s = search.strip()
        qs = qs.filter(Q(name__icontains=s) | Q(canonical_slug__icontains=s) | Q(provider__icontains=s) | Q(openrouter_id__icontains=s) | Q(aa_slug__icontains=s))

    if provider:
        qs = qs.filter(provider__icontains=provider.strip())

    if is_open_weight is not None:
        qs = qs.filter(is_open_weight=is_open_weight)

    if is_free is not None:
        qs = qs.filter(is_free=is_free)

    order_fields = {
        'rank': 'rank_overall',
        'rankllms_index': 'rankllms_index',
        'intelligence': 'intelligence_index',
        'coding': 'coding_index',
        'math': 'math_index',
        'terminalbench_hard': 'terminalbench_hard',
        'terminalbench_v2_1': 'terminalbench_v2_1',
        'gpqa': 'gpqa_diamond',
        'mmlu_pro': 'mmlu_pro',
        'hle': 'hle',
        'livecodebench': 'livecodebench',
        'aime_25': 'aime_25',
        'design_arena_elo': 'design_arena_elo',
        'ifbench': 'ifbench',
        'tau2': 'tau2',
        'context_length': 'context_length',
        'prompt_price': 'prompt_price_per_1m',
        'completion_price': 'completion_price_per_1m',
        'speed': 'tokens_per_second',
        'latency': 'time_to_first_token',
        'name': 'name',
    }
    field = order_fields.get(sort_by, 'rank_overall')
    prefix = '-' if sort_dir.lower() == 'desc' else ''
    qs = qs.order_by(f"{prefix}{field}")

    total = qs.count()
    items = list(qs[offset:offset + limit].values(
        'id', 'canonical_slug', 'name', 'provider', 'author_slug', 'openrouter_id',
        'aa_slug', 'description', 'release_date', 'is_open_weight', 'is_free',
        'rankllms_index', 'rank_overall', 'rank_coding', 'rank_reasoning', 'rank_value',
        'intelligence_index', 'coding_index', 'math_index', 'terminalbench_hard',
        'terminalbench_v2_1', 'gpqa_diamond', 'mmlu_pro', 'hle', 'livecodebench',
        'scicode', 'math_500', 'aime_25', 'design_arena_elo', 'design_arena_win_rate',
        'ifbench', 'lcr', 'tau2', 'tau_banking', 'context_length', 'max_output_tokens',
        'prompt_price_per_1m', 'completion_price_per_1m', 'tokens_per_second',
        'time_to_first_token', 'has_openrouter', 'has_artificial_analysis',
        'has_design_arena', 'sources', 'updated_at'
    ))

    return {
        "table": "rankindex",
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "items": items
    }


# ================= models.dev SOURCE TABLE =================

@api.get("/modelsdev", response=dict, tags=["Dedicated Raw Tables"])
def list_modelsdev(
    request,
    search: str = "",
    provider: str = "",
    open_weights: Optional[bool] = None,
    reasoning: Optional[bool] = None,
    tool_call: Optional[bool] = None,
    sort_by: str = "name",
    sort_dir: str = "asc",
    limit: int = Field(100, ge=1, le=1000),
    offset: int = 0
):
    """
    Direct endpoint for 'modelsdev' table (models.dev provider/model catalog as-is).
    """
    qs = ModelsDevModel.objects.all()

    if search:
        s = search.strip()
        qs = qs.filter(
            Q(name__icontains=s)
            | Q(modelsdev_id__icontains=s)
            | Q(provider_name__icontains=s)
            | Q(family__icontains=s)
            | Q(description__icontains=s)
        )

    if provider:
        qs = qs.filter(provider_name__icontains=provider.strip())

    if open_weights is not None:
        qs = qs.filter(open_weights=open_weights)

    if reasoning is not None:
        qs = qs.filter(reasoning=reasoning)

    if tool_call is not None:
        qs = qs.filter(tool_call=tool_call)

    order_fields = {
        'name': 'name',
        'provider': 'provider_name',
        'family': 'family',
        'context': 'context_length',
        'prompt_price': 'prompt_price_per_1m',
        'completion_price': 'completion_price_per_1m',
        'release_date': 'release_date',
        'modelsdev_id': 'modelsdev_id',
    }
    field = order_fields.get(sort_by, 'name')
    prefix = '-' if sort_dir.lower() == 'desc' else ''
    qs = qs.order_by(f"{prefix}{field}")

    total = qs.count()
    items = list(qs[offset:offset + limit].values(
        'id', 'modelsdev_id', 'provider_slug', 'provider_name', 'name',
        'description', 'family', 'reasoning', 'tool_call', 'structured_output',
        'temperature', 'open_weights', 'release_date', 'last_updated',
        'modalities', 'context_length', 'max_output_tokens',
        'prompt_price_per_1m', 'completion_price_per_1m', 'cache_read_price_per_1m',
        'status', 'updated_at'
    ))

    return {
        "table": "modelsdev",
        "source": "https://models.dev/api.json",
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "items": items
    }

