from django.core.management.base import BaseCommand, CommandError
from llms.services.sync_all import run_master_sync


class Command(BaseCommand):
    help = 'Fetches model catalog from OpenRouter API and syncs into Neon PostgreSQL database'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting OpenRouter data sync..."))
        try:
            summary = run_master_sync(sources=['openrouter'])
            if summary['status'] != 'succeeded':
                raise CommandError('OpenRouter sync was partial or failed; inspect the source summary.')
            self.stdout.write(self.style.SUCCESS(
                f"OpenRouter sync successful. Records received: {summary['records_received']}, "
                f"added: {summary['records_added']}, updated: {summary['records_updated']}"
            ))
        except CommandError:
            raise
        except Exception as e:
            raise CommandError(f"OpenRouter sync failed ({type(e).__name__}).") from e
