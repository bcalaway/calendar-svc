# calendar-svc

The market data platform's calendar service: it owns the **golden holiday calendars** (FED, SIFMA-US, NYSE to start) and answers "is this a business day?" for everything else, DAGs and services alike. It builds them from mkt-data's near-raw calendar rows, each source as it states itself, which it reads over gRPC (`mkt-data:9090`, `CalendarSources`). The plan and status live in mkt-data's [docs/phase-2.md](https://github.com/bcalaway/mkt-data/blob/main/docs/phase-2.md) (Part A).

It runs on the home platform's AWS hub (`bcalaway/nyc_pa_aws_gitops`) as a registry app (`apps/registry.yml`: own Postgres database, Airflow pipelines, no Authentik client, no previews). Started from `templates/python` there, whose README explains the template's pieces; [docs/app-platform.md](https://github.com/bcalaway/nyc_pa_aws_gitops/blob/main/docs/app-platform.md) is the platform contract.

## How it runs

- **Container:** one process with HTTP on 8000 and gRPC on 9090, internal only: no Traefik route and no DNS record. Other services reach it on the `home-platform` network as `calendar-svc:8000` / `calendar-svc:9090`.
- **Database:** `calendar-svc` on the hub's Postgres 16 (role, database and password created by the platform, `/home-platform/postgres/calendar-svc-password`). Schema changes are Alembic migrations, applied when the container starts.
- **CI/CD:** `ci.yml` runs the platform's `app-ci.yml` on every PR (`ci / Build, test, lint` is required on `main`). `cd.yml` builds and pushes to ECR on merge, then deploys once Bill approves the `production` environment. Docs-only merges don't deploy.
- **Secrets:** anything under `/home-platform/calendar-svc/` in SSM arrives in the container's environment at deploy time (the Airflow job token arrives as `AIRFLOW_TOKEN`).

## Conventions

As in mkt-data: hidden integer IDs internally and short readable names (`SIFMA-US`) in every view, log line and metric; processed tables always rebuildable from their inputs (here, mkt-data's near-raw rows).

## Local development

```
pip install -r requirements.txt -r requirements-dev.txt
./gen_proto.sh
uvicorn app.main:app --reload
```

`POSTGRES_PASSWORD` is optional locally; without it the app runs with no database.

Tests and lint: `pytest` and `ruff check app/ tests/ migrations/`, or `docker build --target test .` / `--target lint .`, which is what CI runs. Where PyPI is blocked, `scripts/sandbox-test.sh` runs everything but `tests/test_grpc.py`.
