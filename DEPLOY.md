# Deploying EMA POC to Fly.io

## Prerequisites

- A [Fly.io](https://fly.io) account
- `flyctl` installed: `brew install flyctl` or via the [curl installer](https://fly.io/docs/hands-on/install-flyctl/)
- Authenticated: `fly auth login`
- **Local working directory with `ema_demo.sqlite` present** — the demo data is baked into the Docker image at build time. It is gitignored and not committed. A fresh `git clone` would NOT have the demo data (the dashboard would start empty there, by design).

## Deployment Steps

### 1. Create the Fly app

Either use `fly launch` (which reads `fly.toml`) or create the app manually:

```bash
# Option A: guided launch (no deploy yet)
fly launch --no-deploy --copy-config --name <your-unique-app-name>

# Option B: manual
# Edit the `app` field in fly.toml, then:
fly apps create <your-unique-app-name>
```

Choose a region (default in `fly.toml` is `iad` — US East).

### 2. Set secrets

**Never commit these values.** Set them as Fly secrets:

```bash
fly secrets set \
  OPENAI_API_KEY=sk-... \
  ANTHROPIC_API_KEY=sk-ant-... \
  GOOGLE_API_KEY=... \
  APP_PASSWORD='<choose-a-strong-password>'
```

- `APP_USER` defaults to `abbvie` via `fly.toml [env]`. To override: `fly secrets set APP_USER=...`
- The playground uses Basic Auth: username = `APP_USER`, password = `APP_PASSWORD`.

### 3. Deploy

Run from the local working directory that contains `ema_demo.sqlite`:

```bash
fly deploy
```

This builds the Docker image from the local directory, baking in `ema_demo.sqlite` and `config_deploy/`.

### 4. Open the app

```bash
fly open
```

Share the HTTPS URL and `APP_PASSWORD` with the product owner. Login: user `abbvie`, password as set above.

## Persistent data volume (seed once, survives every redeploy)

The dashboard data lives in `ema_demo.sqlite`. The repo is code-only (the DB is
gitignored), so a CI build ships an **empty** DB. To give the product owner a populated
dashboard that **persists across redeploys**, the app mounts a Fly volume at `/app/data`
(see `[mounts]` in `fly.toml`) and auto-seeds it on first boot.

How the seed works: the demo snapshot is baked into the image at `/app/seed/ema_demo.sqlite`
(only when `fly deploy` runs locally, where `ema_demo.sqlite` is in the build context).
On boot, `docker-entrypoint.sh` copies it onto the volume **only if the volume has no DB
yet**. Once seeded, the data is on the volume and every later deploy — CI or local —
leaves it untouched.

One-time setup (needs `flyctl`):

```bash
brew install flyctl && fly auth login

# 1. Single machine (one volume = one machine)
fly scale count 1 --app ema-poc --yes

# 2. Create the persistent volume (1 GB, same region as the app)
fly volumes create ema_data --size 1 --region iad --app ema-poc --yes

# 3. Deploy from THIS directory so the image carries ema_demo.sqlite as the seed.
#    The entrypoint copies it onto the empty volume on first boot.
fly deploy

# 4. Confirm
fly logs --app ema-poc        # look for: [entrypoint] seeding /app/data/ema_demo.sqlite
fly open                      # dashboard now shows the demo data
```

After this, pushing to `main` (GitHub Actions) redeploys the code and the **volume data
persists** — the empty-CI-image caveat no longer applies once the volume is seeded.

To re-seed with fresh data later: build a new local `ema_demo.sqlite`, then
`fly ssh console --app ema-poc -C 'rm -f /app/data/ema_demo.sqlite'` and `fly deploy`
(the next boot re-seeds from the baked snapshot).

## Verifying the Deployment

Visiting the URL should prompt for username and password. After login, the unified app loads with **Playground** and **Dashboard** tabs.

## Operating Notes

### Cost guard
The playground makes real LLM API calls. Per-IP rate limiting is applied via `PLAYGROUND_MAX_QUERIES_PER_HOUR` (default: 60). To change:
```bash
fly secrets set PLAYGROUND_MAX_QUERIES_PER_HOUR=30
# or edit fly.toml [env] and redeploy
```
Auth limits spend to whoever holds the password, and the per-IP hourly cap (PLAYGROUND_MAX_QUERIES_PER_HOUR) bounds runaway usage.

`PLAYGROUND_MAX_CONCURRENT_JOBS` (default 2) bounds how many background questions run at once.

### Compliance
- Third-party host with AbbVie **DEMO data only** — no PII/PHI, not production secrets (SE-004).
- The demo data resets to the baked snapshot on each redeploy (no persistent volume by default).

### Pausing to stop spend
```bash
fly scale count 0          # manual pause
# or it auto-stops when idle (auto_stop_machines = "stop" in fly.toml)
```

### Tear down
```bash
fly apps destroy <your-app-name>
```

## Auto-Deploy via GitHub Actions

A workflow at `.github/workflows/fly-deploy.yml` redeploys to Fly.io on every push to `main` (and on-demand via the Actions tab → "Deploy to Fly.io" → Run workflow).

**One-time setup:**

1. Create a deploy token (scoped to this app, not your full account):
   ```bash
   fly tokens create deploy
   ```
2. In GitHub: **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `FLY_API_TOKEN`
   - Value: the token printed above (including the `FlyV1 ...` prefix)

After that, `git push origin main` triggers a deploy automatically.

**Data and CI:** Once the persistent volume is seeded (see "Persistent data volume" above), GitHub Actions deploys redeploy the **code** and the volume data **persists** — the dashboard stays populated. Before the volume is seeded, a CI deploy ships an empty dashboard (the repo is code-only; `ema_demo.sqlite` is gitignored). The seed step is a one-time local `fly deploy`; after that, auto-deploy is safe and non-destructive.

### Optional local Docker smoke test

Before deploying, verify the image locally (requires Docker):

```bash
docker build -t ema .
docker run -p 8080:8080 \
  -e APP_PASSWORD=test \
  -e OPENAI_API_KEY=... \
  -e ANTHROPIC_API_KEY=... \
  -e GOOGLE_API_KEY=... \
  ema
```

Open http://localhost:8080 — login with user `abbvie`, password `test`.
