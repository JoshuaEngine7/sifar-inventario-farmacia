# Deploying the live demo to Azure App Service (free tier)

The demo runs at **$0** on App Service's F1 (Free) Linux tier. The database is
seeded with demo data on every restart, so the public demo periodically resets
itself — by design.

Why `SIFAR_DB=/tmp/farmacia.db`: on App Service, the app directory lives on a
network file share (CIFS), where SQLite's WAL locking is unreliable. `/tmp` is
local disk — safe for WAL, wiped on restart, which doubles as the demo reset.

## Option A — Azure CLI

```bash
az login
cd sifar-inventario-farmacia
az webapp up --name <globally-unique-name> --runtime PYTHON:3.12 --sku F1 --os-type Linux
az webapp config appsettings set --name <name> --resource-group <rg-created-above> \
    --settings SIFAR_DB=/tmp/farmacia.db SCM_DO_BUILD_DURING_DEPLOYMENT=true
az webapp config set --name <name> --resource-group <rg-created-above> --startup-file \
    "rm -f /tmp/farmacia.db*; python -m app.demo_data; python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
```

## Option B — Azure Portal (no CLI)

1. Create resource → **Web App**: Publish *Code*, runtime *Python 3.12*, OS *Linux*,
   plan *Free F1*.
2. **Deployment Center** → Source *GitHub* → authorize → pick this repo, branch
   `main`. Azure adds a GitHub Actions workflow that deploys on every push.
3. **Configuration → Application settings**: add `SIFAR_DB` = `/tmp/farmacia.db`.
4. **Configuration → General settings → Startup Command**:
   `rm -f /tmp/farmacia.db*; python -m app.demo_data; python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
5. Restart the app. First load is slow (free tier cold start); log in with
   `Admin Demo` / `demo1234`.

## Free-tier caveats

- F1 gives 60 CPU-minutes/day and sleeps when idle: the first request after a
  quiet period takes ~30-60 s. Fine for a portfolio demo.
- Anyone can log in and change the demo passwords; a restart re-seeds everything.
