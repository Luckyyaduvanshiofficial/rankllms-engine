import os
from django.apps import AppConfig


class LlmsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'llms'
    verbose_name = 'RankLLMs Model Catalog'

    def ready(self):
        # Start background scheduler if enabled and running server (not during migrations)
        if os.environ.get('RUN_MAIN') == 'true' or os.environ.get('ENABLE_SCHEDULER') == 'true':
            try:
                from .scheduler import start_scheduler
                start_scheduler()
            except Exception as e:
                print(f"[Scheduler] Failed to start background scheduler: {e}")
