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

**Caveat — empty dashboard from CI:** GitHub Actions builds from the committed repo, which by design has **no demo data** (`ema_demo.sqlite` is gitignored). A CI deploy ships a working, auth-gated app with an **empty dashboard** until a monitoring run populates it. To deploy *with* the baked demo snapshot, run `fly deploy` locally (steps above) — that uses your working directory as the build context. The two paths don't conflict; the most recent deploy wins.

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
