from django.core.management.base import BaseCommand
from llms.services.sync_all import run_master_sync


class Command(BaseCommand):
    help = (
        'Executes complete end-to-end data pipeline: OpenRouter Ingestion -> '
        'models.dev Catalog -> Artificial Analysis -> Dedicated Raw Tables -> '
        'Null Backfill -> Merge into rankindex'
    )

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting Master Pipeline Sync..."))
        try:
            report = run_master_sync()
            self.stdout.write(self.style.SUCCESS(
                f"Master Pipeline Sync Completed in {report['elapsed_seconds']}s! "
                f"Total Models: {report['total_models']}, Providers: {report['total_providers']}, "
                f"Benchmarks: {report['total_benchmarks']}, RankIndex: {report.get('total_rankindex', 0)}"
            ))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Master Pipeline Sync Failed: {e}"))
