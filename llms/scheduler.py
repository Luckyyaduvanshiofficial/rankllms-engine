import fcntl
import logging
import os
import sys

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler = None
_lock_handle = None


def is_enabled() -> bool:
    """Single source of truth for the opt-in flag.

    apps.py and the entrypoint both need to answer "is the in-process
    scheduler on?", so the parsing lives here once instead of being
    re-implemented (and drifting) in each caller.
    """
    return os.environ.get('ENABLE_SCHEDULER', '').strip().lower() in ('1', 'true', 'yes', 'on')


def _in_migrations_or_commands() -> bool:
    """True while a management command runs, so ready() can stay quiet.

    Scans every argument, not just argv[1], so `manage.py --verbosity 2
    migrate` is caught too. Migrations and collectstatic load the app
    registry, which would otherwise start a sync nobody is waiting on.
    """
    commands = {
        'migrate', 'makemigrations', 'collectstatic', 'shell', 'dbshell',
        'sync_all', 'sync_openrouter', 'sync_artificial_analysis',
        'sync_models_dev', 'fill_nulls',
    }
    return any(arg in commands for arg in sys.argv[1:])


def _acquire_single_instance_lock() -> bool:
    """Guarantee only one process per container runs the scheduler.

    Gunicorn forks one process per worker and each calls ready(), so a
    naive start would run N copies of the 6-hourly sync. An exclusive,
    non-blocking file lock dedupes them: the first worker to grab it
    owns the scheduler, the rest return quietly. The lock is held for
    the process lifetime (the handle stays open) and released on exit.
    """
    global _lock_handle
    lock_path = os.environ.get('SCHEDULER_LOCK_FILE', '/tmp/rankllms-scheduler.lock')
    try:
        handle = open(lock_path, 'w')
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_handle = handle
        return True
    except OSError:
        return False


def _database_available() -> bool:
    """The scheduler must never hold a DB connection that blocks shutdown.

    A background thread mid-query keeps psycopg2's connection alive, and
    gunicorn's graceful timeout then escalates to SIGKILL. Check first,
    and let the job's own error handling deal with a dropped connection later.
    """
    try:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True
    except Exception as e:
        logger.warning("[APScheduler] Database not reachable, skipping sync (%s).", type(e).__name__)
        return False


def run_scheduled_sync():
    from llms.services.admin_sync import SyncAlreadyRunning, enqueue_sync

    if not _database_available():
        return

    try:
        logger.info("[APScheduler] Queueing scheduled master pipeline sync.")
        enqueue_sync(source='all')
    except SyncAlreadyRunning:
        logger.info("[APScheduler] A sync is already active; scheduled run was skipped.")
    except Exception as e:
        logger.error("[APScheduler] Could not queue scheduled sync (%s).", type(e).__name__)


def start_scheduler():
    """Start the 6-hourly catalog sync, if enabled and safe to do so.

    All gating lives here so callers (apps.ready) stay one line. Returns
    quietly when disabled, during management commands, or when another
    worker already owns the scheduler.
    """
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return
    if not is_enabled():
        return
    if _in_migrations_or_commands():
        return
    if not _acquire_single_instance_lock():
        logger.info("[APScheduler] Another worker already owns the scheduler; skipping.")
        return

    _scheduler = BackgroundScheduler(executors={'default': ThreadPoolExecutor(1)})

    _scheduler.add_job(
        run_scheduled_sync,
        trigger=IntervalTrigger(hours=int(os.environ.get('SYNC_INTERVAL_HOURS', '6'))),
        id='master_model_sync',
        name='Sync OpenRouter and Artificial Analysis LLM models catalog',
        # Don't pile up runs if a sync overruns its interval, and let a missed
        # or crashed job recover instead of killing the scheduler.
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
        replace_existing=True
    )
    _scheduler.start()
    logger.info(
        "Background scheduler started (pid=%s, interval_hours=%s).",
        os.getpid(), os.environ.get('SYNC_INTERVAL_HOURS', '6'),
    )
