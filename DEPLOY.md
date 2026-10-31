# Deploying PayPilot

Three paths. All of them need one thing you must supply yourself: a
`SARVAM_API_KEY` (or leave it blank and the offline rule agent runs).

Never commit the key. Every config below reads it from the platform's
environment variables.

---

## 1. Fastest demo link — the static preview (30 seconds, free)

`PayPilot_Preview.html` is a single self-contained file. Host it anywhere:

- **Netlify Drop** — <https://app.netlify.com/drop>, drag the file in, get a URL
- **GitHub Pages** — commit it as `index.html` in a repo, enable Pages
- **Cloudflare Pages** — drag and drop, same idea

It's a recording of a real session, so chips work and free text does not.
Good for a link in a submission form; not the app.

---

## 2. Render (easiest real deployment)

1. Push this folder to a GitHub repo.
2. Render → **New → Blueprint** → pick the repo. It reads `render.yaml`.
3. When prompted, set `SARVAM_API_KEY` (mark it secret).
4. Deploy. Health check is `/api/health`.

Free tier has an **ephemeral filesystem**: the SQLite file resets on every
deploy and after long idle. Fine for a demo. For persistence, attach a disk
(paid) and point `DATABASE_PATH` at the mount.

---

## 3. Fly.io

```bash
fly launch --no-deploy --copy-config      # uses fly.toml
fly volumes create paypilot_data --size 1 # persistent /data
fly secrets set SARVAM_API_KEY=sk_...
fly deploy
```

The volume is already mounted at `/data` in `fly.toml`, and `DATABASE_PATH`
points there, so sessions survive a restart.

---

## 4. Railway

```bash
railway init
railway variables set SARVAM_API_KEY=sk_...
railway up
```

Railway detects the `Dockerfile` and the `Procfile`. Set `DATABASE_PATH` to a
mounted volume if you want persistence.

---

## Anywhere else (VPS)

```bash
git clone <your repo> && cd paypilot-backend
docker compose up -d --build
```

Then put nginx or Caddy in front for TLS:

```
paypilot.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

---

## After deploying — a 30-second check

```bash
curl https://your-host/api/health
# {"status":"ok","llm":{"mode":"offline-rule-agent"|"llm+nlu", ...}}

curl -X POST https://your-host/api/sessions -H 'Content-Type: application/json' -d '{"language":"en"}'
```

If `mode` says `offline-rule-agent`, the key is not reaching the container —
check the env var on the platform, not the code.
