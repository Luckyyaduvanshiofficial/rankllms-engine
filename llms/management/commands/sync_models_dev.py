from django.core.management.base import BaseCommand

from llms.services.models_dev_sync import sync_models_dev_catalog


class Command(BaseCommand):
    help = 'Sync the free models.dev provider/model catalog into the modelsdev table.'

    def handle(self, *args, **options):
        summary = sync_models_dev_catalog()
        if summary.get('error'):
            self.stderr.write(self.style.ERROR(f"models.dev sync failed: {summary['error']}"))
            return
        self.stdout.write(self.style.SUCCESS(
            f"models.dev sync complete: {summary['created']} created, "
            f"{summary['updated']} updated, {summary['providers']} providers."
        ))
