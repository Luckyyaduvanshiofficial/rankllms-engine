from django.core.management.base import BaseCommand, CommandError

from llms.services.sync_all import run_master_sync


class Command(BaseCommand):
    help = 'Sync the free models.dev provider/model catalog into the modelsdev table.'

    def handle(self, *args, **options):
        summary = run_master_sync(sources=['models_dev'])
        if summary['status'] != 'succeeded':
            raise CommandError('models.dev sync was partial or failed; inspect the source summary.')
        source = summary['sources'][0].get('summary', {})
        self.stdout.write(self.style.SUCCESS(
            f"models.dev sync complete: {source.get('created', 0)} created, "
            f"{source.get('updated', 0)} updated."
        ))
