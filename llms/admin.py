from django.contrib import admin
from .models import (
    Provider, LLMModel, ModelSpecification, ModelPricing,
    ModelBenchmark, WeeklyTop10Ranking, PricingHistory,
    DailyModelRanking, AppRanking, TaskClassification
)


class ModelSpecificationInline(admin.StackedInline):
    model = ModelSpecification
    can_delete = False
    verbose_name_plural = 'Technical Specifications'


class ModelPricingInline(admin.StackedInline):
    model = ModelPricing
    can_delete = False
    verbose_name_plural = 'Model Pricing ($ / 1M Tokens)'


class ModelBenchmarkInline(admin.StackedInline):
    model = ModelBenchmark
    can_delete = False
    verbose_name_plural = 'Leaderboard & Benchmarks'


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'created_at')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    list_filter = ('is_active',)


@admin.register(LLMModel)
class LLMModelAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'openrouter_id', 'provider', 'category', 'is_open_weight',
        'license', 'is_free', 'is_active', 'last_synced_at'
    )
    search_fields = ('name', 'openrouter_id', 'provider__name', 'description')
    list_filter = (
        'provider', 'category', 'is_open_weight', 'license', 'is_free', 'is_active'
    )
    inlines = [ModelSpecificationInline, ModelPricingInline, ModelBenchmarkInline]
    ordering = ('-last_synced_at',)


@admin.register(WeeklyTop10Ranking)
class WeeklyTop10RankingAdmin(admin.ModelAdmin):
    list_display = ('year', 'week_number', 'category', 'rank', 'model', 'highlight_reason')
    search_fields = ('model__name', 'highlight_reason')
    list_filter = ('year', 'week_number', 'category')
    ordering = ('-year', '-week_number', 'category', 'rank')


@admin.register(DailyModelRanking)
class DailyModelRankingAdmin(admin.ModelAdmin):
    list_display = ('model', 'date', 'total_tokens')
    search_fields = ('model__name', 'model__openrouter_id')
    list_filter = ('date',)


@admin.register(AppRanking)
class AppRankingAdmin(admin.ModelAdmin):
    list_display = ('rank', 'app_name', 'total_tokens', 'total_requests', 'updated_at')
    search_fields = ('app_name',)


@admin.register(TaskClassification)
class TaskClassificationAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'tag', 'macro_category', 'usage_share', 'token_share', 'updated_at')
    search_fields = ('display_name', 'tag', 'macro_category')


@admin.register(PricingHistory)
class PricingHistoryAdmin(admin.ModelAdmin):
    list_display = ('model', 'prompt_price_per_1m', 'completion_price_per_1m', 'recorded_at')
    search_fields = ('model__name', 'model__openrouter_id')
    list_filter = ('recorded_at',)
