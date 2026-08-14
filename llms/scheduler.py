import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler = None


def run_scheduled_sync():
    from llms.services.sync_all import run_master_sync
    try:
        logger.info("[APScheduler] Triggering periodic master pipeline sync...")
        run_master_sync()
    except Exception as e:
        logger.error(f"[APScheduler] Periodic sync error: {e}")


def start_scheduler():
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return

    _scheduler = BackgroundScheduler()
    # Run sync every 6 hours
    _scheduler.add_job(
        run_scheduled_sync,
        trigger=IntervalTrigger(hours=6),
        id='master_model_sync',
        name='Sync OpenRouter and Artificial Analysis LLM models catalog',
        replace_existing=True
    )
    _scheduler.start()
    print("[APScheduler] Background scheduler started: Master model sync set for every 6 hours.")

