# Security policy

## Reporting a vulnerability

Please do not publish secrets, exploit details, or an unpatched vulnerability in a public issue. Contact the maintainers through the private security contact listed on the repository's GitHub Security page. Include the affected version/commit, impact, and a minimal reproduction where possible.

## Deployment expectations

- Keep `SECRET_KEY`, `ARTIFICIAL_ANALYSIS_API_KEY`, `OPENROUTER_API_KEY`, and `DATABASE_URL` in Render environment secrets or another server-side secret store. Never add them to source control or browser code.
- Keep `DEBUG=False` and set explicit `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, and `CSRF_TRUSTED_ORIGINS` in production.
- `/settings/data-sync/`, source settings, API key administration, and `POST /api/v1/sync` require an authenticated Django staff account.
- The public read API does not require a RankLLMs API key. The optional key registry is staff-only; it does not currently enforce request quotas.
- Generated registry keys are currently stored as plaintext and are not used to authenticate or rate-limit API requests. Treat them as staff-only metadata; do not distribute them as working credentials.
- Rotate any source key or Django secret that may have been exposed. `.env` is git-ignored; verify that local secrets are not staged before committing.
