from django.core.management.base import BaseCommand
from llms.services.artificial_analysis_sync import sync_artificial_analysis_data


class Command(BaseCommand):
    help = 'Fetches benchmark scores and model evaluations from Artificial Analysis Data API and enriches database models'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting Artificial Analysis benchmark sync..."))
        try:
            success = sync_artificial_analysis_data()
            if success:
                self.stdout.write(self.style.SUCCESS("Artificial Analysis Sync completed successfully!"))
            else:
                self.stdout.write(self.style.WARNING("Artificial Analysis Sync completed with warnings."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Artificial Analysis Sync Failed: {e}"))
