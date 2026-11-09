# Deployment guide

## Render production configuration

The repository's `render.yaml` defines a single-instance Python web service. It installs the production dependencies from `requirements.txt`, runs the Flask WSGI application with Gunicorn on Render's assigned `$PORT`, checks `/api/health`, and mounts a 1 GB persistent disk at `/var/data`. Both SQLite files are configured under that mount (`/var/data/router.sqlite3` and `/var/data/evaluation_results.sqlite3`). Keep the service to one instance; SQLite on a mounted disk is not a multi-instance database.

The Flask app creates the parent directories for both configured database paths before initializing the stores. `FLASK_DEBUG=0` is set in the Blueprint; Gunicorn imports `backend.app:app` and does not start Flask's development server. The direct `python -m backend.app` development entry point binds to `0.0.0.0` and only enables debug when `FLASK_DEBUG=1` is explicitly supplied.

### Render environment settings

The Blueprint configures these non-secret values:

- `LLM_PROVIDER=demo` (default; no API credential required)
- `FLASK_DEBUG=0`
- `DATABASE_PATH=/var/data/router.sqlite3`
- `EVALUATION_DATABASE=/var/data/evaluation_results.sqlite3`
- `CONFIDENCE_THRESHOLD=0.65`
- `LLM_TIMEOUT=20`
- `GEMINI_MODEL=gemini-3.8-flash`

Render provides `PORT`; do not set a fixed port. If you choose Gemini mode, set `LLM_PROVIDER=gemini` and add `GEMINI_API_KEY` as a secret in Render's Environment settings. Never commit the key or put it in `render.yaml`. No database URL is needed; this app currently uses SQLite, not PostgreSQL.

### Local production-start smoke test (Linux/macOS/WSL)

Install runtime requirements, start Gunicorn with the same WSGI target, bind address, and worker/thread settings as Render (using a local test port), then query health and the frontend:

```sh
python -m pip install -r requirements.txt
FLASK_DEBUG=0 DATABASE_PATH=/tmp/router-smoke/router.sqlite3 EVALUATION_DATABASE=/tmp/router-smoke/evaluation.sqlite3 gunicorn backend.app:app --bind 0.0.0.0:8000 --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile -
```

In another terminal:

```sh
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://127.0.0.1:8000/
```

A successful local smoke test does not prove that the Render disk is attached. After deployment, verify `https://<your-service>.onrender.com/api/health` returns HTTP 200 and that request history remains after a redeploy.

## Push the reviewed changes

From the local clone, check out the deployment branch, review the diff, then push it:

```sh
git fetch origin
git switch copilot/render-production-readiness
git pull --ff-only origin copilot/render-production-readiness
git diff --check
git status --short
git diff --stat
git push -u origin copilot/render-production-readiness
```

Then open a pull request from `copilot/render-production-readiness` into `main` and merge it after review. Do not push secrets, `.env` files, or SQLite database files.
