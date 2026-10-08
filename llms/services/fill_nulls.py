"""Non-mutating catalog completeness report.

This module used to invent scores, context limits, output caps, prices, and
Arena ELO values from model names. Unknown source data must stay unknown, so the
legacy command now reports gaps without writing inferred values.
"""

from django.db.models import Q

from llms.models import LLMModel, ModelBenchmark, ModelPricing, ModelSpecification


def fill_all_nulls():
    """Return current coverage; deliberately does not synthesize missing data."""
    total = LLMModel.objects.count()
    return {
        'total_models': total,
        'missing_specifications': total - ModelSpecification.objects.count(),
        'missing_pricing_rows': total - ModelPricing.objects.count(),
        'missing_benchmark_rows': total - ModelBenchmark.objects.count(),
        'models_without_context': ModelSpecification.objects.filter(
            Q(context_length__isnull=True) | Q(context_length__lte=0)
        ).count(),
        'note': 'No source value was inferred or written.',
    }
