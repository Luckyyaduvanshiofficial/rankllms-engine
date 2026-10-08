from django.db import models
from django.conf import settings as django_settings
from django.utils.text import slugify


class Provider(models.Model):
    """
    Represents an AI Company / Model Provider (OpenAI, Anthropic, Google, Meta, DeepSeek, Mistral, etc.).
    """
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=150, unique=True, db_index=True)
    website = models.URLField(blank=True, null=True)
    description = models.TextField(blank=True, default='')
    logo_url = models.URLField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class LLMModel(models.Model):
    """
    Core AI Model Registry entity.
    """
    MODEL_CATEGORY_CHOICES = [
        ('llm', 'Language Model'),
        ('image', 'Image Generation'),
        ('video', 'Video Generation'),
        ('audio', 'Audio Model'),
        ('embedding', 'Embedding Model'),
    ]

    openrouter_id = models.CharField(max_length=200, unique=True, db_index=True)
    slug = models.SlugField(max_length=250, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='models')
    category = models.CharField(max_length=50, choices=MODEL_CATEGORY_CHOICES, default='llm', db_index=True)
    description = models.TextField(blank=True, default='')

    # Open Source & License Classification (For Open-LLM Leaderboard)
    is_open_weight = models.BooleanField(null=True, blank=True, db_index=True, help_text="Whether a source confirms public model weights")
    license = models.CharField(max_length=100, blank=True, default='', help_text="License reported by a source, if known")

    # Status & Dates
    is_active = models.BooleanField(default=True, db_index=True)
    is_free = models.BooleanField(null=True, blank=True, db_index=True)
    created_at_openrouter = models.DateTimeField(null=True, blank=True)
    raw_json = models.JSONField(default=dict, blank=True)
    last_synced_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.openrouter_id})"


class ModelSpecification(models.Model):
    """
    Technical Specifications and Capabilities Matrix for a Model.
    """
    model = models.OneToOneField(LLMModel, on_delete=models.CASCADE, related_name='spec')
    context_length = models.IntegerField(null=True, blank=True, db_index=True)
    max_completion_tokens = models.IntegerField(null=True, blank=True)
    modality = models.CharField(max_length=100, blank=True, default='')
    tokenizer = models.CharField(max_length=100, blank=True, default='')
    instruct_type = models.CharField(max_length=100, blank=True, null=True)

    is_multimodal = models.BooleanField(null=True, blank=True, db_index=True)
    supports_vision = models.BooleanField(null=True, blank=True, db_index=True)
    supports_audio = models.BooleanField(null=True, blank=True, db_index=True)
    supports_tools = models.BooleanField(null=True, blank=True, db_index=True)
    supports_json_schema = models.BooleanField(null=True, blank=True)

    def __str__(self):
        context = f'{self.context_length:,} tokens' if self.context_length else 'context unknown'
        return f"Specs for {self.model.name} ({context})"


class ModelPricing(models.Model):
    """
    Normalized Pricing per 1 Million Tokens.
    """
    model = models.OneToOneField(LLMModel, on_delete=models.CASCADE, related_name='pricing')
    prompt_price_per_token = models.DecimalField(max_digits=20, decimal_places=12, null=True, blank=True)
    completion_price_per_token = models.DecimalField(max_digits=20, decimal_places=12, null=True, blank=True)
    image_price = models.DecimalField(max_digits=20, decimal_places=12, null=True, blank=True)
    request_price = models.DecimalField(max_digits=20, decimal_places=12, null=True, blank=True)

    prompt_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True, db_index=True)
    completion_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True, db_index=True)

    def __str__(self):
        return f"Pricing for {self.model.name}: ${self.prompt_price_per_1m}/1M prompt, ${self.completion_price_per_1m}/1M output"


class ModelBenchmark(models.Model):
    """
    Leaderboard Scores, SWE-Bench, Coding, Intelligence, and Latency/Speed Metrics.
    """
    model = models.OneToOneField(LLMModel, on_delete=models.CASCADE, related_name='benchmark')

    # Artificial Analysis Indices
    intelligence_index = models.FloatField(null=True, blank=True, db_index=True)
    coding_index = models.FloatField(null=True, blank=True, db_index=True)
    agentic_index = models.FloatField(null=True, blank=True, db_index=True)

    # SWE-Bench & Coding Leaderboard Benchmarks
    swe_bench_score = models.FloatField(null=True, blank=True, db_index=True, help_text="SWE-bench Resolved % (Software Engineering)")
    human_eval_score = models.FloatField(null=True, blank=True, help_text="HumanEval %")
    mmlu_score = models.FloatField(null=True, blank=True, help_text="MMLU %")
    arena_elo = models.FloatField(null=True, blank=True, db_index=True, help_text="LMSYS Chatbot Arena ELO")

    # Latency & Throughput Speed
    tokens_per_second = models.FloatField(null=True, blank=True, help_text="Throughput (TPS)")
    time_to_first_token = models.FloatField(null=True, blank=True, help_text="TTFT Latency (seconds)")

    class Meta:
        ordering = ['-intelligence_index', '-coding_index', '-swe_bench_score', '-arena_elo']

    def __str__(self):
        return f"Benchmarks for {self.model.name}: Intel={self.intelligence_index}, Coding={self.coding_index}, SWE={self.swe_bench_score}%"


class BenchmarkSnapshot(models.Model):
    """
    Historical record of benchmark scores at a point in time.
    Enables weekly top 10 to be reproducible and trend-chartable.
    """
    model = models.ForeignKey(LLMModel, on_delete=models.CASCADE, related_name='benchmark_history')
    captured_at = models.DateTimeField(db_index=True)

    intelligence_index = models.FloatField(default=0.0)
    coding_index = models.FloatField(default=0.0)
    agentic_index = models.FloatField(default=0.0)
    swe_bench_score = models.FloatField(default=0.0)
    human_eval_score = models.FloatField(default=0.0)
    mmlu_score = models.FloatField(default=0.0)
    arena_elo = models.FloatField(default=0.0)

    tokens_per_second = models.FloatField(default=0.0)
    time_to_first_token = models.FloatField(default=0.0)

    class Meta:
        ordering = ['-captured_at']
        unique_together = ('model', 'captured_at')
        indexes = [
            models.Index(fields=['captured_at', '-intelligence_index']),
        ]

    def __str__(self):
        return f"Benchmarks for {self.model.name} @ {self.captured_at}"


class WeeklyTop10Ranking(models.Model):
    """
    Weekly Curated & Calculated Top 10 Model Rankings for RankLLMs.com.
    """
    CATEGORY_CHOICES = [
        ('coding', 'Top 10 Coding Models'),
        ('writing_reasoning', 'Top 10 Writing & Reasoning Models'),
        ('open_source', 'Top 10 Open Source & Open Weight Models'),
        ('cost_effective', 'Top 10 Value / Cost-Effective Models'),
        ('overall', 'Top 10 Overall Best AI Models'),
    ]

    week_number = models.IntegerField(db_index=True)
    year = models.IntegerField(db_index=True)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, db_index=True)
    rank = models.IntegerField(db_index=True, help_text="Rank 1 to 10")
    model = models.ForeignKey(LLMModel, on_delete=models.CASCADE, related_name='weekly_rankings')
    highlight_reason = models.TextField(blank=True, default='', help_text="Why this model is ranked here this week")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['year', 'week_number', 'category', 'rank']
        unique_together = ('week_number', 'year', 'category', 'rank')

    def __str__(self):
        return f"{self.get_category_display()} [W{self.week_number}/{self.year}]: #{self.rank} {self.model.name}"


class DailyModelRanking(models.Model):
    """
    Daily token usage rankings across models (From /datasets/rankings-daily).
    """
    model = models.ForeignKey(LLMModel, on_delete=models.CASCADE, related_name='daily_rankings')
    date = models.DateField(db_index=True)
    total_tokens = models.BigIntegerField(default=0)

    class Meta:
        ordering = ['-date', '-total_tokens']
        unique_together = ('model', 'date')

    def __str__(self):
        return f"{self.model.name} [{self.date}]: {self.total_tokens:,} tokens"


class AppRanking(models.Model):
    """
    Top AI Apps by token usage (From /datasets/app-rankings).
    """
    app_id = models.BigIntegerField(unique=True)
    app_name = models.CharField(max_length=255)
    rank = models.IntegerField(db_index=True)
    total_tokens = models.BigIntegerField(default=0)
    total_requests = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['rank']

    def __str__(self):
        return f"#{self.rank} {self.app_name}: {self.total_tokens:,} tokens"


class TaskClassification(models.Model):
    """
    Task classification market share (Coding, Reasoning, Writing, Tagging).
    """
    tag = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=150)
    macro_category = models.CharField(max_length=100, blank=True, default='')
    usage_share = models.FloatField(default=0.0)
    token_share = models.FloatField(default=0.0)
    top_models_share = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-token_share']

    def __str__(self):
        return f"{self.display_name} ({self.token_share * 100:.1f}% token share)"


class PricingHistory(models.Model):
    """
    Historical log of pricing changes for models.
    """
    model = models.ForeignKey(LLMModel, on_delete=models.CASCADE, related_name='price_history')
    prompt_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6)
    completion_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-recorded_at']

    def __str__(self):
        return f"{self.model.name} @ {self.recorded_at}: ${self.prompt_price_per_1m}/1M in, ${self.completion_price_per_1m}/1M out"


import secrets

class APIKey(models.Model):
    """
    Developer API Keys for RankLLMs Data API.
    """
    TIER_CHOICES = [
        ('free', 'Free Tier (60 req/min)'),
        ('pro', 'Pro Tier (1000 req/min)'),
        ('admin', 'Admin Tier (Unlimited)'),
    ]

    key = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=255, help_text="Developer or Application name")
    tier = models.CharField(max_length=20, choices=TIER_CHOICES, default='free')
    is_active = models.BooleanField(default=True)
    total_requests = models.BigIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.tier.upper()}): {self.key[:12]}..."

    @classmethod
    def generate_key(cls, name: str, tier: str = 'free'):
        raw_key = f"rk_live_{secrets.token_hex(20)}"
        return cls.objects.create(key=raw_key, name=name, tier=tier)


class DataSourceConfig(models.Model):
    """Safe, non-secret operational controls for one upstream data source."""

    SOURCE_CHOICES = [
        ('openrouter', 'OpenRouter'),
        ('artificial_analysis', 'Artificial Analysis'),
        ('models_dev', 'models.dev'),
    ]

    source = models.CharField(max_length=40, choices=SOURCE_CHOICES, unique=True)
    enabled = models.BooleanField(default=True)
    timeout_seconds = models.PositiveSmallIntegerField(default=30)
    retry_count = models.PositiveSmallIntegerField(default=2)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['source']

    def __str__(self):
        return f'{self.get_source_display()} ({"enabled" if self.enabled else "disabled"})'


class SyncRun(models.Model):
    """Compact, persistent history for manual and scheduled data sync runs."""

    SOURCE_CHOICES = DataSourceConfig.SOURCE_CHOICES + [('all', 'All sources')]
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('succeeded', 'Succeeded'),
        ('partial', 'Partial'),
        ('failed', 'Failed'),
        ('dry_run', 'Dry run'),
    ]

    source = models.CharField(max_length=40, choices=SOURCE_CHOICES, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued', db_index=True)
    dry_run = models.BooleanField(default=False)
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    records_received = models.PositiveIntegerField(default=0)
    records_added = models.PositiveIntegerField(default=0)
    records_updated = models.PositiveIntegerField(default=0)
    records_skipped = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    error_summary = models.TextField(blank=True, default='')
    summary = models.JSONField(default=dict, blank=True)
    triggered_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rankllms_sync_runs',
    )
    # Only one queued/running job may hold this unique key. It is cleared when
    # the worker finishes, including on failure.
    active_key = models.CharField(max_length=16, unique=True, null=True, blank=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [models.Index(fields=['source', '-started_at'])]

    def __str__(self):
        mode = ' preview' if self.dry_run else ''
        return f'{self.get_source_display()}{mode}: {self.get_status_display()} ({self.started_at:%Y-%m-%d %H:%M})'


# ================= DEDICATED SOURCE TABLES (AS REQUESTED) =================

class ORModel(models.Model):
    """
    Direct OpenRouter Models Catalog (Table: ormodels).
    """
    openrouter_id = models.CharField(max_length=250, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    canonical_slug = models.CharField(max_length=250, blank=True, default='')
    author = models.CharField(max_length=150, blank=True, default='')
    description = models.TextField(blank=True, default='')
    context_length = models.IntegerField(null=True, blank=True, db_index=True)
    prompt_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True, db_index=True)
    completion_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True, db_index=True)
    is_free = models.BooleanField(null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    architecture = models.JSONField(default=dict, blank=True)
    top_provider = models.JSONField(default=dict, blank=True)
    pricing = models.JSONField(default=dict, blank=True)
    raw_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ormodels'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.openrouter_id})"


class ORBench(models.Model):
    """
    Direct OpenRouter Unified Benchmarks (Table: orbench).
    Aggregates openrouter, design-arena, and artificial-analysis empirical evals.
    """
    model_permaslug = models.CharField(max_length=250, db_index=True)
    display_name = models.CharField(max_length=255)
    source = models.CharField(max_length=100, db_index=True)  # openrouter, design-arena, artificial-analysis
    benchmark_type = models.CharField(max_length=150, blank=True, default='', db_index=True)
    accuracy = models.FloatField(null=True, blank=True, db_index=True)
    primary_score = models.FloatField(null=True, blank=True, db_index=True)
    primary_metric = models.CharField(max_length=80, blank=True, default='')
    elo = models.FloatField(null=True, blank=True, db_index=True)
    win_rate = models.FloatField(null=True, blank=True)
    category = models.CharField(max_length=100, blank=True, default='', db_index=True)
    arena = models.CharField(max_length=100, blank=True, default='')
    intelligence_index = models.FloatField(null=True, blank=True, db_index=True)
    coding_index = models.FloatField(null=True, blank=True, db_index=True)
    agentic_index = models.FloatField(null=True, blank=True)
    avg_cost_per_task = models.FloatField(null=True, blank=True)
    total_tasks = models.IntegerField(null=True, blank=True)
    tournament_stats = models.JSONField(default=dict, blank=True)
    pricing = models.JSONField(default=dict, blank=True)
    source_url = models.URLField(blank=True, default='')
    last_run_timestamp = models.DateTimeField(null=True, blank=True)
    raw_json = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, db_index=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'orbench'
        ordering = ['-accuracy', '-elo', '-intelligence_index']

    def __str__(self):
        return f"[{self.source}] {self.display_name} ({self.model_permaslug})"


class AAModel(models.Model):
    """
    Direct Artificial Analysis Models Catalog (Table: aamodels).
    """
    slug = models.CharField(max_length=250, unique=True, db_index=True)
    source_id = models.CharField(max_length=100, blank=True, default='', db_index=True)
    source_slug = models.CharField(max_length=250, blank=True, default='', db_index=True)
    source_endpoint = models.CharField(max_length=255, blank=True, default='')
    name = models.CharField(max_length=255)
    creator_name = models.CharField(max_length=150, db_index=True)
    creator_slug = models.CharField(max_length=150, blank=True, default='')
    is_active = models.BooleanField(default=True, db_index=True)
    release_date = models.DateField(null=True, blank=True)
    model_type = models.CharField(max_length=100, blank=True, default='')
    context_window = models.IntegerField(null=True, blank=True, db_index=True)
    max_output_tokens = models.IntegerField(null=True, blank=True)
    prompt_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    completion_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    cache_hit_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    cache_write_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    modalities = models.JSONField(default=list, blank=True)
    raw_json = models.JSONField(default=dict, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'aamodels'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.creator_name})"


class AABench(models.Model):
    """
    Direct Artificial Analysis Benchmark Evaluations & Telemetry (Table: aabanch).
    Captures source-published language indices, task scores, and performance telemetry.
    """
    model_slug = models.CharField(max_length=250, unique=True, db_index=True)
    source_id = models.CharField(max_length=100, blank=True, default='', db_index=True)
    source_slug = models.CharField(max_length=250, blank=True, default='', db_index=True)
    source_endpoint = models.CharField(max_length=255, blank=True, default='')
    model_name = models.CharField(max_length=255)
    creator_name = models.CharField(max_length=150, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    intelligence_index = models.FloatField(null=True, blank=True, db_index=True)
    coding_index = models.FloatField(null=True, blank=True, db_index=True)
    agentic_index = models.FloatField(null=True, blank=True, db_index=True)
    finance_and_accounting_index = models.FloatField(null=True, blank=True)
    strategy_and_ops_index = models.FloatField(null=True, blank=True)
    legal_index = models.FloatField(null=True, blank=True)
    healthcare_and_medical_index = models.FloatField(null=True, blank=True)
    engineering_index = models.FloatField(null=True, blank=True)
    economics_index = models.FloatField(null=True, blank=True)
    math_index = models.FloatField(null=True, blank=True, db_index=True)
    terminalbench_hard = models.FloatField(null=True, blank=True)
    terminalbench_v2_1 = models.FloatField(null=True, blank=True)
    gpqa = models.FloatField(null=True, blank=True)
    mmlu_pro = models.FloatField(null=True, blank=True)
    hle = models.FloatField(null=True, blank=True)  # Humanity's Last Exam
    livecodebench = models.FloatField(null=True, blank=True)
    scicode = models.FloatField(null=True, blank=True)
    math_500 = models.FloatField(null=True, blank=True)
    aime = models.FloatField(null=True, blank=True)
    aime_25 = models.FloatField(null=True, blank=True)  # AIME 2025
    ifbench = models.FloatField(null=True, blank=True)  # Instruction Following
    lcr = models.FloatField(null=True, blank=True)  # Long Context Reasoning
    tau2 = models.FloatField(null=True, blank=True)  # Tau-Bench 2
    tau_banking = models.FloatField(null=True, blank=True)
    tokens_per_second = models.FloatField(null=True, blank=True, db_index=True)
    time_to_first_token = models.FloatField(null=True, blank=True, db_index=True)
    time_to_first_answer_token = models.FloatField(null=True, blank=True)
    end_to_end_response_time = models.FloatField(null=True, blank=True)
    elo = models.FloatField(null=True, blank=True, db_index=True)
    confidence_interval = models.FloatField(null=True, blank=True)
    samples = models.IntegerField(null=True, blank=True)
    price_per_unit = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    price_unit = models.CharField(max_length=60, blank=True, default='')
    raw_json = models.JSONField(default=dict, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'aabanch'
        ordering = ['-intelligence_index', '-coding_index']

    def __str__(self):
        return f"{self.model_name} (Intel: {self.intelligence_index}, Code: {self.coding_index})"


class ModelsDevModel(models.Model):
    """
    Direct models.dev catalog (Table: modelsdev).
    Source: https://models.dev/api.json — free public provider/model metadata.
    """
    modelsdev_id = models.CharField(max_length=250, unique=True, db_index=True)
    canonical_model_id = models.CharField(max_length=250, blank=True, default='', db_index=True)
    provider_slug = models.CharField(max_length=150, db_index=True)
    provider_name = models.CharField(max_length=150, blank=True, default='')
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True, db_index=True)
    description = models.TextField(blank=True, default='')
    family = models.CharField(max_length=100, blank=True, default='', db_index=True)
    reasoning = models.BooleanField(null=True, blank=True, db_index=True)
    tool_call = models.BooleanField(null=True, blank=True, db_index=True)
    structured_output = models.BooleanField(null=True, blank=True)
    temperature = models.BooleanField(null=True, blank=True)
    open_weights = models.BooleanField(null=True, blank=True, db_index=True)
    release_date = models.DateField(null=True, blank=True, db_index=True)
    last_updated = models.DateField(null=True, blank=True)
    modalities = models.JSONField(default=dict, blank=True)
    context_length = models.IntegerField(null=True, blank=True, db_index=True)
    max_output_tokens = models.IntegerField(null=True, blank=True)
    prompt_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True, db_index=True)
    completion_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    cache_read_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=50, blank=True, default='')
    raw_json = models.JSONField(default=dict, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'modelsdev'
        ordering = ['provider_name', 'name']

    def __str__(self):
        return f"{self.name} ({self.provider_name})"


# ================= MERGED MASTER TABLE: rankindex =================

class RankIndex(models.Model):
    """
    Unified Master Table (Table: rankindex).
    Merges all 4 source tables: ormodels, orbench, aamodels, and aabanch.
    """
    canonical_slug = models.CharField(max_length=250, unique=True, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    provider = models.CharField(max_length=150, db_index=True)
    author_slug = models.CharField(max_length=150, blank=True, default='')
    openrouter_id = models.CharField(max_length=250, blank=True, default='', db_index=True)
    aa_slug = models.CharField(max_length=250, blank=True, default='', db_index=True)
    modelsdev_id = models.CharField(max_length=250, blank=True, default='', db_index=True)
    family = models.CharField(max_length=150, blank=True, default='', db_index=True)
    version = models.CharField(max_length=100, blank=True, default='')
    aliases = models.JSONField(default=list, blank=True)
    category = models.CharField(max_length=40, blank=True, default='llm', db_index=True)
    status = models.CharField(max_length=50, blank=True, default='')
    license = models.CharField(max_length=150, blank=True, default='')
    description = models.TextField(blank=True, default='')
    release_date = models.DateField(null=True, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    input_modalities = models.JSONField(default=list, blank=True)
    output_modalities = models.JSONField(default=list, blank=True)
    media_metrics = models.JSONField(default=dict, blank=True)
    is_open_weight = models.BooleanField(null=True, blank=True, db_index=True)
    is_free = models.BooleanField(null=True, blank=True, db_index=True)
    reasoning = models.BooleanField(null=True, blank=True)
    tool_call = models.BooleanField(null=True, blank=True)
    structured_output = models.BooleanField(null=True, blank=True)

    # Master Composite Rankings
    rankllms_index = models.FloatField(null=True, blank=True, db_index=True)
    rank_overall = models.IntegerField(null=True, blank=True, db_index=True)
    rank_coding = models.IntegerField(null=True, blank=True)
    rank_reasoning = models.IntegerField(null=True, blank=True)
    rank_value = models.IntegerField(null=True, blank=True)

    # Empirical Benchmarks (Merged from orbench + aabanch)
    intelligence_index = models.FloatField(null=True, blank=True, db_index=True)
    coding_index = models.FloatField(null=True, blank=True, db_index=True)
    agentic_index = models.FloatField(null=True, blank=True, db_index=True)
    finance_and_accounting_index = models.FloatField(null=True, blank=True)
    strategy_and_ops_index = models.FloatField(null=True, blank=True)
    legal_index = models.FloatField(null=True, blank=True)
    healthcare_and_medical_index = models.FloatField(null=True, blank=True)
    engineering_index = models.FloatField(null=True, blank=True)
    economics_index = models.FloatField(null=True, blank=True)
    math_index = models.FloatField(null=True, blank=True)
    terminalbench_hard = models.FloatField(null=True, blank=True)
    terminalbench_v2_1 = models.FloatField(null=True, blank=True)
    gpqa_diamond = models.FloatField(null=True, blank=True)
    mmlu_pro = models.FloatField(null=True, blank=True)
    hle = models.FloatField(null=True, blank=True)
    livecodebench = models.FloatField(null=True, blank=True)
    scicode = models.FloatField(null=True, blank=True)
    math_500 = models.FloatField(null=True, blank=True)
    aime_25 = models.FloatField(null=True, blank=True)
    design_arena_elo = models.FloatField(null=True, blank=True)
    design_arena_win_rate = models.FloatField(null=True, blank=True)
    ifbench = models.FloatField(null=True, blank=True)
    lcr = models.FloatField(null=True, blank=True)
    tau2 = models.FloatField(null=True, blank=True)
    tau_banking = models.FloatField(null=True, blank=True)

    # Hardware Telemetry & Economics (Merged from ormodels + aamodels)
    context_length = models.IntegerField(null=True, blank=True, db_index=True)
    max_output_tokens = models.IntegerField(null=True, blank=True)
    prompt_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True, db_index=True)
    completion_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True, db_index=True)
    aa_cache_hit_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    aa_cache_write_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    tokens_per_second = models.FloatField(null=True, blank=True, db_index=True)
    time_to_first_token = models.FloatField(null=True, blank=True, db_index=True)
    time_to_first_answer_token = models.FloatField(null=True, blank=True)
    end_to_end_response_time = models.FloatField(null=True, blank=True)

    # Sources & Metadata
    has_openrouter = models.BooleanField(default=False)
    has_artificial_analysis = models.BooleanField(default=False)
    has_design_arena = models.BooleanField(default=False)
    sources = models.JSONField(default=list, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rankindex'
        ordering = ['rank_overall', '-rankllms_index', '-intelligence_index']

    def __str__(self):
        return f"#{self.rank_overall} {self.name} ({self.provider}) - Index: {self.rankllms_index:.1f}"
