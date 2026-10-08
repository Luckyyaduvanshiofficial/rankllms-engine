from django.core.management.base import BaseCommand
from llms.services.fill_nulls import fill_all_nulls


class Command(BaseCommand):
    help = 'Report missing catalog values without inventing data'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting database-wide null backfill..."))
        try:
            summary = fill_all_nulls()
            self.stdout.write(self.style.WARNING(
                'No values were inferred. Missing rows: '
                f"specifications={summary['missing_specifications']}, "
                f"pricing={summary['missing_pricing_rows']}, "
                f"benchmarks={summary['missing_benchmark_rows']}."
            ))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Null Backfill Failed: {e}"))
