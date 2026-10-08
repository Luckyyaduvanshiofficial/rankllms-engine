"""Artificial Analysis API v2 language-model client and page traversal."""

from django.conf import settings

from llms.services.source_http import UpstreamSourceError, fetch_json, require_list


PAGE_SIZE = 200
MAX_PAGES = 200
MEDIA_ENDPOINTS = {
    'image': (
        'media/text-to-image/models/free',
        'media/image-editing/models/free',
    ),
    'video': (
        'media/text-to-video/models/free',
        'media/image-to-video/models/free',
        'media/text-to-video-audio/models/free',
        'media/image-to-video-audio/models/free',
    ),
    'audio': (
        'media/text-to-speech/models/free',
        'media/speech-to-speech/models/free',
        'media/speech-to-text/models/free',
    ),
    'music': (
        'media/music/instrumental/models/free',
        'media/music/with-vocals/models/free',
    ),
}


def _pagination_info(payload):
    info = payload.get('pagination') if isinstance(payload, dict) else None
    return info if isinstance(info, dict) else {}


def _has_more(payload, current_page, rows_in_page):
    pagination = _pagination_info(payload)
    for key in ('has_more', 'has_next', 'has_next_page'):
        if key in pagination:
            return bool(pagination[key])
    next_value = pagination.get('next') or pagination.get('next_page')
    if next_value:
        return True
    total_pages = next((
        pagination.get(key)
        for key in ('total_pages', 'pages', 'last_page', 'page_count')
        if pagination.get(key) is not None
    ), None)
    if total_pages is not None:
        try:
            return current_page < int(total_pages)
        except (TypeError, ValueError):
            pass
    total_items = next((
        pagination.get(key)
        for key in ('total_items', 'total_records', 'total')
        if pagination.get(key) is not None
    ), None)
    if total_items is not None:
        try:
            return current_page * PAGE_SIZE < int(total_items)
        except (TypeError, ValueError):
            pass
    return rows_in_page >= PAGE_SIZE


def fetch_language_models():
    """Fetch every AA model page and reject malformed or empty snapshots."""
    api_key = getattr(settings, 'ARTIFICIAL_ANALYSIS_API_KEY', '') or ''
    if not api_key:
        raise UpstreamSourceError('artificial_analysis', 'Artificial Analysis API key is not configured.')
    base_url = getattr(settings, 'ARTIFICIAL_ANALYSIS_API_URL', 'https://artificialanalysis.ai/api/v2')
    model_path = getattr(settings, 'ARTIFICIAL_ANALYSIS_MODELS_PATH', 'language/models/free').strip('/')
    if model_path not in {'language/models/free', 'language/models'}:
        raise UpstreamSourceError('artificial_analysis', 'ARTIFICIAL_ANALYSIS_MODELS_PATH must be language/models/free or language/models.')
    url = f'{base_url.rstrip("/")}/{model_path}'
    headers = {'x-api-key': api_key, 'Accept': 'application/json', 'User-Agent': 'RankLLMs-Engine/1.0'}
    all_models = []
    seen_ids = set()

    for page in range(1, MAX_PAGES + 1):
        payload = fetch_json(
            'artificial_analysis',
            url,
            headers=headers,
            # AA documents only `page` as a request parameter. PAGE_SIZE is
            # used to bound fallback pagination when older envelopes omit it.
            params={'page': page},
        )
        rows = require_list(payload, source='artificial_analysis', path=('data',), allow_empty=True)
        malformed = sum(
            1 for row in rows
            if not isinstance(row, dict) or not (row.get('id') or row.get('slug'))
        )
        if rows and malformed > max(0, int(len(rows) * 0.1)):
            raise UpstreamSourceError('artificial_analysis', 'Too many AA model records are missing source IDs; existing data was kept.')
        for row in rows:
            if not isinstance(row, dict):
                continue
            model_id = row.get('id') or row.get('slug')
            if not model_id:
                continue
            normalized_id = str(model_id).strip().casefold()
            if normalized_id in seen_ids:
                continue
            seen_ids.add(normalized_id)
            all_models.append(row)
        if not _has_more(payload, page, len(rows)):
            break
    else:
        raise UpstreamSourceError('artificial_analysis', 'Artificial Analysis pagination exceeded the safety limit.')

    if not all_models:
        raise UpstreamSourceError('artificial_analysis', 'Artificial Analysis returned no valid models; existing data was kept.')
    return all_models


def fetch_media_models():
    """Fetch the documented Free-tier media arena snapshots by type."""
    api_key = getattr(settings, 'ARTIFICIAL_ANALYSIS_API_KEY', '') or ''
    if not api_key:
        raise UpstreamSourceError('artificial_analysis', 'Artificial Analysis API key is not configured.')
    base_url = getattr(settings, 'ARTIFICIAL_ANALYSIS_API_URL', 'https://artificialanalysis.ai/api/v2')
    headers = {'x-api-key': api_key, 'Accept': 'application/json', 'User-Agent': 'RankLLMs-Engine/1.0'}
    datasets = {}
    for category, endpoints in MEDIA_ENDPOINTS.items():
        for endpoint in endpoints:
            payload = fetch_json('artificial_analysis', f'{base_url.rstrip("/")}/{endpoint}', headers=headers)
            rows = require_list(payload, source='artificial_analysis', path=('data',), allow_empty=True)
            malformed = sum(
                1 for row in rows
                if not isinstance(row, dict) or not (row.get('id') or row.get('slug'))
            )
            if rows and malformed > max(0, int(len(rows) * 0.1)):
                raise UpstreamSourceError('artificial_analysis', f'{endpoint} returned too many records without source IDs; existing data was kept.')
            datasets[endpoint] = (category, rows)
    return datasets
