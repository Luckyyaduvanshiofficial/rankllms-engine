from django.db import models
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
        ('embedding', 'Embedding Model'),
    ]

    openrouter_id = models.CharField(max_length=200, unique=True, db_index=True)
    slug = models.SlugField(max_length=250, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='models')
    category = models.CharField(max_length=50, choices=MODEL_CATEGORY_CHOICES, default='llm', db_index=True)
    description = models.TextField(blank=True, default='')

    # Open Source & License Classification (For Open-LLM Leaderboard)
    is_open_weight = models.BooleanField(default=False, db_index=True, help_text="True for open-source/open-weight models (Llama, DeepSeek, Qwen)")
    license = models.CharField(max_length=100, blank=True, default='Proprietary', help_text="License type (e.g. MIT, Apache 2.0, Llama 3.3, Proprietary)")

    # Status & Dates
    is_active = models.BooleanField(default=True, db_index=True)
    is_free = models.BooleanField(default=False, db_index=True)
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
    context_length = models.IntegerField(default=0, db_index=True)
    max_completion_tokens = models.IntegerField(null=True, blank=True)
    modality = models.CharField(max_length=100, blank=True, default='')
    tokenizer = models.CharField(max_length=100, blank=True, default='')
    instruct_type = models.CharField(max_length=100, blank=True, null=True)

    is_multimodal = models.BooleanField(default=False, db_index=True)
    supports_vision = models.BooleanField(default=False, db_index=True)
    supports_audio = models.BooleanField(default=False, db_index=True)
    supports_tools = models.BooleanField(default=False, db_index=True)
    supports_json_schema = models.BooleanField(default=False)

    def __str__(self):
        return f"Specs for {self.model.name} ({self.context_length:,} tokens)"


class ModelPricing(models.Model):
    """
    Normalized Pricing per 1 Million Tokens.
    """
    model = models.OneToOneField(LLMModel, on_delete=models.CASCADE, related_name='pricing')
    prompt_price_per_token = models.DecimalField(max_digits=20, decimal_places=12, default=0.0)
    completion_price_per_token = models.DecimalField(max_digits=20, decimal_places=12, default=0.0)
    image_price = models.DecimalField(max_digits=20, decimal_places=12, default=0.0)
    request_price = models.DecimalField(max_digits=20, decimal_places=12, default=0.0)

    prompt_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, default=0.0, db_index=True)
    completion_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, default=0.0, db_index=True)

    def __str__(self):
        return f"Pricing for {self.model.name}: ${self.prompt_price_per_1m}/1M prompt, ${self.completion_price_per_1m}/1M output"


class ModelBenchmark(models.Model):
    """
    Leaderboard Scores, SWE-Bench, Coding, Intelligence, and Latency/Speed Metrics.
    """
    model = models.OneToOneField(LLMModel, on_delete=models.CASCADE, related_name='benchmark')

    # Artificial Analysis Indices
    intelligence_index = models.FloatField(default=0.0, db_index=True)
    coding_index = models.FloatField(default=0.0, db_index=True)
    agentic_index = models.FloatField(default=0.0, db_index=True)

    # SWE-Bench & Coding Leaderboard Benchmarks
    swe_bench_score = models.FloatField(default=0.0, db_index=True, help_text="SWE-bench Resolved % (Software Engineering)")
    human_eval_score = models.FloatField(default=0.0, help_text="HumanEval %")
    mmlu_score = models.FloatField(default=0.0, help_text="MMLU %")
    arena_elo = models.FloatField(default=0.0, db_index=True, help_text="LMSYS Chatbot Arena ELO")

    # Latency & Throughput Speed
    tokens_per_second = models.FloatField(default=0.0, help_text="Throughput (TPS)")
    time_to_first_token = models.FloatField(default=0.0, help_text="TTFT Latency (seconds)")

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
    context_length = models.IntegerField(default=0, db_index=True)
    prompt_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, default=0.0, db_index=True)
    completion_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, default=0.0, db_index=True)
    is_free = models.BooleanField(default=False, db_index=True)
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
    raw_json = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

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
    name = models.CharField(max_length=255)
    creator_name = models.CharField(max_length=150, db_index=True)
    creator_slug = models.CharField(max_length=150, blank=True, default='')
    release_date = models.DateField(null=True, blank=True)
    model_type = models.CharField(max_length=100, blank=True, default='')
    context_window = models.IntegerField(default=0, db_index=True)
    max_output_tokens = models.IntegerField(null=True, blank=True)
    prompt_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, default=0.0)
    completion_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, default=0.0)
    modalities = models.JSONField(default=list, blank=True)
    raw_json = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'aamodels'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.creator_name})"


class AABench(models.Model):
    """
    Direct Artificial Analysis Benchmark Evaluations & Telemetry (Table: aabanch).
    Captures all 17 empirical benchmark evaluation metrics.
    """
    model_slug = models.CharField(max_length=250, unique=True, db_index=True)
    model_name = models.CharField(max_length=255)
    creator_name = models.CharField(max_length=150, db_index=True)
    intelligence_index = models.FloatField(default=0.0, db_index=True)
    coding_index = models.FloatField(default=0.0, db_index=True)
    math_index = models.FloatField(default=0.0, db_index=True)
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
    tokens_per_second = models.FloatField(default=0.0, db_index=True)
    time_to_first_token = models.FloatField(default=0.0, db_index=True)
    raw_json = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'aabanch'
        ordering = ['-intelligence_index', '-coding_index']

    def __str__(self):
        return f"{self.model_name} (Intel: {self.intelligence_index}, Code: {self.coding_index})"


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
    description = models.TextField(blank=True, default='')
    release_date = models.DateField(null=True, blank=True)
    is_open_weight = models.BooleanField(default=False, db_index=True)
    is_free = models.BooleanField(default=False, db_index=True)

    # Master Composite Rankings
    rankllms_index = models.FloatField(default=0.0, db_index=True)
    rank_overall = models.IntegerField(default=0, db_index=True)
    rank_coding = models.IntegerField(default=0)
    rank_reasoning = models.IntegerField(default=0)
    rank_value = models.IntegerField(default=0)

    # Empirical Benchmarks (Merged from orbench + aabanch)
    intelligence_index = models.FloatField(default=0.0, db_index=True)
    coding_index = models.FloatField(default=0.0, db_index=True)
    math_index = models.FloatField(default=0.0, db_index=True)
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
    context_length = models.IntegerField(default=0, db_index=True)
    max_output_tokens = models.IntegerField(null=True, blank=True)
    prompt_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, default=0.0, db_index=True)
    completion_price_per_1m = models.DecimalField(max_digits=14, decimal_places=6, default=0.0, db_index=True)
    tokens_per_second = models.FloatField(default=0.0, db_index=True)
    time_to_first_token = models.FloatField(default=0.0, db_index=True)

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

