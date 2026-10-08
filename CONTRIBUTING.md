# Contributing

Thanks for improving RankLLMs Engine. Keep changes focused, preserve existing API URLs where possible, and treat upstream data as untrusted input.

## Local setup

```bash
git clone https://github.com/Luckyyaduvanshiofficial/rankllms-engine.git
cd rankllms-engine
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

Local development can use SQLite by leaving `DATABASE_URL` empty. Keep real source keys in the local `.env` or a deployment secret store; never commit them.

## Before opening a pull request

Run the isolated checks:

```bash
DJANGO_SETTINGS_MODULE=config.test_settings python manage.py check
DJANGO_SETTINGS_MODULE=config.test_settings python manage.py makemigrations --check --dry-run
DJANGO_SETTINGS_MODULE=config.test_settings python manage.py test
```

If you change models, add an additive migration and test it against the isolated SQLite settings. Do not apply destructive schema/data changes to a production database without a verified backup and recovery plan.

## Adding or changing a source

1. Put network access in a source service, never in a template or public request handler.
2. Use `llms.services.source_http.fetch_json()` for HTTPS host validation, bounded timeouts, retries, 429 handling, and secret-safe errors.
3. Validate response envelopes before any database write. Preserve the previous snapshot if the payload is malformed or unexpectedly empty.
4. Keep source IDs and original payloads. Match with explicit IDs and provider-scoped aliases; do not merge by display-name similarity alone.
5. Preserve unknown fields as `null`. Do not infer benchmark scores, prices, licenses, context windows, or open-weight status.
6. Add or update parser, merge, and dry-run tests, then update source attribution in the docs.

## Data attribution

- Cite OpenRouter when republishing its Data API datasets; those datasets are licensed under CC BY 4.0.
- Attribute Artificial Analysis scores to Artificial Analysis and do not describe them as RankLLMs-run evaluations.
- Preserve models.dev model/provider IDs and license information where present.
