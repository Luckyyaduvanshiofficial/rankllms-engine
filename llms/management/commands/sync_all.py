from django.core.management.base import BaseCommand
from llms.services.sync_all import run_master_sync


class Command(BaseCommand):
    help = 'Executes complete end-to-end data pipeline: OpenRouter Ingestion -> Artificial Analysis Benchmark & Media Sync -> Null Backfill'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting Master Pipeline Sync..."))
        try:
            report = run_master_sync()
            self.stdout.write(self.style.SUCCESS(
                f"Master Pipeline Sync Completed in {report['elapsed_seconds']}s! "
                f"Total Models: {report['total_models']}, Providers: {report['total_providers']}, Benchmarks: {report['total_benchmarks']}"
            ))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Master Pipeline Sync Failed: {e}"))
