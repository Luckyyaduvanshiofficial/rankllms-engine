"""Public benchmark reads use the last validated database snapshot."""

from llms.models import ORBench


def fetch_openrouter_unified_benchmarks():
    """Return stored source payloads; never call OpenRouter during a user read."""
    rows = []
    for item in ORBench.objects.filter(is_active=True).iterator(chunk_size=500):
        payload = dict(item.raw_json or {})
        payload.setdefault('model_permaslug', item.model_permaslug)
        payload.setdefault('display_name', item.display_name)
        payload.setdefault('source', item.source)
        payload.setdefault('benchmark_type', item.benchmark_type)
        payload.setdefault('accuracy', item.accuracy)
        payload.setdefault('elo', item.elo)
        payload.setdefault('win_rate', item.win_rate)
        payload.setdefault('category', item.category)
        payload.setdefault('arena', item.arena)
        payload.setdefault('intelligence_index', item.intelligence_index)
        payload.setdefault('coding_index', item.coding_index)
        payload.setdefault('agentic_index', item.agentic_index)
        payload.setdefault('pricing', item.pricing or {})
        rows.append(payload)
    return rows
