import os

from django.apps import AppConfig


class LlmsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'llms'
    verbose_name = 'RankLLMs Model Catalog'

    def ready(self):
        # Start the 6-hourly catalog sync. All gating (the ENABLE_SCHEDULER
        # opt-in, the management-command check, and the single-instance lock
        # that keeps gunicorn from running one scheduler per worker) lives in
        # scheduler.start_scheduler(), so this stays a one-line call.
        try:
            from .scheduler import start_scheduler
            start_scheduler()
        except Exception as e:  # never let a scheduler failure block startup
            print(f"[Scheduler] Failed to start background scheduler: {e}")
