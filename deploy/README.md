# Munsiji — Apne VPS pe chalao (Self-host guide)

Repo: `https://github.com/iamsjtitu/munsiji` · Domain: `munsiji.app` · Alerts: `admin@munsiji.com`

Poora stack ek command se: **MongoDB + FastAPI backend + Web app + HTTPS (Caddy)**, GitHub se **one-tap update** (app Settings / home update bar), optional **auto-update**, aur owner ko **email alerts**.

## 1. Pehle ye 3 kaam
1. **DNS**: `munsiji.app` ka **A record → aapke VPS ka IP** (abhi 91.195.240.94 parking pe hai — badalna hai). `www` chahiye to CNAME → munsiji.app.
2. **Email inbox**: `admin@munsiji.com` pe mail tabhi aayegi jab domain pe **MX records** honge (abhi nahi hain). Options: Cloudflare Email Routing (free, Gmail pe forward), Zoho Mail (free), Google Workspace. Tab tak Settings mein apna Gmail daal sakte ho.
3. **GitHub**: Emergent mein **Save to GitHub** (repo `iamsjtitu/munsiji`). Repo private hai to niche wala private flow use karo.

## 2. Requirements
| Cheez | Detail |
|---|---|
| VPS | Ubuntu 22.04 / 24.04 (ya Debian 12), **2 GB RAM+** (script 3 GB swap add karta hai), 20 GB disk |
| Ports | 80 aur 443 open |
| Keys | Emergent LLM key (AI parsing) + Emergent Email key (alerts) — Emergent Profile → Universal Key / app ke backend `.env` se copy |

## 3. Ek command (VPS pe root/sudo se)

**Public repo:**
```bash
curl -fsSL https://raw.githubusercontent.com/iamsjtitu/munsiji/main/deploy/install.sh | sudo bash -s -- \
  --repo https://github.com/iamsjtitu/munsiji.git \
  --domain munsiji.app --email admin@munsiji.com \
  --owner 917205930002 --pin 3366 \
  --llm-key sk-emergent-xxxx --email-key ek_xxxx
```

**Private repo** (GitHub → Settings → Developer settings → Fine-grained token, repo *Contents: read*):
```bash
sudo git clone https://<TOKEN>@github.com/iamsjtitu/munsiji.git /opt/munsiji
sudo bash /opt/munsiji/deploy/install.sh \
  --repo https://<TOKEN>@github.com/iamsjtitu/munsiji.git \
  --domain munsiji.app --email admin@munsiji.com \
  --owner 917205930002 --pin 3366 \
  --llm-key sk-emergent-xxxx --email-key ek_xxxx
```
(token remote URL mein reh jaata hai — updates isi se fetch honge)

Bina domain test karna ho: `--domain` / `--email` hata do → `http://<VPS-IP>`.

Script: Docker install → swap → clone `/opt/munsiji` → `.env` (random JWT secret) → Caddy HTTPS → systemd updater → `docker compose build && up -d`. 5–10 min. End mein **app URL, PIN, WhatsApp webhook URL** print hota hai.

## 4. Install ke baad (app Settings = admin panel)
1. `https://munsiji.app` → PIN `3366` se login.
2. **Emergent Keys**: LLM key / Email key yahan se bhi badal sakte ho (`.env` ke upar priority).
3. **Email Alerts**: owner email (`admin@munsiji.com`), on/off switch, **Test email bhejo**. Alerts: galat PIN ×5 (lock), wa.9x reply fail, AI parsing fail, server update fail. Max 1 / 30 min per type.
4. **WhatsApp (wa.9x)**: Base URL + API key daalo, provider **wa.9x live**, Save. wa.9x dashboard mein webhook: `https://munsiji.app/api/whatsapp/webhook`
5. Phone app ko VPS se connect: PIN screen ke upar-right **server icon** → `https://munsiji.app` → Save.

## 5. Update flow (Emergent → GitHub → VPS)
1. Emergent mein changes → **Save to GitHub**.
2. App home pe **"Naya update available" bar** → **Update karo**, ya Settings → Server & Updates → **Update now**. Progress dikhta hai; web app khud reload.
3. **Auto-update** switch on → har 15 min GitHub check, naya commit khud install.
4. Fail hua to email alert + Settings → "Update log dekho".

Andar se: app `UPDATE_REQUESTED` flag likhta hai → systemd `munsiji-updater.path` → `deploy/update.sh` → `git reset --hard origin/main` → `docker compose build` → `up -d`. Mongo data aur `.env` safe.

> Phone ka native APK update se nahi badalta (uske liye Emergent Publish build). Backend + web app update hote hain.

## 6. Useful commands (VPS)
```bash
cd /opt/munsiji
docker compose -f deploy/docker-compose.yml ps                 # status
docker compose -f deploy/docker-compose.yml logs -f backend    # backend logs
docker compose -f deploy/docker-compose.yml up -d              # .env change ke baad
sudo bash deploy/update.sh                                     # manual update
systemctl status munsiji-updater.path munsiji-autoupdate.timer
nano .env                                                      # PIN/owner/keys/PUBLIC_BASE_URL (first-install defaults)
```

## 7. Backup
```bash
docker exec munsiji-mongo-1 mongodump --archive --db munsiji > munsiji-$(date +%F).archive
docker exec -i munsiji-mongo-1 mongorestore --archive --drop < munsiji-YYYY-MM-DD.archive   # restore
```

## 8. Files
- `deploy/install.sh` — one-command installer (re-run safe)
- `deploy/update.sh` — updater (systemd se chalta hai)
- `deploy/docker-compose.yml`, `Dockerfile.backend`, `Dockerfile.web`, `nginx.conf`, `requirements.txt`
- `deploy/systemd/*` — updater path/service + auto-update timer
- Runtime: `/opt/munsiji/data/` (Caddyfile, updater status/log), `/opt/munsiji/.env`
