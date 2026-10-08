from django.core.management.base import BaseCommand, CommandError
from llms.services.sync_all import run_master_sync


class Command(BaseCommand):
    help = 'Fetches benchmark scores and model evaluations from Artificial Analysis Data API and enriches database models'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting Artificial Analysis benchmark sync..."))
        try:
            report = run_master_sync(sources=['artificial_analysis'])
            if report['status'] != 'succeeded':
                raise CommandError('Artificial Analysis sync was partial or failed; inspect the source summary.')
            self.stdout.write(self.style.SUCCESS(
                f"Artificial Analysis sync complete: {report['records_received']} records received."
            ))
        except CommandError:
            raise
        except Exception as e:
            raise CommandError(f"Artificial Analysis sync failed ({type(e).__name__}).") from e
