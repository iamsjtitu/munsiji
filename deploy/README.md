# Munsiji — Apne VPS pe chalao (Self-host guide)

Repo: `https://github.com/iamsjtitu/munsiji` · Domain: `munsiji.app` · Alerts: `admin@munsiji.com`

Poora stack ek command se: **MongoDB + FastAPI backend + Web app + HTTPS (Caddy)**, GitHub se **one-tap update** (app Settings / home update bar), optional **auto-update**, aur owner ko **email alerts**.

## 1. Pehle ye 3 kaam
1. **DNS**: `munsiji.app` ka **A record → aapke VPS ka IP**. **Cloudflare use karte ho to neeche "Cloudflare" section dekho** (orange cloud + default settings pe Error 525 aata hai).
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
  --owner 917205930002 \
  --llm-key sk-emergent-xxxx --email-key ek_xxxx
```
(PIN script khud poochega — `--pin 123456` bhi de sakte ho, par shell history mein reh jaata hai.)

**Private repo** (GitHub → Settings → Developer settings → Fine-grained token, repo *Contents: read*):
```bash
sudo git clone https://<TOKEN>@github.com/iamsjtitu/munsiji.git /opt/munsiji
sudo bash /opt/munsiji/deploy/install.sh \
  --repo https://<TOKEN>@github.com/iamsjtitu/munsiji.git \
  --domain munsiji.app --email admin@munsiji.com \
  --owner 917205930002 \
  --llm-key sk-emergent-xxxx --email-key ek_xxxx
```
(token remote URL mein reh jaata hai — updates isi se fetch honge)

Bina domain test karna ho: `--domain` / `--email` hata do → `http://<VPS-IP>`.

Script: Docker install → swap → clone `/opt/munsiji` → `.env` (random JWT secret) → Caddy HTTPS → systemd updater → `docker compose build && up -d`. 5–10 min. End mein **app URL, PIN, WhatsApp webhook URL** print hota hai.

## 4. Install ke baad (app Settings = admin panel)
1. `https://munsiji.app` → PIN `3366` se login.
2. **Emergent Keys**: LLM key / Email key yahan se bhi badal sakte ho (`.env` ke upar priority).
3. **Email Alerts**: owner email (`admin@munsiji.com`), on/off switch, **Test email bhejo**. Alerts: galat PIN ×5 (lock), wa.9x reply fail, AI parsing fail, server update fail. Max 1 / 30 min per type.
4. **WhatsApp (wa.9x.design)** — step by step:
   1. wa.9x dashboard → **Sessions** → QR scan karke **bot number** link karo (ye aapka owner number NAHI — alag SIM/number lo). Session settings mein **Receive Messages = ON**.
   2. **Get my API keys** → key copy (wa9x_… se shuru). Munsiji Settings → WhatsApp → API key paste, provider **wa.9x live**, Base URL khaali (default `https://wa.9x.design/api`), **Save**.
   3. Munsiji Settings ka **Webhook URL (poora, token ke saath)** copy karo → wa.9x → **Settings → Inbound Webhook** mein paste → Save. Optional: wa.9x ka *webhook signing secret* Munsiji mein daalo (HMAC verify).
   4. Munsiji → WhatsApp screen → upar **activity icon** → **Test message bhejo**: owner number pe WhatsApp aayega = sending OK. Neeche **webhook log** mein har hit dikhta hai (galat token / whitelist mismatch / processed) — wa.9x ke **Test** button se bhi entry aani chahiye.
   5. Ab apne owner number se bot number ko `Biki mill ko 5000 diya` bhejo → reply + entry.
   Webhook 10s ke andar 200 deta hai (processing background mein), 10 fail pe wa.9x webhook auto-disable karta hai — wa.9x Settings mein *Re-enable*.
5. Phone app ko VPS se connect: PIN screen ke upar-right **server icon** → `https://munsiji.app` → Save.

Security defaults: PIN 4–8 digit (install pe prompt, common PINs reject), bar-bar galat PIN pe backoff lock + email alert, PIN badalne pe purane logins invalid, statement download links random token + 24h expiry (`EXPORT_LINK_TTL_HOURS`), backend container non-root, security headers (Caddy + nginx CSP).

## 5. Cloudflare ke saath HTTPS (Error 525 / 526 fix)
Caddy default mein Let's Encrypt se certificate leta hai — ye tabhi chalta hai jab domain **seedha VPS pe** point kare. Cloudflare ka proxy (orange cloud) beech mein ho to LE fail hota hai → Cloudflare **Error 525 (SSL handshake failed)**. Teen options:

| Option | Kab | Kaise |
|---|---|---|
| **A. DNS only** (sabse simple) | Cloudflare proxy nahi chahiye | Cloudflare DNS → `munsiji.app` A record ke **orange cloud ko grey (DNS only)** karo → 1–2 min mein Caddy khud LE cert le lega |
| **B. Full** | Cloudflare proxy rakhna hai, 1 min fix | Cloudflare → SSL/TLS → Overview → **Full** (strict nahi). VPS pe: `cd /opt/munsiji && echo "TLS_MODE=internal" >> .env && bash deploy/gen-caddyfile.sh && docker compose -f deploy/docker-compose.yml restart caddy` |
| **C. Full (strict)** (best) | Cloudflare proxy + proper cert | Cloudflare → SSL/TLS → **Origin Server → Create Certificate** (hostnames `munsiji.app`, `*.munsiji.app`, 15 yrs). "Origin Certificate" ko `/opt/munsiji/data/certs/origin.pem`, "Private Key" ko `/opt/munsiji/data/certs/origin.key` mein save karo. Phir `bash deploy/gen-caddyfile.sh && docker compose -f deploy/docker-compose.yml restart caddy`, aur Cloudflare SSL mode **Full (strict)** |

Cloudflare pe "Always Use HTTPS" on rakho. Check: `docker compose -f deploy/docker-compose.yml logs caddy | tail -20` (cert errors yahin dikhte hain).

## 6. Update flow (Emergent → GitHub → VPS)
1. Emergent mein changes → **Save to GitHub**.
2. App home pe **"Naya update available" bar** → **Update karo**, ya Settings → Server & Updates → **Update now**. Progress dikhta hai; web app khud reload.
3. **Auto-update** switch on → har 15 min GitHub check, naya commit khud install.
4. Fail hua to email alert + Settings → "Update log dekho".

Andar se: app `UPDATE_REQUESTED` flag likhta hai → systemd `munsiji-updater.path` → `deploy/update.sh` → `git reset --hard origin/main` → `docker compose build` → `up -d`. Mongo data aur `.env` safe.

> Phone ka native APK update se nahi badalta (uske liye Emergent Publish build). Backend + web app update hote hain.

## 7. Useful commands (VPS)
```bash
cd /opt/munsiji
docker compose -f deploy/docker-compose.yml ps                 # status
docker compose -f deploy/docker-compose.yml logs -f backend    # backend logs
docker compose -f deploy/docker-compose.yml up -d              # .env change ke baad
sudo bash deploy/update.sh                                     # manual update
systemctl status munsiji-updater.path munsiji-autoupdate.timer
nano .env                                                      # PIN/owner/keys/PUBLIC_BASE_URL (first-install defaults)
```

## 8. Backup
```bash
docker exec munsiji-mongo-1 mongodump --archive --db munsiji > munsiji-$(date +%F).archive
docker exec -i munsiji-mongo-1 mongorestore --archive --drop < munsiji-YYYY-MM-DD.archive   # restore
```

## 9. Files
- `deploy/install.sh` — one-command installer (re-run safe)
- `deploy/gen-caddyfile.sh` — Caddy config generator (TLS_MODE auto/internal/origin)
- `deploy/update.sh` — updater (systemd se chalta hai)
- `deploy/docker-compose.yml`, `Dockerfile.backend`, `Dockerfile.web`, `nginx.conf`, `requirements.txt`
- `deploy/systemd/*` — updater path/service + auto-update timer
- Runtime: `/opt/munsiji/data/` (Caddyfile, updater status/log), `/opt/munsiji/.env`
