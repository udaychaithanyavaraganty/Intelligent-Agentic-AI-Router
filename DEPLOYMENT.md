# Deployment Guide

## Status and scope

This repository is prepared for a **single-instance Render web service** using Gunicorn and a mounted persistent disk. No deployment has been created or tested, and no public URL is claimed. Do not deploy or push until the project owner confirms the target repository and hosting account.

The deployment uses demo classification by default. Gemini is optional and must be explicitly configured with a secret environment variable. The registered workflows remain response-only demonstration handlers after deployment; they do not carry out real account, data, or automation actions.

## Included deployment configuration

[`render.yaml`](render.yaml) declares:

- Python 3.12.8 runtime;
- installation from the production-only `requirements.txt`;
- Gunicorn WSGI start command bound to the platform's `$PORT`;
- one worker process with four request threads, suitable for the single mounted SQLite volume and the current small demo;
- `/api/health` as the health-check path;
- automatic deploys disabled, so linked Git commits do not deploy without a manual platform action;
- a 1 GB persistent disk mounted at `/var/data`;
- operational and evaluation SQLite paths under that mount;
- demo provider, debug disabled, and default threshold/timeout values.

The configuration requests Render's `starter` plan because persistent disks are not available on every free hosting tier. Confirm current Render prices and plan requirements in your account before applying the Blueprint. The deployment has not been applied.

## Deploy through Render Blueprint

1. Review the source and verify `.env`, key files, database files, and local caches are ignored. Do not upload `.env` or paste a key into YAML, source, GitHub, or this chat.
2. Push the reviewed source to a GitHub repository only after explicitly confirming the repository and push.
3. In Render, create a Blueprint from that repository and review the resources, plan, persistent disk, and environment values before approving creation. Creating a Blueprint may provision and start the initial service deployment even though automatic subsequent deploys are disabled; approve only after the project owner confirms deployment.
4. Keep `LLM_PROVIDER=demo` for the first deployment. No Gemini credential is needed in this mode.
5. Wait for the build and service deployment to finish. Render's deployment log should show the Gunicorn process starting; a successful build alone does not establish application health.
6. Copy the generated HTTPS service URL and run the verification checklist below. This assistant has not performed these steps or tested a live URL.

### Optional Gemini configuration

Only when the project owner intends to use the real classifier:

1. Open the Render service's Environment settings.
2. Add `GEMINI_API_KEY` as a secret environment variable using the provider's dashboard. Never commit it, put it in `render.yaml`, or expose it in browser code.
3. Set `LLM_PROVIDER=gemini` and redeploy.
4. Confirm `/api/health` reports `"provider":"gemini"` and `"mode":"real"` but does not return the key. Submit a non-sensitive test request and verify the resulting trace.
5. Monitor provider usage and billing. The model can classify only; routes and handlers remain application-controlled.

Missing credentials in Gemini mode prevent startup. The application does not silently fall back to demo mode. No live Gemini integration was tested as part of this preparation.

## Environment variables

| Variable | Required/default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `demo` | Choose `demo` or `gemini` |
| `GEMINI_API_KEY` | Required only for Gemini; secret | Gemini Developer API credential |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Gemini model identifier |
| `LLM_TIMEOUT` | `20` seconds | Provider timeout |
| `CONFIDENCE_THRESHOLD` | `0.65` | Minimum auto-route confidence |
| `DATABASE_PATH` | Local default; Render: `/var/data/router.sqlite3` | Operational history database file |
| `EVALUATION_DATABASE` | Local default; Render: `/var/data/evaluation_results.sqlite3` | Separate benchmark database file |
| `FLASK_DEBUG` | `0` in deployment | Development server debug switch; Gunicorn is the production server |
| `PORT` | Platform assigned | HTTP listener port; passed to Gunicorn by Render |

`.env.example` contains non-secret local defaults. `.env` and `.env.*` are ignored, with `.env.example` explicitly allowed. On Render, set secrets in the platform's secret environment configuration.

## Database persistence and scaling

Render's mounted disk provides persistence across deploys for a single service instance, subject to the platform's current disk behavior, account plan, region, and configuration. Render documents that a disk is accessible to only one service instance, prevents scaling the service to multiple instances, and prevents zero-downtime deploys. Confirm disk attachment and backups in the hosting account. Both SQLite files must remain under `/var/data`; do not store live data in the ephemeral application filesystem.

This app uses SQLite and does not include a PostgreSQL adapter. The mounted single-instance deployment is intended for a low-volume demonstration. Do not add multiple replicas or multiple independent instances sharing an unsupported filesystem. SQLite locking, backup, disk capacity, and recovery need operational monitoring. Render's persistent-disk snapshots and restore behavior are controlled by the platform; verify the current retention and recovery policy rather than treating a volume as a complete backup plan.

For a multi-instance or higher-write-volume deployment, provision a managed PostgreSQL database and implement/test a PostgreSQL-backed persistence adapter and schema migration strategy first. Setting a PostgreSQL URL alone will **not** make this SQLite application use Postgres.

## Frontend, backend, and health check

The Flask process serves `frontend/index.html` and assets from the same origin as the JSON endpoints. No separate frontend host or CORS configuration is needed for this deployment. The dashboard calls relative `/api/...` paths.

`GET /api/health` checks that the operational and evaluation SQLite stores can be opened and queried. On success it returns HTTP 200 and a small JSON status including provider mode and `"storage":"ok"`. A storage SQLite error is logged and returns HTTP 503 with `"storage":"unavailable"`. The endpoint does not make a Gemini request and therefore is not a provider availability test.

Gunicorn access and error logs are directed to stdout/stderr for the platform log viewer. Application exceptions use Flask logging. Client responses sanitize provider/processing errors; avoid adding request text, keys, or other sensitive values to production logs.

## Post-deployment verification checklist

After you have a live service URL:

1. `GET https://<service-host>/api/health` — expect HTTP 200, `"status":"ok"`, and `"storage":"ok"`.
2. Open `https://<service-host>/` — verify the dashboard HTML and static CSS/JS load.
3. `GET /api/dashboard` and `GET /api/analytics` — verify valid JSON and explicit empty-state values for a new database.
4. Submit a benign known-category request, such as “What is a REST API?” — expect a supported label, canonical `general_information` workflow, completed response, and actual agent trace.
5. Submit an ambiguous request — expect pending review, no execution agent event, then test reject/clarify. Approve only a known supported request that the validator has explicitly put in review.
6. Verify `GET /api/requests/<id>/trace` reflects persisted events. Redeploy, then confirm a prior record remains; this tests volume persistence rather than merely trusting configuration.
7. If Gemini was explicitly configured, verify provider mode and run a non-sensitive request while checking provider billing/usage. Do not claim real LLM integration from a demo-mode health response.
8. Check Render logs for startup errors and review the hosting account's disk, backup, and restart behavior.

No live deployment or URL has been tested by this documentation change.

The project has not been deployed and no public service URL is available, so frontend access, live database persistence, and real-provider classification remain unverified outside the local test client.

## Linux/macOS/WSL production-server smoke test

Gunicorn is a Unix WSGI server; the following is for Linux, macOS, or WSL, not native Windows PowerShell. After installing runtime dependencies:

```sh
python -m pip install -r requirements.txt
gunicorn backend.app:app --bind 127.0.0.1:8000 --workers 1 --threads 4 --timeout 120
```

In another terminal:

```sh
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://127.0.0.1:8000/
```

This local check validates the WSGI start path only; it is not a substitute for testing the hosted service and mounted disk.

## Platform references

- [Render Blueprint specification](https://render.com/docs/blueprint-spec)
- [Render persistent disks](https://render.com/docs/disks)
- [Render managed PostgreSQL](https://render.com/docs/postgresql)
