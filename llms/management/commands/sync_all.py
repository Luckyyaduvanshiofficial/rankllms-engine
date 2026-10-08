from django.core.management.base import BaseCommand, CommandError
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
            if report['status'] != 'succeeded':
                raise CommandError(f"Master sync {report['status']}; inspect source results in the report.")
            self.stdout.write(self.style.SUCCESS(
                f"Master Pipeline Sync Completed in {report['elapsed_seconds']}s! "
                f"Total Models: {report['total_models']}, Providers: {report['total_providers']}, "
                f"Benchmarks: {report['total_benchmarks']}, RankIndex: {report.get('total_rankindex', 0)}"
            ))
        except CommandError:
            raise
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Master Pipeline Sync Failed ({type(e).__name__})."))
            raise CommandError('Master pipeline sync failed.') from e
