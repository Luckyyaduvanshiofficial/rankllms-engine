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
    DailyModelRanking, AppRanking, TaskClassification
)
from .services.openrouter_sync import sync_openrouter_models
from .services.sync_all import run_master_sync

api = NinjaAPI(
    title="RankLLMs Engine API",
    version="1.0.0",
    description="High-performance API engine powering LLM leaderboards, Open-LLM rankings, model comparisons, and weekly top 10 charts.",
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
    intelligence_index: float
    coding_index: float
    agentic_index: float
    swe_bench_score: float
    human_eval_score: float
    mmlu_score: float
    arena_elo: float
    tokens_per_second: float
    time_to_first_token: float


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
    ordering: Optional[str] = "-intelligence_index"
    limit: int = Field(50, ge=1, le=1000)
    offset: int = Field(0, ge=0)



# API Endpoints

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


    total = qs.count()
    models = list(qs[filters.offset:filters.offset + filters.limit])

    items = []
    for m in models:
        spec = getattr(m, 'spec', None)
        pricing = getattr(m, 'pricing', None)
        benchmark = getattr(m, 'benchmark', None)

        items.append({
            "id": m.id,
            "openrouter_id": m.openrouter_id,
            "slug": m.slug,
            "name": m.name,
            "category": m.category,
            "provider_slug": m.provider.slug,
            "provider_name": m.provider.name,
            "is_open_weight": m.is_open_weight,
            "license": m.license,
            "is_free": m.is_free,
            "context_length": spec.context_length if spec else 0,
            "prompt_price_per_1m": pricing.prompt_price_per_1m if pricing else Decimal('0'),
            "completion_price_per_1m": pricing.completion_price_per_1m if pricing else Decimal('0'),
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


@api.get("/leaderboard", response=dict, tags=["Page 1: LLM Leaderboard"])
def get_main_leaderboard(request, sort_by: str = "intelligence", limit: int = 50):
    """
    Main LLM Leaderboard API (Supports sorting by Intelligence, Coding Index, SWE-bench, Agentic Index, Context, Price).
    """
    qs = LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark').filter(is_active=True, category='llm')

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
            "is_open_weight": m.is_open_weight,
            "license": m.license,
            "intelligence_index": benchmark.intelligence_index if benchmark else 0.0,
            "coding_index": benchmark.coding_index if benchmark else 0.0,
            "agentic_index": benchmark.agentic_index if benchmark else 0.0,
            "swe_bench_score": benchmark.swe_bench_score if benchmark else 0.0,
            "context_length": spec.context_length if spec else 0,
            "prompt_price_per_1m": pricing.prompt_price_per_1m if pricing else Decimal('0'),
            "completion_price_per_1m": pricing.completion_price_per_1m if pricing else Decimal('0'),
            "is_free": m.is_free,
        })

    return {
        "sort_by": sort_by,
        "count": len(rankings),
        "rankings": rankings
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
def compare_models(request, ids: str):
    """
    Dynamic Comparison API (Returns side-by-side specs, pricing, and benchmark indices formatted for charts).
    """
    model_ids = [item.strip() for item in ids.split(',') if item.strip()]
    if not model_ids:
        return {"error": "Please provide at least one model ID in 'ids' parameter"}

    models = LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark').filter(
        Q(openrouter_id__in=model_ids) | Q(slug__in=model_ids) | Q(id__in=[int(x) for x in model_ids if x.isdigit()])
    )

    models_list = []
    for m in models:
        spec = getattr(m, 'spec', None)
        pricing = getattr(m, 'pricing', None)
        benchmark = getattr(m, 'benchmark', None)

        models_list.append({
            "id": m.id,
            "openrouter_id": m.openrouter_id,
            "slug": m.slug,
            "name": m.name,
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
                "intelligence_index": benchmark.intelligence_index if benchmark else 0.0,
                "coding_index": benchmark.coding_index if benchmark else 0.0,
                "agentic_index": benchmark.agentic_index if benchmark else 0.0,
                "swe_bench_score": benchmark.swe_bench_score if benchmark else 0.0,
                "arena_elo": benchmark.arena_elo if benchmark else 0.0,
            }
        })

    return {
        "count": len(models_list),
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

