from django.core.management.base import BaseCommand
from llms.services.openrouter_sync import sync_openrouter_models


class Command(BaseCommand):
    help = 'Fetches model catalog from OpenRouter API and syncs into Neon PostgreSQL database'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting OpenRouter data sync..."))
        try:
            summary = sync_openrouter_models()
            self.stdout.write(self.style.SUCCESS(
                f"Sync successful! Total: {summary['total_fetched']}, "
                f"Created: {summary['created']}, Updated: {summary['updated']}, "
                f"Providers: {summary['total_providers']}"
            ))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"OpenRouter Sync Failed: {e}"))
