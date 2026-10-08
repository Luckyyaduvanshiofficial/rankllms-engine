from typing import List, Optional, Literal
from decimal import Decimal
from datetime import datetime
from pydantic import Field
from ninja import NinjaAPI, Query, Schema
from ninja.errors import HttpError, ValidationError
from ninja.security import django_auth
from django.shortcuts import get_object_or_404
from django.db.models import Q, Count, F, OuterRef, Subquery
from .models import (
    Provider, LLMModel, ModelSpecification, ModelPricing,
    ModelBenchmark, WeeklyTop10Ranking, PricingHistory,
    DailyModelRanking, AppRanking, TaskClassification, APIKey,
    ORModel, ORBench, AAModel, AABench, RankIndex, ModelsDevModel
)

from .services.deduplication import deduplicate_models, get_clean_model_name
from .services.openrouter_benchmarks_service import fetch_openrouter_unified_benchmarks
from .services.admin_sync import SyncAlreadyRunning, enqueue_sync



api = NinjaAPI(
    title="RankLLMs Engine API",
    version="1.0.0",
    description=(
        "Free high-performance API powering LLM leaderboards, open-weights rankings, "
        "model comparisons, and weekly top 10 charts. "
        "Data sources: OpenRouter, Artificial Analysis, and models.dev. "
        "Product: https://rankllms.com · Maintainer: https://codaipro.com"
    ),
    docs_url="/docs",
)


@api.exception_handler(ValidationError)
def validation_error_handler(request, exc):
    return api.create_response(request, {'error': 'Invalid query parameters.'}, status=400)


def _validate_pagination(limit, offset, *, maximum=500):
    if not isinstance(limit, int) or not 1 <= limit <= maximum:
        raise HttpError(400, f'limit must be between 1 and {maximum}.')
    if not isinstance(offset, int) or offset < 0:
        raise HttpError(400, 'offset must be zero or greater.')


def _validate_sort_dir(sort_dir):
    if str(sort_dir).lower() not in {'asc', 'desc'}:
        raise HttpError(400, 'sort_dir must be asc or desc.')
    return str(sort_dir).lower()


def _resolve_model_exact(identifier):
    """Resolve only explicit IDs/slugs; never return a fuzzy substring match."""
    clean = str(identifier or '').strip()
    if not clean:
        return None
    queryset = LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark')
    if clean.isdigit():
        return queryset.filter(pk=int(clean)).first()
    matches = list(queryset.filter(Q(slug__iexact=clean) | Q(openrouter_id__iexact=clean))[:2])
    return matches[0] if len(matches) == 1 else None


def _numeric_sort_value(value, *, percent=False):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number != number or number in (float('inf'), float('-inf')):
        return None
    return number * 100 if percent and 0 <= number <= 1 else number


def _canonical_scores(models):
    openrouter_ids = [model.openrouter_id for model in models if model.openrouter_id]
    if not openrouter_ids:
        return {}
    return dict(
        RankIndex.objects.filter(openrouter_id__in=openrouter_ids)
        .exclude(openrouter_id='')
        .values_list('openrouter_id', 'rankllms_index')
    )


def _canonical_records(models):
    openrouter_ids = [model.openrouter_id for model in models if model.openrouter_id]
    if not openrouter_ids:
        return {}
    return {
        row.openrouter_id: row
        for row in RankIndex.objects.filter(openrouter_id__in=openrouter_ids).exclude(openrouter_id='')
    }


def _canonical_record_for_model(model):
    if not model or not model.openrouter_id:
        return None
    if not hasattr(model, '_rankllms_canonical_record'):
        model._rankllms_canonical_record = RankIndex.objects.filter(
            openrouter_id=model.openrouter_id
        ).first()
    return model._rankllms_canonical_record


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
    context_length: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    modality: str
    tokenizer: str
    instruct_type: Optional[str] = None
    is_multimodal: Optional[bool] = None
    supports_vision: Optional[bool] = None
    supports_audio: Optional[bool] = None
    supports_tools: Optional[bool] = None
    supports_json_schema: Optional[bool] = None


class ModelPricingSchema(Schema):
    prompt_price_per_1m: Optional[Decimal] = None
    completion_price_per_1m: Optional[Decimal] = None
    image_price: Optional[Decimal] = None
    request_price: Optional[Decimal] = None


class ModelBenchmarkSchema(Schema):
    rankllms_index: Optional[float] = None
    intelligence_index: Optional[float] = None
    coding_index: Optional[float] = None
    agentic_index: Optional[float] = None
    swe_bench_score: Optional[float] = None
    human_eval_score: Optional[float] = None
    mmlu_score: Optional[float] = None
    arena_elo: Optional[float] = None
    tokens_per_second: Optional[float] = None
    time_to_first_token: Optional[float] = None

    @staticmethod
    def resolve_rankllms_index(obj):
        model = getattr(obj, 'model', None)
        canonical = _canonical_record_for_model(model)
        return canonical.rankllms_index if canonical else None



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
    is_open_weight: Optional[bool] = None
    license: str
    is_free: Optional[bool] = None
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

    @staticmethod
    def resolve_is_open_weight(obj):
        canonical = _canonical_record_for_model(obj)
        return canonical.is_open_weight if canonical else None

    @staticmethod
    def resolve_is_free(obj):
        canonical = _canonical_record_for_model(obj)
        return canonical.is_free if canonical else None

    @staticmethod
    def resolve_license(obj):
        canonical = _canonical_record_for_model(obj)
        return canonical.license if canonical else ''


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
    run_id: Optional[int] = None


class ModelFilterSchema(Schema):
    search: Optional[str] = None
    provider: Optional[str] = None
    category: Optional[str] = None
    is_open_weight: Optional[bool] = None
    is_free: Optional[bool] = None
    supports_vision: Optional[bool] = None
    supports_tools: Optional[bool] = None
    min_context: Optional[int] = Field(None, ge=0)
    max_prompt_price_1m: Optional[float] = Field(None, ge=0)
    ordering: Optional[str] = "-rankllms_index"
    dedup: bool = True
    limit: int = Field(50, ge=1, le=1000)

    offset: int = Field(0, ge=0)




class APIKeyCreateSchema(Schema):
    name: str = Field(..., min_length=1, max_length=255, example="RankLLMs Frontend")
    tier: Literal['free', 'pro', 'admin'] = Field("free", example="free")


class APIKeyCreatedSchema(Schema):
    id: int
    key: str
    name: str
    tier: str
    is_active: bool
    total_requests: int
    created_at: datetime


class APIKeyListSchema(Schema):
    id: int
    key_preview: str
    name: str
    tier: str
    is_active: bool
    total_requests: int
    created_at: datetime


def _require_staff(request):
    user = getattr(request, 'auth', None) or getattr(request, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False):
        raise HttpError(401, 'Authentication required.')
    if not user.is_staff:
        raise HttpError(403, 'Staff access required.')
    return user



# API Endpoints

@api.post("/keys/generate", response=APIKeyCreatedSchema, auth=django_auth, tags=["API Key Manager"])
def generate_api_key(request, payload: APIKeyCreateSchema):
    """
    Generate a new Developer API Key (rk_live_...).
    """
    _require_staff(request)
    api_key_obj = APIKey.generate_key(name=payload.name.strip(), tier=payload.tier)
    return api_key_obj


@api.get("/keys", response=List[APIKeyListSchema], auth=django_auth, tags=["API Key Manager"])
def list_api_keys(request):
    """
    List all active API keys and their usage statistics.
    """
    _require_staff(request)
    return [
        {
            'id': key.pk,
            'key_preview': f'{key.key[:12]}…',
            'name': key.name,
            'tier': key.tier,
            'is_active': key.is_active,
            'total_requests': key.total_requests,
            'created_at': key.created_at,
        }
        for key in APIKey.objects.filter(is_active=True).order_by('-created_at')
    ]


@api.get("/health", tags=["System"])

def health_check(request):
    """
    System health status and Neon DB connection check.
    """
    from django.db import connection, DatabaseError

    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        latest = RankIndex.objects.order_by('-updated_at').values_list('updated_at', flat=True).first()
        return {
            'status': 'healthy',
            'database': 'connected',
            'total_models': RankIndex.objects.count(),
            'total_providers': Provider.objects.count(),
            'data_snapshot_time': latest.isoformat() if latest else None,
            'version': __import__('os').getenv('RENDER_GIT_COMMIT', '')[:12] or None,
            'timestamp': datetime.now(),
        }
    except DatabaseError:
        return api.create_response(request, {
            'status': 'unavailable',
            'database': 'unavailable',
            'timestamp': datetime.now(),
        }, status=503)


@api.get("/providers", response=List[ProviderSchema], tags=["Providers"])
def list_providers(request):
    """
    List AI providers with active model counts.
    """
    return Provider.objects.annotate(
        model_count=Count('models', filter=Q(models__is_active=True))
    ).filter(is_active=True)


@api.get("/models", response=dict, tags=["Models Catalog"])
def list_models(request, filters: ModelFilterSchema = Query(...)):
    """
    Query, search, and filter AI models with specs, pricing, and benchmark indices.
    """
    _validate_pagination(filters.limit, filters.offset, maximum=1000)
    if filters.category and filters.category not in {choice[0] for choice in LLMModel.MODEL_CATEGORY_CHOICES}:
        raise HttpError(400, 'category is not supported.')
    canonical_score_query = RankIndex.objects.filter(
        openrouter_id=OuterRef('openrouter_id')
    ).values('rankllms_index')[:1]
    canonical_context_query = RankIndex.objects.filter(
        openrouter_id=OuterRef('openrouter_id')
    ).values('context_length')[:1]
    canonical_price_query = RankIndex.objects.filter(
        openrouter_id=OuterRef('openrouter_id')
    ).values('prompt_price_per_1m')[:1]
    qs = LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark').annotate(
        canonical_rankllms_index=Subquery(canonical_score_query),
        canonical_context_length=Subquery(canonical_context_query),
        canonical_prompt_price=Subquery(canonical_price_query),
    ).filter(is_active=True)

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
        matching_ids = RankIndex.objects.filter(
            is_open_weight=filters.is_open_weight
        ).exclude(openrouter_id='').values('openrouter_id')
        qs = qs.filter(openrouter_id__in=matching_ids)

    if filters.is_free is not None:
        matching_ids = RankIndex.objects.filter(
            is_free=filters.is_free
        ).exclude(openrouter_id='').values('openrouter_id')
        qs = qs.filter(openrouter_id__in=matching_ids)

    if filters.supports_vision is not None:
        qs = qs.filter(spec__supports_vision=filters.supports_vision)

    if filters.supports_tools is not None:
        qs = qs.filter(spec__supports_tools=filters.supports_tools)

    if filters.min_context is not None:
        matching_ids = RankIndex.objects.filter(
            context_length__gte=filters.min_context
        ).exclude(openrouter_id='').values('openrouter_id')
        qs = qs.filter(openrouter_id__in=matching_ids)

    if filters.max_prompt_price_1m is not None:
        matching_ids = RankIndex.objects.filter(
            prompt_price_per_1m__lte=filters.max_prompt_price_1m
        ).exclude(openrouter_id='').values('openrouter_id')
        qs = qs.filter(openrouter_id__in=matching_ids)

    # Ordering mapping defaulting to most intelligent models at top
    order_map = {
        'rankllms_index': F('canonical_rankllms_index').desc(nulls_last=True),
        '-rankllms_index': F('canonical_rankllms_index').desc(nulls_last=True),
        'intelligence_index': F('benchmark__intelligence_index').desc(nulls_last=True),
        '-intelligence_index': F('benchmark__intelligence_index').desc(nulls_last=True),
        'coding_index': F('benchmark__coding_index').desc(nulls_last=True),
        '-coding_index': F('benchmark__coding_index').desc(nulls_last=True),
        'agentic_index': F('benchmark__agentic_index').desc(nulls_last=True),
        '-agentic_index': F('benchmark__agentic_index').desc(nulls_last=True),
        'swe_bench': F('benchmark__swe_bench_score').desc(nulls_last=True),
        '-swe_bench': F('benchmark__swe_bench_score').desc(nulls_last=True),
        'prompt_price': F('canonical_prompt_price').asc(nulls_last=True),
        '-prompt_price': F('canonical_prompt_price').desc(nulls_last=True),
        'context_length': F('canonical_context_length').desc(nulls_last=True),
        '-context_length': F('canonical_context_length').desc(nulls_last=True),
        'name': 'name',
        '-name': '-name',
    }

    if filters.ordering not in order_map:
        raise HttpError(400, 'ordering is not supported.')
    sort_field = order_map[filters.ordering]
    qs = qs.order_by(sort_field, F('benchmark__coding_index').desc(nulls_last=True))

    total = qs.count()
    models = list(qs[filters.offset:filters.offset + filters.limit])
    canonical_scores = _canonical_scores(models)
    canonical_records = _canonical_records(models)


    items = []
    for m in models:
        spec = getattr(m, 'spec', None)
        pricing = getattr(m, 'pricing', None)
        benchmark = getattr(m, 'benchmark', None)
        canonical = canonical_records.get(m.openrouter_id)

        items.append({
            "id": m.id,
            "openrouter_id": m.openrouter_id,
            "slug": m.slug,
            "name": get_clean_model_name(m.name, m.provider.name) if filters.dedup else m.name,
            "category": m.category,
            "provider_slug": m.provider.slug,
            "provider_name": m.provider.name,
            "is_open_weight": canonical.is_open_weight if canonical else None,
            "license": canonical.license if canonical and canonical.license else None,
            "is_free": canonical.is_free if canonical else None,
            "context_length": canonical.context_length if canonical else (spec.context_length if spec else None),
            "prompt_price_per_1m": canonical.prompt_price_per_1m if canonical else (pricing.prompt_price_per_1m if pricing else None),
            "completion_price_per_1m": canonical.completion_price_per_1m if canonical else (pricing.completion_price_per_1m if pricing else None),
            "rankllms_index": canonical_scores.get(m.openrouter_id),
            "intelligence_index": benchmark.intelligence_index if benchmark else None,
            "coding_index": benchmark.coding_index if benchmark else None,
            "agentic_index": benchmark.agentic_index if benchmark else None,
            "swe_bench_score": benchmark.swe_bench_score if benchmark else None,
            "arena_elo": benchmark.arena_elo if benchmark else None,
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
    _validate_pagination(limit, 0, maximum=500)
    canonical_score_query = RankIndex.objects.filter(
        openrouter_id=OuterRef('openrouter_id')
    ).values('rankllms_index')[:1]
    qs = LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark').annotate(
        canonical_rankllms_index=Subquery(canonical_score_query),
    ).filter(is_active=True, category='llm')
    qs = qs.order_by(F('canonical_rankllms_index').desc(nulls_last=True), F('benchmark__coding_index').desc(nulls_last=True))

    models = list(qs[:limit])
    canonical_scores = _canonical_scores(models)
    canonical_records = _canonical_records(models)
    cards = []

    for m in models:
        spec = getattr(m, 'spec', None)
        pricing = getattr(m, 'pricing', None)
        bm = getattr(m, 'benchmark', None)
        canonical = canonical_records.get(m.openrouter_id)

        desc = m.description or ''

        strengths = []
        if canonical and canonical.coding_index is not None and canonical.coding_index >= 70:
            strengths.append("Coding Index ≥70 (source benchmark)")
        if canonical and canonical.reasoning is True:
            strengths.append("Reasoning capability reported by source")
        context = canonical.context_length if canonical else (spec.context_length if spec else None)
        if context is not None and context >= 128000:
            strengths.append(f"{context // 1000}K context reported by source")
        if canonical and canonical.is_free is True:
            strengths.append("Free price listing reported by source")
        if canonical and canonical.is_open_weight is True:
            strengths.append("Open weights reported by source")
        if spec and spec.supports_vision is True:
            strengths.append("Multimodal Vision")
        cards.append({
            "id": m.slug or m.openrouter_id.replace('/', '-'),
            "openrouter_id": m.openrouter_id,
            "name": get_clean_model_name(canonical.name if canonical else m.name, canonical.provider if canonical else m.provider.name),
            "provider": canonical.provider if canonical else m.provider.name,
            "category": m.category,
            "isOpenWeight": canonical.is_open_weight if canonical else None,
            "isFree": canonical.is_free if canonical else None,
            "contextWindow": context,
            "inputPricePerM": float(canonical.prompt_price_per_1m) if canonical and canonical.prompt_price_per_1m is not None else None,
            "outputPricePerM": float(canonical.completion_price_per_1m) if canonical and canonical.completion_price_per_1m is not None else None,
            "rankllmsIndex": canonical_scores.get(m.openrouter_id),
            "intelligenceIndex": bm.intelligence_index if bm else None,
            "codingIndex": bm.coding_index if bm else None,
            "agenticIndex": bm.agentic_index if bm else None,
            "sweBenchScore": bm.swe_bench_score if bm else None,
            "humanEvalScore": bm.human_eval_score if bm else None,
            "mmluScore": bm.mmlu_score if bm else None,
            "arenaElo": bm.arena_elo if bm else None,
            "speedTps": bm.tokens_per_second if bm else None,
            "timeToFirstToken": bm.time_to_first_token if bm else None,
            "releaseDate": canonical.release_date.isoformat() if canonical and canonical.release_date else None,
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
    limit: int = 200
):
    """
    Main LLM Leaderboard API.
    Ranks models by Intelligence Index (primary) then Coding Index (secondary) by default.
    Supports sorting by Coding Index, SWE-bench, Agentic Index, Context, or Price.
    With exclude_nulls=true (default), only models with verified Intelligence AND Coding scores are ranked.
    """
    _validate_pagination(limit, 0, maximum=500)
    if sort_by not in {'rankllms_index', 'intelligence', 'coding', 'swe_bench', 'agentic', 'context', 'cost'}:
        raise HttpError(400, 'sort_by is not supported.')
    canonical_score_query = RankIndex.objects.filter(
        openrouter_id=OuterRef('openrouter_id')
    ).values('rankllms_index')[:1]
    canonical_price_query = RankIndex.objects.filter(
        openrouter_id=OuterRef('openrouter_id')
    ).values('prompt_price_per_1m')[:1]
    canonical_free_query = RankIndex.objects.filter(
        openrouter_id=OuterRef('openrouter_id')
    ).values('is_free')[:1]
    qs = LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark').annotate(
        canonical_rankllms_index=Subquery(canonical_score_query),
        canonical_prompt_price=Subquery(canonical_price_query),
        canonical_is_free=Subquery(canonical_free_query),
    ).filter(is_active=True, category='llm')

    if exclude_nulls:
        if sort_by == 'rankllms_index':
            qs = qs.filter(canonical_rankllms_index__isnull=False)
        else:
            qs = qs.filter(
                benchmark__intelligence_index__isnull=False,
                benchmark__coding_index__isnull=False,
            )

    if sort_by == 'rankllms_index':
        qs = qs.order_by(F('canonical_rankllms_index').desc(nulls_last=True), F('benchmark__coding_index').desc(nulls_last=True))
    elif sort_by == 'intelligence':
        qs = qs.order_by(F('benchmark__intelligence_index').desc(nulls_last=True), F('benchmark__coding_index').desc(nulls_last=True))
    elif sort_by == "coding":
        qs = qs.order_by(F('benchmark__coding_index').desc(nulls_last=True), F('benchmark__intelligence_index').desc(nulls_last=True))
    elif sort_by == "swe_bench":
        qs = qs.order_by(F('benchmark__swe_bench_score').desc(nulls_last=True), F('benchmark__coding_index').desc(nulls_last=True))
    elif sort_by == "agentic":
        qs = qs.order_by(F('benchmark__agentic_index').desc(nulls_last=True), F('benchmark__intelligence_index').desc(nulls_last=True))
    elif sort_by == "context":
        qs = qs.order_by(F('spec__context_length').desc(nulls_last=True), F('benchmark__intelligence_index').desc(nulls_last=True))
    elif sort_by == "cost":
        qs = qs.filter(canonical_is_free=False, canonical_prompt_price__gt=0).order_by(F('canonical_prompt_price').asc(nulls_last=True))
    else:
        qs = qs.order_by(F('canonical_rankllms_index').desc(nulls_last=True), F('benchmark__coding_index').desc(nulls_last=True))


    models = list(qs[:limit])
    canonical_scores = _canonical_scores(models)
    canonical_records = _canonical_records(models)

    rankings = []
    for idx, m in enumerate(models, start=1):
        spec = getattr(m, 'spec', None)
        pricing = getattr(m, 'pricing', None)
        benchmark = getattr(m, 'benchmark', None)
        canonical = canonical_records.get(m.openrouter_id)

        rankings.append({
            "rank": idx,
            "id": m.id,
            "openrouter_id": m.openrouter_id,
            "slug": m.slug,
            "name": get_clean_model_name(m.name, m.provider.name) if dedup else m.name,
            "provider": m.provider.name,
            "is_open_weight": canonical.is_open_weight if canonical else None,
            "license": canonical.license if canonical and canonical.license else None,
            "rankllms_index": canonical_scores.get(m.openrouter_id),
            "intelligence_index": benchmark.intelligence_index if benchmark else None,
            "coding_index": benchmark.coding_index if benchmark else None,

            "agentic_index": benchmark.agentic_index if benchmark else None,
            "swe_bench_score": benchmark.swe_bench_score if benchmark else None,
            "context_length": canonical.context_length if canonical else (spec.context_length if spec else None),
            "prompt_price_per_1m": canonical.prompt_price_per_1m if canonical else (pricing.prompt_price_per_1m if pricing else None),
            "completion_price_per_1m": canonical.completion_price_per_1m if canonical else (pricing.completion_price_per_1m if pricing else None),
            "is_free": canonical.is_free if canonical else None,
            "is_multimodal": spec.is_multimodal if spec else None,
            "supports_vision": spec.supports_vision if spec else None,
        })

    return {
        "sort_by": sort_by,
        "dedup": dedup,
        "exclude_nulls": exclude_nulls,
        "count": len(rankings),
        "rankings": rankings
    }


@api.get("/benchmarks", response=dict, tags=["Benchmarks API"])
def get_benchmarks_catalog(request, sort_by: str = "rankllms_index", dedup: bool = True, limit: int = 50, offset: int = 0):
    """
    Dedicated Benchmarks API endpoint.
    Returns model benchmark evaluation matrix sorted by rankllms_index (default), coding_index, agentic_index, swe_bench, arena_elo, or speed.
    """
    _validate_pagination(limit, offset, maximum=1000)
    canonical_score_query = RankIndex.objects.filter(
        openrouter_id=OuterRef('openrouter_id')
    ).values('rankllms_index')[:1]
    qs = LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark').annotate(
        canonical_rankllms_index=Subquery(canonical_score_query)
    ).filter(is_active=True, category='llm')

    order_map = {
        'rankllms_index': F('canonical_rankllms_index').desc(nulls_last=True),
        '-rankllms_index': F('canonical_rankllms_index').desc(nulls_last=True),
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

    if sort_by not in order_map:
        raise HttpError(400, 'sort_by is not supported.')
    sort_field = order_map[sort_by]
    qs = qs.order_by(sort_field, F('benchmark__coding_index').desc(nulls_last=True))

    total = qs.count()
    models = list(qs[offset:offset + limit])
    canonical_scores = _canonical_scores(models)

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
            "context_length": spec.context_length if spec else None,
            "pricing": {
                "prompt_price_per_1m": float(pricing.prompt_price_per_1m) if pricing and pricing.prompt_price_per_1m is not None else None,
                "completion_price_per_1m": float(pricing.completion_price_per_1m) if pricing and pricing.completion_price_per_1m is not None else None,
                "is_free": m.is_free,
            },
            "benchmarks": {
                "rankllms_index": canonical_scores.get(m.openrouter_id),
                "intelligence_index": benchmark.intelligence_index if benchmark else None,
                "coding_index": benchmark.coding_index if benchmark else None,
                "agentic_index": benchmark.agentic_index if benchmark else None,
                "swe_bench_score": benchmark.swe_bench_score if benchmark else None,
                "mmlu_score": benchmark.mmlu_score if benchmark else None,
                "human_eval_score": benchmark.human_eval_score if benchmark else None,
                "arena_elo": benchmark.arena_elo if benchmark else None,
                "tokens_per_second": benchmark.tokens_per_second if benchmark else None,
                "time_to_first_token": benchmark.time_to_first_token if benchmark else None,
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
    limit: int = 100,
    offset: int = 0
):
    """
    OpenRouter Unified Benchmarks Endpoint.
    Aggregates empirical evaluations from:
    1. 'openrouter' (GPQA Diamond, Tau-bench, search evals, Math)
    2. 'design-arena' (Design Arena ELO & Win Rates across webapps, mobile, graphicdesign, fullstack, etc.)
    3. 'artificial-analysis' (Intelligence, Coding, and Agentic indices)
    """
    _validate_pagination(limit, offset, maximum=1000)
    if source not in {'all', 'openrouter', 'design-arena', 'artificial-analysis'}:
        raise HttpError(400, 'source is not supported.')
    if sort_dir.lower() not in {'asc', 'desc'}:
        raise HttpError(400, 'sort_dir must be asc or desc.')
    if sort_by not in {'score', 'name', 'accuracy', 'elo', 'win_rate', 'intelligence', 'coding', 'price'}:
        raise HttpError(400, 'sort_by is not supported.')
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
            return _numeric_sort_value(x.get("accuracy"), percent=True)
        elif sort_by == "elo":
            return _numeric_sort_value(x.get("elo"))
        elif sort_by == "win_rate":
            return _numeric_sort_value(x.get("win_rate"), percent=True)
        elif sort_by == "intelligence":
            return _numeric_sort_value(x.get("intelligence_index"))
        elif sort_by == "coding":
            return _numeric_sort_value(x.get("coding_index"))
        elif sort_by == "price":
            pricing = x.get("pricing") or {}
            return _numeric_sort_value(pricing.get("prompt"))
        else: # "score" / default
            # This is a source-specific primary metric, not a normalized score.
            if x.get('primary_score') is not None:
                return _numeric_sort_value(x.get('primary_score'))
            if x.get("accuracy") is not None:
                return _numeric_sort_value(x.get("accuracy"), percent=True)
            elif x.get("elo") is not None:
                return _numeric_sort_value(x.get("elo"))
            elif x.get("intelligence_index") is not None:
                return _numeric_sort_value(x.get("intelligence_index"))
            return None

    reverse = (sort_dir.lower() == "desc")
    present = [row for row in filtered if get_sort_key(row) is not None]
    missing = [row for row in filtered if get_sort_key(row) is None]
    present.sort(key=get_sort_key, reverse=reverse)
    filtered = present + missing

    total = len(filtered)
    paginated = filtered[offset:offset + limit]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "source": source,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "sort_note": "Source-specific primary metrics use different units; filter to one source before comparing scores." if source == 'all' and sort_by == 'score' else None,
        "sources_breakdown": sources_breakdown,
        "items": paginated
    }


@api.get("/leaderboard/open-weights", response=dict, tags=["Page 2: Open-LLM Leaderboard"])

def get_open_llm_leaderboard(request, sort_by: str = "intelligence", limit: int = 50):
    """
    Open LLM Leaderboard API (Ranks ONLY Open-Source / Open-Weight models like DeepSeek, Llama, Qwen, Mistral).
    """
    _validate_pagination(limit, 0, maximum=500)
    if sort_by not in {'intelligence', 'coding', 'swe_bench'}:
        raise HttpError(400, 'sort_by is not supported.')
    canonical_score_query = RankIndex.objects.filter(
        openrouter_id=OuterRef('openrouter_id')
    ).values('rankllms_index')[:1]
    qs = LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark').annotate(
        canonical_rankllms_index=Subquery(canonical_score_query)
    ).filter(
        is_active=True, category='llm', is_open_weight=True
    )

    if sort_by == "coding":
        qs = qs.order_by(F('benchmark__coding_index').desc(nulls_last=True), F('benchmark__intelligence_index').desc(nulls_last=True))
    elif sort_by == "swe_bench":
        qs = qs.order_by(F('benchmark__swe_bench_score').desc(nulls_last=True), F('benchmark__coding_index').desc(nulls_last=True))
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
            "license": m.license,
            "rankllms_index": m.canonical_rankllms_index,
            "intelligence_index": benchmark.intelligence_index if benchmark else None,
            "coding_index": benchmark.coding_index if benchmark else None,
            "agentic_index": benchmark.agentic_index if benchmark else None,
            "context_length": spec.context_length if spec else None,
            "prompt_price_per_1m": pricing.prompt_price_per_1m if pricing else None,
            "completion_price_per_1m": pricing.completion_price_per_1m if pricing else None,
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

    if len(unique_ids) < 2:
        raise HttpError(400, 'Provide at least two distinct model IDs.')
    if len(unique_ids) > 5:
        raise HttpError(400, 'Compare supports at most five models per request.')

    models = []
    for model_id in unique_ids:
        model = _resolve_model_exact(model_id)
        if model is None:
            raise HttpError(404, f'Unknown model identifier: {model_id}')
        models.append(model)

    canonical_scores = _canonical_scores(models)
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
                "context_length": spec.context_length if spec else None,
                "max_completion_tokens": spec.max_completion_tokens if spec else None,
                "modality": spec.modality if spec else "",
                "is_multimodal": spec.is_multimodal if spec else None,
                "supports_vision": spec.supports_vision if spec else None,
                "supports_tools": spec.supports_tools if spec else None,
            },
            "pricing": {
                "prompt_price_per_1m": pricing.prompt_price_per_1m if pricing else None,
                "completion_price_per_1m": pricing.completion_price_per_1m if pricing else None,
                "is_free": m.is_free,
            },
            "benchmarks": {
                "rankllms_index": canonical_scores.get(m.openrouter_id),
                "intelligence_index": benchmark.intelligence_index if benchmark else None,
                "coding_index": benchmark.coding_index if benchmark else None,
                "agentic_index": benchmark.agentic_index if benchmark else None,
                "swe_bench_score": benchmark.swe_bench_score if benchmark else None,
                "arena_elo": benchmark.arena_elo if benchmark else None,
            }
        })

    # Determine winners if 2 models
    winner = {}
    if len(models_list) >= 2:
        m1, m2 = models_list[0], models_list[1]
        m1_intel = m1['benchmarks']['intelligence_index']
        m2_intel = m2['benchmarks']['intelligence_index']
        if m1_intel is not None and m2_intel is not None:
            winner['overall'] = m1['name'] if m1_intel >= m2_intel else m2['name']

        m1_code = m1['benchmarks']['coding_index']
        m2_code = m2['benchmarks']['coding_index']
        if m1_code is not None and m2_code is not None:
            winner['coding'] = m1['name'] if m1_code >= m2_code else m2['name']

        m1_price = m1['pricing']['prompt_price_per_1m']
        m2_price = m2['pricing']['prompt_price_per_1m']
        if m1_price is not None and m2_price is not None:
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
    valid_categories = {choice[0] for choice in WeeklyTop10Ranking.CATEGORY_CHOICES}
    if category not in valid_categories:
        raise HttpError(400, 'category is not supported.')
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
                "intelligence_index": benchmark.intelligence_index if benchmark else None,
                "coding_index": benchmark.coding_index if benchmark else None,
                "prompt_price_per_1m": pricing.prompt_price_per_1m if pricing else None,
                "completion_price_per_1m": pricing.completion_price_per_1m if pricing else None,
            })
    else:
        # Auto-calculate Top 10 from benchmark scores if curated list not set yet
        qs = LLMModel.objects.select_related('provider', 'spec', 'pricing', 'benchmark').filter(is_active=True, category='llm')

        if category == "coding":
            qs = qs.filter(benchmark__coding_index__isnull=False).order_by(F('benchmark__coding_index').desc(nulls_last=True), F('benchmark__intelligence_index').desc(nulls_last=True))
        elif category == "open_source":
            qs = qs.filter(is_open_weight=True, benchmark__intelligence_index__isnull=False).order_by(F('benchmark__intelligence_index').desc(nulls_last=True))
        elif category == "cost_effective":
            qs = qs.filter(is_free=False, pricing__prompt_price_per_1m__gt=0).order_by(F('pricing__prompt_price_per_1m').asc(nulls_last=True))
        else:
            qs = qs.filter(benchmark__intelligence_index__isnull=False).order_by(F('benchmark__intelligence_index').desc(nulls_last=True))

        for idx, m in enumerate(qs[:10], start=1):
            spec = getattr(m, 'spec', None)
            pricing = getattr(m, 'pricing', None)
            benchmark = getattr(m, 'benchmark', None)

            top_10.append({
                "rank": idx,
                "openrouter_id": m.openrouter_id,
                "name": m.name,
                "provider": m.provider.name,
                "highlight_reason": f"Ranked by available source data for {category}",
                "intelligence_index": benchmark.intelligence_index if benchmark else None,
                "coding_index": benchmark.coding_index if benchmark else None,
                "prompt_price_per_1m": pricing.prompt_price_per_1m if pricing else None,
                "completion_price_per_1m": pricing.completion_price_per_1m if pricing else None,
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
    model = _resolve_model_exact(identifier)
    if model is None:
        raise HttpError(404, 'Model not found.')
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


@api.post("/sync", response=SyncResponseSchema, auth=django_auth, tags=["Admin & Data Sync"])
def trigger_master_sync(request):
    """
    Manually trigger full master data sync (OpenRouter + Artificial Analysis + Null Backfill).
    """
    user = _require_staff(request)
    try:
        run = enqueue_sync(source='all', user=user)
    except SyncAlreadyRunning as exc:
        raise HttpError(409, str(exc)) from exc
    return api.create_response(request, {
        'status': 'accepted',
        'run_id': run.pk,
        'summary': {'message': 'Sync queued. Poll the staff Settings page for the result.'},
    }, status=202)


# ================= DEDICATED SOURCE ENDPOINTS (ormodels, orbench, aamodels, aabanch) =================

@api.get("/ormodels", response=dict, tags=["Dedicated Raw Tables"])
def list_ormodels(
    request,
    search: str = "",
    author: str = "",
    is_free: Optional[bool] = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: int = 100,
    offset: int = 0,
    include_stale: bool = False,
):
    """
    Direct endpoint for 'ormodels' table (OpenRouter Models Catalog).
    """
    _validate_pagination(limit, offset, maximum=1000)
    sort_dir = _validate_sort_dir(sort_dir)
    qs = ORModel.objects.all() if include_stale else ORModel.objects.filter(is_active=True)

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
        'created_at': 'created_at',
    }
    if sort_by not in order_fields:
        raise HttpError(400, 'sort_by is not supported.')
    field = order_fields[sort_by]
    prefix = '-' if sort_dir == 'desc' else ''
    if field in {'context_length', 'prompt_price_per_1m', 'completion_price_per_1m'}:
        qs = qs.order_by(F(field).desc(nulls_last=True) if prefix else F(field).asc(nulls_last=True))
    else:
        qs = qs.order_by(f"{prefix}{field}")

    total = qs.count()
    items = list(qs[offset:offset + limit].values(
        'id', 'openrouter_id', 'name', 'canonical_slug', 'author', 'description',
        'context_length', 'prompt_price_per_1m', 'completion_price_per_1m',
        'is_free', 'is_active', 'last_verified_at', 'architecture', 'top_provider', 'pricing', 'created_at', 'updated_at'
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
    limit: int = 100,
    offset: int = 0,
    include_stale: bool = False,
):
    """
    Direct endpoint for 'orbench' table (OpenRouter Unified Benchmarks).
    """
    _validate_pagination(limit, offset, maximum=1000)
    sort_dir = _validate_sort_dir(sort_dir)
    if sort_by not in {'accuracy', 'elo', 'win_rate', 'intelligence', 'coding', 'name', 'score'}:
        raise HttpError(400, 'sort_by is not supported.')
    qs = ORBench.objects.all() if include_stale else ORBench.objects.filter(is_active=True)

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
    prefix = '-' if sort_dir == 'desc' else ''
    if sort_by in {'accuracy', 'elo', 'win_rate', 'intelligence', 'coding'}:
        field = {'intelligence': 'intelligence_index', 'coding': 'coding_index'}.get(sort_by, sort_by)
        qs = qs.order_by(F(field).desc(nulls_last=True) if prefix else F(field).asc(nulls_last=True))
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
        'accuracy', 'primary_score', 'primary_metric', 'source_url', 'last_run_timestamp',
        'elo', 'win_rate', 'category', 'arena', 'intelligence_index',
        'coding_index', 'agentic_index', 'avg_cost_per_task', 'total_tasks',
        'tournament_stats', 'pricing', 'is_active', 'last_verified_at', 'updated_at'
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
    sort_by: str = "release_date",
    sort_dir: str = "desc",
    limit: int = 100,
    offset: int = 0,
    include_stale: bool = False,
):
    """
    Direct endpoint for 'aamodels' table (Artificial Analysis Models Catalog).
    """
    _validate_pagination(limit, offset, maximum=1000)
    sort_dir = _validate_sort_dir(sort_dir)
    qs = AAModel.objects.all() if include_stale else AAModel.objects.filter(is_active=True)

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
    if sort_by not in order_fields:
        raise HttpError(400, 'sort_by is not supported.')
    field = order_fields[sort_by]
    prefix = '-' if sort_dir == 'desc' else ''
    if field in {'release_date', 'context_window', 'prompt_price_per_1m', 'completion_price_per_1m'}:
        expr = F(field).desc(nulls_last=True) if prefix else F(field).asc(nulls_last=True)
        qs = qs.order_by(expr)
    else:
        qs = qs.order_by(f"{prefix}{field}")

    total = qs.count()
    items = list(qs[offset:offset + limit].values(
        'id', 'slug', 'source_id', 'source_slug', 'source_endpoint', 'last_verified_at',
        'name', 'creator_name', 'creator_slug', 'release_date',
        'model_type', 'is_active', 'context_window', 'max_output_tokens', 'prompt_price_per_1m',
        'completion_price_per_1m', 'cache_hit_price_per_1m', 'cache_write_price_per_1m',
        'modalities', 'updated_at'
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
    limit: int = 100,
    offset: int = 0,
    include_stale: bool = False,
):
    """
    Direct endpoint for 'aabanch' table (Artificial Analysis Benchmark Evaluations).
    """
    _validate_pagination(limit, offset, maximum=1000)
    sort_dir = _validate_sort_dir(sort_dir)
    qs = AABench.objects.all() if include_stale else AABench.objects.filter(is_active=True)

    if search:
        s = search.strip()
        qs = qs.filter(Q(model_name__icontains=s) | Q(model_slug__icontains=s) | Q(creator_name__icontains=s))

    if creator:
        qs = qs.filter(creator_name__icontains=creator.strip())

    order_fields = {
        'intelligence': 'intelligence_index',
        'coding': 'coding_index',
        'agentic': 'agentic_index',
        'finance_and_accounting': 'finance_and_accounting_index',
        'strategy_and_ops': 'strategy_and_ops_index',
        'legal': 'legal_index',
        'healthcare_and_medical': 'healthcare_and_medical_index',
        'engineering': 'engineering_index',
        'economics': 'economics_index',
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
        'latency_answer': 'time_to_first_answer_token',
        'latency_end_to_end': 'end_to_end_response_time',
        'media_elo': 'elo',
        'media_price': 'price_per_unit',
        'media_samples': 'samples',
        'name': 'model_name',
    }
    if sort_by not in order_fields:
        raise HttpError(400, 'sort_by is not supported.')
    field = order_fields[sort_by]
    prefix = '-' if sort_dir == 'desc' else ''
    nullable_fields = {
        'intelligence_index', 'coding_index', 'agentic_index',
        'finance_and_accounting_index', 'strategy_and_ops_index', 'legal_index',
        'healthcare_and_medical_index', 'engineering_index', 'economics_index',
        'math_index', 'terminalbench_hard',
        'terminalbench_v2_1', 'gpqa', 'mmlu_pro', 'hle', 'livecodebench', 'scicode',
        'math_500', 'aime', 'aime_25', 'ifbench', 'lcr', 'tau2', 'tau_banking',
        'tokens_per_second', 'time_to_first_token', 'time_to_first_answer_token',
        'end_to_end_response_time', 'elo', 'price_per_unit', 'samples',
    }
    if field in nullable_fields:
        qs = qs.order_by(F(field).desc(nulls_last=True) if prefix else F(field).asc(nulls_last=True))
    else:
        qs = qs.order_by(f"{prefix}{field}")

    total = qs.count()
    items = list(qs[offset:offset + limit].values(
        'id', 'model_slug', 'source_id', 'source_slug', 'source_endpoint', 'last_verified_at',
        'model_name', 'creator_name', 'is_active', 'intelligence_index',
        'coding_index', 'agentic_index', 'finance_and_accounting_index',
        'strategy_and_ops_index', 'legal_index', 'healthcare_and_medical_index',
        'engineering_index', 'economics_index', 'math_index', 'terminalbench_hard', 'terminalbench_v2_1',
        'gpqa', 'mmlu_pro', 'hle', 'livecodebench', 'scicode', 'math_500',
        'aime', 'aime_25', 'ifbench', 'lcr', 'tau2', 'tau_banking',
        'tokens_per_second', 'time_to_first_token', 'time_to_first_answer_token',
        'end_to_end_response_time', 'elo', 'confidence_interval',
        'samples', 'price_per_unit', 'price_unit', 'updated_at'
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
    sort_by: str = "release_date",
    sort_dir: str = "desc",
    limit: int = 100,
    offset: int = 0
):
    """
    Direct endpoint for 'rankindex' master table.
    Unified matrix merged from ormodels, orbench, aamodels, and aabanch.
    """
    _validate_pagination(limit, offset, maximum=1000)
    sort_dir = _validate_sort_dir(sort_dir)
    qs = RankIndex.objects.all()

    if search:
        s = search.strip()
        qs = qs.filter(Q(name__icontains=s) | Q(canonical_slug__icontains=s) | Q(provider__icontains=s) | Q(openrouter_id__icontains=s) | Q(aa_slug__icontains=s) | Q(modelsdev_id__icontains=s))

    if provider:
        qs = qs.filter(provider__icontains=provider.strip())

    if is_open_weight is not None:
        qs = qs.filter(is_open_weight=is_open_weight)

    if is_free is not None:
        qs = qs.filter(is_free=is_free)

    order_fields = {
        'rank': 'rank_overall',
        'rankllms_index': 'rankllms_index',
        'provider': 'provider',
        'intelligence': 'intelligence_index',
        'coding': 'coding_index',
        'agentic': 'agentic_index',
        'finance_and_accounting': 'finance_and_accounting_index',
        'strategy_and_ops': 'strategy_and_ops_index',
        'legal': 'legal_index',
        'healthcare_and_medical': 'healthcare_and_medical_index',
        'engineering': 'engineering_index',
        'economics': 'economics_index',
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
        'release_date': 'release_date',
    }
    if sort_by not in order_fields:
        raise HttpError(400, 'sort_by is not supported.')
    field = order_fields[sort_by]
    prefix = '-' if sort_dir == 'desc' else ''
    if field in {'release_date', 'rank_overall', 'rankllms_index', 'intelligence_index', 'coding_index', 'agentic_index', 'finance_and_accounting_index', 'strategy_and_ops_index', 'legal_index', 'healthcare_and_medical_index', 'engineering_index', 'economics_index', 'math_index', 'terminalbench_hard', 'terminalbench_v2_1', 'gpqa_diamond', 'mmlu_pro', 'hle', 'livecodebench', 'aime_25', 'design_arena_elo', 'ifbench', 'tau2', 'context_length', 'prompt_price_per_1m', 'completion_price_per_1m', 'tokens_per_second', 'time_to_first_token', 'time_to_first_answer_token', 'end_to_end_response_time'}:
        expression = F(field).desc(nulls_last=True) if prefix else F(field).asc(nulls_last=True)
        qs = qs.order_by(expression)
    else:
        qs = qs.order_by(f"{prefix}{field}")

    total = qs.count()
    items = list(qs[offset:offset + limit].values(
        'id', 'canonical_slug', 'name', 'provider', 'author_slug', 'openrouter_id',
        'aa_slug', 'modelsdev_id', 'family', 'version', 'aliases', 'category', 'status',
        'license', 'description', 'release_date', 'last_verified_at', 'input_modalities',
        'output_modalities', 'media_metrics', 'is_open_weight', 'is_free', 'reasoning', 'tool_call', 'structured_output',
        'rankllms_index', 'rank_overall', 'rank_coding', 'rank_reasoning', 'rank_value',
        'intelligence_index', 'coding_index', 'agentic_index',
        'finance_and_accounting_index', 'strategy_and_ops_index', 'legal_index',
        'healthcare_and_medical_index', 'engineering_index', 'economics_index',
        'math_index', 'terminalbench_hard',
        'terminalbench_v2_1', 'gpqa_diamond', 'mmlu_pro', 'hle', 'livecodebench',
        'scicode', 'math_500', 'aime_25', 'design_arena_elo', 'design_arena_win_rate',
        'ifbench', 'lcr', 'tau2', 'tau_banking', 'context_length', 'max_output_tokens',
        'prompt_price_per_1m', 'completion_price_per_1m',
        'aa_cache_hit_price_per_1m', 'aa_cache_write_price_per_1m', 'tokens_per_second',
        'time_to_first_token', 'time_to_first_answer_token', 'end_to_end_response_time',
        'media_metrics', 'has_openrouter', 'has_artificial_analysis',
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
    sort_by: str = "release_date",
    sort_dir: str = "desc",
    limit: int = 100,
    offset: int = 0,
    include_stale: bool = False,
):
    """
    Direct endpoint for 'modelsdev' table (models.dev provider/model catalog as-is).
    """
    _validate_pagination(limit, offset, maximum=1000)
    sort_dir = _validate_sort_dir(sort_dir)
    qs = ModelsDevModel.objects.all() if include_stale else ModelsDevModel.objects.filter(is_active=True)

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
    if sort_by not in order_fields:
        raise HttpError(400, 'sort_by is not supported.')
    field = order_fields[sort_by]
    prefix = '-' if sort_dir == 'desc' else ''
    if field in {'release_date', 'context_length', 'prompt_price_per_1m', 'completion_price_per_1m'}:
        qs = qs.order_by(
            F('release_date').desc(nulls_last=True) if prefix else F('release_date').asc(nulls_last=True)
        )
    else:
        qs = qs.order_by(f"{prefix}{field}")

    total = qs.count()
    items = list(qs[offset:offset + limit].values(
        'id', 'modelsdev_id', 'canonical_model_id', 'provider_slug', 'provider_name', 'name', 'is_active',
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


# ================= LEADERBOARD FROM MERGED RANKINDEX =================

@api.get("/leaderboard/rankindex", response=dict, tags=["LLM Leaderboard"])
def get_rankindex_leaderboard(
    request,
    sort_by: str = "rank",
    category: str = "",
    search: str = "",
    is_open_weight: Optional[bool] = None,
    is_free: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0
):
    """
    Leaderboard built from the merged 'rankindex' source of truth.
    sort_by: rank | rankllms_index | intelligence | coding | agentic | reasoning | value | context | price | speed
    category: '' | open | proprietary | free
    """
    _validate_pagination(limit, offset)
    if sort_by not in {'rank', 'rankllms_index', 'intelligence', 'coding', 'agentic', 'reasoning', 'value', 'context', 'price', 'speed'}:
        raise HttpError(400, 'sort_by is not supported.')
    if category not in {'', 'open', 'proprietary', 'free'}:
        raise HttpError(400, 'category is not supported.')
    qs = RankIndex.objects.all()

    if category == 'open':
        qs = qs.filter(is_open_weight=True)
    elif category == 'proprietary':
        qs = qs.filter(is_open_weight=False)
    elif category == 'free':
        qs = qs.filter(is_free=True)

    if is_open_weight is not None:
        qs = qs.filter(is_open_weight=is_open_weight)

    if is_free is not None:
        qs = qs.filter(is_free=is_free)

    if search:
        s = search.strip()
        qs = qs.filter(
            Q(name__icontains=s)
            | Q(provider__icontains=s)
            | Q(canonical_slug__icontains=s)
            | Q(openrouter_id__icontains=s)
            | Q(aa_slug__icontains=s)
            | Q(modelsdev_id__icontains=s)
        )

    fields = {
        'rank': 'rank_overall',
        'rankllms_index': 'rankllms_index',
        'intelligence': 'intelligence_index',
        'coding': 'coding_index',
        'agentic': 'agentic_index',
        'reasoning': 'rank_reasoning',
        'value': 'rank_value',
        'context': 'context_length',
        'price': 'prompt_price_per_1m',
        'speed': 'tokens_per_second',
    }
    field = fields[sort_by]
    ascending = sort_by in {'rank', 'price'}
    expression = F(field).asc(nulls_last=True) if ascending else F(field).desc(nulls_last=True)
    tie_breaker = F('rankllms_index').desc(nulls_last=True)
    qs = qs.order_by(expression, tie_breaker)

    total = qs.count()
    items = list(qs[offset:offset + limit].values(
        'id', 'canonical_slug', 'name', 'provider', 'author_slug', 'openrouter_id', 'aa_slug',
        'modelsdev_id', 'family', 'version', 'aliases', 'category', 'status', 'license',
        'description', 'release_date', 'last_verified_at', 'input_modalities', 'output_modalities',
        'is_open_weight', 'is_free', 'reasoning', 'tool_call', 'structured_output',
        'rankllms_index', 'rank_overall', 'rank_coding', 'rank_reasoning', 'rank_value',
        'intelligence_index', 'coding_index', 'agentic_index',
        'finance_and_accounting_index', 'strategy_and_ops_index', 'legal_index',
        'healthcare_and_medical_index', 'engineering_index', 'economics_index',
        'math_index', 'gpqa_diamond', 'media_metrics',
        'terminalbench_hard', 'livecodebench', 'context_length', 'max_output_tokens',
        'prompt_price_per_1m', 'completion_price_per_1m',
        'aa_cache_hit_price_per_1m', 'aa_cache_write_price_per_1m', 'tokens_per_second',
        'time_to_first_token', 'time_to_first_answer_token', 'end_to_end_response_time',
        'has_openrouter', 'has_artificial_analysis',
        'has_design_arena', 'sources', 'updated_at'
    ))

    rankings = []
    for idx, item in enumerate(items, start=offset + 1):
        row = dict(item)
        row['rank'] = item.get('rank_overall')
        rankings.append(row)

    return {
        "leaderboard": "rankindex",
        "source_table": "rankindex",
        "source_page": "/rankllms",
        "api": "/api/v1/leaderboard/rankindex",
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort_by": sort_by,
        "category": category,
        "count": len(rankings),
        "rankings": rankings,
    }
