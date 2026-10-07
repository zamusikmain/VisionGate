# GitHub publication and Render deployment

## Publication contract

Use a PRIVATE GitHub repository named VisionGate and branch main. No customer photographs belong in Git, including private repositories. Dataset and holdout retain only good/bad/.gitkeep. Raster photographs are ignored globally; demo photos must be generated locally. Runtime images/uploads, reports/debug exports, SQLite files, secrets/environment files, logs, caches, dependency folders, build output, archives and IDE/system files are excluded. .env.example intentionally has an empty ADMIN_TOKEN.

Before a commit run `python -m tools.release_check`. It inspects the Git index and rejects private paths, photos and symlinks even if force-added. It is a publication check, not an installed mandatory server policy: run it for future commits, alongside Gitleaks. Gitignore can always be bypassed with force-add; never do that for customer data. Secret scanning cannot prove absence of every possible credential.

GitHub CLI was not found during preparation. After installing it from the official GitHub CLI distribution, run in this workspace:

```powershell
winget install --id GitHub.cli --exact
# Reopen the terminal so gh is in PATH, then return to the VisionGate directory.
gh auth login --hostname github.com --git-protocol https --web
gh auth status
python -m tools.release_check
gh repo create VisionGate --private --source . --remote origin --push
git push -u origin main
gh repo view --json url,visibility,defaultBranchRef
git status --short
```

If VisionGate already exists, do not create a replacement or change its visibility blindly: inspect it with `gh repo view VisionGate --json url,visibility`, confirm PRIVATE, then use its actual returned URL as origin. No repository URL is assumed here.

## Single Render Web Service

Connect the private repository through Render's GitHub integration. Create a Web Service or a Blueprint from render.yaml. Select branch main, runtime Docker, root directory repository root, Dockerfile path ./Dockerfile.render, Docker build context . and plan Free for an evaluation pilot. No PostgreSQL or other external datastore is required.

Build command: leave blank (Docker multi-stage build performs npm ci, TypeScript/Vite build and Python dependency installation). Docker command/start override: leave blank; the image CMD runs /app/start.sh. Effective start:

```sh
uvicorn backend.render_app:create_app --factory --host 0.0.0.0 --port "$PORT" --workers 1 --limit-concurrency 16 --no-access-log
```

Render supplies PORT; the script uses it and defaults to 10000 for local image tests. Do not put a literal $PORT into an exec-form command override. Health check path: **/api/v1/health**, using the existing API. The container also checks that same path at its configured PORT. Frontend and API share the generated HTTPS URL; no frontend API URL or CORS change is needed. The existing local Compose remains a two-service deployment at localhost:8080.

| Environment | Render value |
|---|---|
| PORT | Supplied by Render; do not add manually |
| STORE_ANALYSIS_IMAGES | false |
| HISTORY_DB | /app/data/history.sqlite3 |
| GATE_CONFIG | /app/data/thresholds.json |
| MAX_CONCURRENT_ANALYSES | 1 (single worker, bounded memory pressure on Free) |
| ADMIN_TOKEN | Optional private random secret in dashboard only; omit to disable settings/history |

The Blueprint sets all non-secret values. No secrets are Docker build arguments. Upload/pixel limits, metrics, Decision Engine and shipped thresholds are unchanged. Runtime config defaults are identical to config/thresholds.json. Administrative changes and SQLite history are ephemeral on Free; a restart returns to shipped defaults. Keep the image-storage flag false. Images are read transiently for analysis; original retention is disabled. Logs must not include request bodies, image bytes or decoded inventory values; access logging is disabled for this packaging.

## Free limitations and security boundary

Render Free spins down after 15 idle minutes; waking can take about a minute. Local file changes, SQLite history and admin edits are lost on restart/redeploy/spin-down. Free does not provide a persistent disk and has monthly shared usage limits. It is an evaluation service, not durable submission storage. See [Render Free](https://render.com/docs/free).

One analysis slot reduces simultaneous native memory demand, but Free resources do not guarantee processing every 24 MP photo or meeting production latency/availability targets. Validate real images on the selected plan; do not alter thresholds to fit hosting. BUSY 503 is a technical retry, not RETAKE. There is no deployment-domain accuracy claim.

The existing analyze endpoint has no corporate authentication. A public Render URL therefore allows anyone to call it. Do not upload real customer data through it until the corporate access/privacy policy and authenticated gateway are in place. Admin endpoints remain protected/disabled independently. A private GitHub repository does not make the Render URL private.

Official configuration references: [Docker](https://render.com/docs/docker), [Web Services](https://render.com/docs/web-services), [health checks](https://render.com/docs/health-checks), [Blueprint schema](https://render.com/docs/blueprint-spec).

## Local production-image verification

```powershell
docker build -f Dockerfile.render -t visiongate-render:verify .
docker run --rm -e PORT=12345 -p 127.0.0.1:18080:12345 visiongate-render:verify
```

Check localhost:18080/, /api/v1/health, /docs and /openapi.json. Runtime files must return 404. Full test/build/security results are in docs/verification.md.
