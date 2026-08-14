from django.core.management.base import BaseCommand
from llms.services.fill_nulls import fill_all_nulls


class Command(BaseCommand):
    help = 'Intelligently backfills missing specs, pricing, and benchmark scores across all database models'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting database-wide null backfill..."))
        try:
            success = fill_all_nulls()
            if success:
                self.stdout.write(self.style.SUCCESS("Database Null Backfill completed successfully!"))
            else:
                self.stdout.write(self.style.WARNING("Database Null Backfill completed with warnings."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Null Backfill Failed: {e}"))
