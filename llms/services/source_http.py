"""Bounded, host-allowlisted HTTP access to configured model-data sources."""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import requests
from django.db.utils import DatabaseError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)
_rate_limit_lock = threading.Lock()
_last_rate_limits = {}


def get_rate_limit_snapshot(source):
    with _rate_limit_lock:
        return dict(_last_rate_limits.get(source, {}))


def _retry_delay(retry_after, attempt):
    if retry_after:
        try:
            delay = float(retry_after)
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(retry_after)
                delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                delay = None
        if delay is not None:
            return min(max(delay, 0.0), BoundedRetry.retry_after_cap_seconds)
    backoff = min(0.4 * (2 ** attempt), BoundedRetry.retry_after_cap_seconds)
    return backoff + random.uniform(0, min(0.3, backoff / 4))

SOURCE_HOSTS = {
    'openrouter': {'openrouter.ai'},
    'artificial_analysis': {'artificialanalysis.ai'},
    'models_dev': {'models.dev'},
}


class UpstreamSourceError(RuntimeError):
    def __init__(self, source: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.source = source
        self.status_code = status_code


class BoundedRetry(Retry):
    """Expose the retry wait cap shared with the status-response retry loop."""

    retry_after_cap_seconds = 30


def _source_options(source: str) -> tuple[int, int]:
    timeout_seconds, retry_count = 30, 2
    try:
        from llms.models import DataSourceConfig

        config = DataSourceConfig.objects.filter(source=source).first()
        if config:
            timeout_seconds = max(5, min(int(config.timeout_seconds), 120))
            retry_count = max(0, min(int(config.retry_count), 5))
    except DatabaseError:
        # Defaults keep ingestion usable during initial migration/bootstrap.
        pass
    return timeout_seconds, retry_count


def fetch_json(source: str, url: str, *, headers=None, params=None, timeout=None):
    """Fetch one JSON response with strict source host validation and retries."""
    hosts = SOURCE_HOSTS.get(source)
    if not hosts:
        raise UpstreamSourceError(source, 'Unknown upstream source.')
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password:
        raise UpstreamSourceError(source, 'Configured upstream URL is not an approved HTTPS host.')

    configured_timeout, retries = _source_options(source)
    timeout = max(5, min(int(timeout or configured_timeout), 120))
    retry = BoundedRetry(
        total=retries,
        connect=retries,
        read=retries,
        status=0,
        backoff_factor=0.4,
        status_forcelist=(),
        allowed_methods=frozenset({'GET'}),
        respect_retry_after_header=False,
        raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)
    try:
        for attempt in range(retries + 1):
            response = session.get(
                url,
                headers=headers or {},
                params=params,
                timeout=(min(10, timeout), timeout),
                allow_redirects=False,
            )
            rate_headers = {
                key: response.headers[value]
                for key, value in (
                    ('tier', 'X-AA-Tier'),
                    ('limit', 'X-RateLimit-Limit'),
                    ('remaining', 'X-RateLimit-Remaining'),
                    ('reset', 'X-RateLimit-Reset'),
                    ('retry_after', 'Retry-After'),
                )
                if response.headers.get(value) is not None
            }
            with _rate_limit_lock:
                _last_rate_limits[source] = rate_headers

            retryable_status = response.status_code in (429, 500, 502, 503, 504)
            if not retryable_status or attempt >= retries:
                break
            delay = _retry_delay(response.headers.get('Retry-After'), attempt)
            time.sleep(delay)
    except requests.RequestException as exc:
        logger.warning('Upstream fetch failed', extra={'source': source, 'error_type': type(exc).__name__})
        raise UpstreamSourceError(source, f'{source} request failed ({type(exc).__name__}).') from exc
    finally:
        session.close()

    if response.status_code >= 300:
        logger.warning(
            'Upstream returned an error',
            extra={
                'source': source,
                'status_code': response.status_code,
                'retry_after': response.headers.get('Retry-After'),
            },
        )
        status_message = f'{source} returned HTTP {response.status_code}.'
        if 300 <= response.status_code < 400:
            status_message = f'{source} attempted an unconfigured redirect; the response was rejected.'
        raise UpstreamSourceError(source, status_message, status_code=response.status_code)
    try:
        return response.json()
    except (ValueError, requests.exceptions.JSONDecodeError) as exc:
        raise UpstreamSourceError(source, f'{source} returned invalid JSON.') from exc


def require_list(payload, *, source: str, path: tuple[str, ...] = (), allow_empty=False):
    """Validate a response envelope without silently treating a bad shape as empty."""
    current = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            raise UpstreamSourceError(source, f'{source} response is missing the expected data field.')
        current = current[key]
    if not isinstance(current, list):
        raise UpstreamSourceError(source, f'{source} response data must be a list.')
    if not current and not allow_empty:
        raise UpstreamSourceError(source, f'{source} returned an empty snapshot; existing data was kept.')
    return current


def require_mapping(payload, *, source: str):
    if not isinstance(payload, dict) or not payload:
        raise UpstreamSourceError(source, f'{source} returned an empty or invalid snapshot.')
    return payload


def reject_suspicious_shrink(source: str, received: int, previous: int, *, floor=100, minimum_ratio=0.5):
    """Keep a last-good snapshot if a large catalog suddenly arrives partial."""
    if previous >= floor and received < previous * minimum_ratio:
        raise UpstreamSourceError(
            source,
            f'{source} returned {received} records after a {previous}-record snapshot; a >50% shrink was rejected and existing data was kept.',
        )
