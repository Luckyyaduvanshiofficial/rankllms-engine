import os
import time
import requests
from django.conf import settings

_OPENROUTER_BENCHMARKS_CACHE = {
    "data": None,
    "timestamp": 0,
}

CACHE_TTL_SECONDS = 3600  # 1 hour cache


def fetch_openrouter_unified_benchmarks(force_refresh: bool = False):
    """
    Fetches raw unified benchmarks from OpenRouter API v1 /benchmarks
    Aggregating Artificial Analysis, Design Arena, and OpenRouter's own GPQA, Tau-bench, and search evals.
    """
    global _OPENROUTER_BENCHMARKS_CACHE

    now = time.time()
    if not force_refresh and _OPENROUTER_BENCHMARKS_CACHE["data"] and (now - _OPENROUTER_BENCHMARKS_CACHE["timestamp"] < CACHE_TTL_SECONDS):
        return _OPENROUTER_BENCHMARKS_CACHE["data"]

    api_key = getattr(settings, 'OPENROUTER_API_KEY', '') or os.getenv('OPENROUTER_API_KEY', '')
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://rankllms.ai",
        "X-Title": "RankLLMs Engine"
    }

    try:
        res = requests.get("https://openrouter.ai/api/v1/benchmarks", headers=headers, timeout=20)
        if res.status_code == 200:
            raw_data = res.json().get("data", [])
            _OPENROUTER_BENCHMARKS_CACHE["data"] = raw_data
            _OPENROUTER_BENCHMARKS_CACHE["timestamp"] = now
            return raw_data
        else:
            print(f"[OpenRouter Benchmarks] Failed status {res.status_code}: {res.text[:200]}")
    except Exception as e:
        print(f"[OpenRouter Benchmarks] Request error: {e}")

    return _OPENROUTER_BENCHMARKS_CACHE["data"] or []
