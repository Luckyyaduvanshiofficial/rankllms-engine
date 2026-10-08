# Static model-card exports

`top_200_models.json` and `top_200_models.ts` are legacy snapshots kept for downstream compatibility. They are not built during sync, are not consumed by the Django API or current web UI, and may contain stale values or placeholder fields. Do not treat them as the live catalog or a source of benchmark truth.

Use the live canonical snapshot instead:

- `GET /api/v1/rankindex` for paginated canonical records
- `GET /api/v1/leaderboard/rankindex` for the published RankLLMs ordering
- `GET /api/v1/models/cards` for a live model-card response

The staff page at `/settings/data-sync/` shows when the current database snapshot was last refreshed.
