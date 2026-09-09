# Munsiji — Apne VPS pe chalao (Self-host guide)

Poora stack ek command se: **MongoDB + FastAPI backend + Web app + HTTPS (Caddy)**, plus GitHub se **one-tap update** (app ke Settings se) aur optional **auto-update**.

## 1. Kya chahiye
| Cheez | Detail |
|---|---|
| VPS | Ubuntu 22.04 / 24.04 (ya Debian 12), **2 GB RAM+** (script khud 3 GB swap add kar deta hai), 20 GB disk |
| Ports | 80 aur 443 open (firewall / cloud security group) |
| Domain (optional) | `munsiji.example.com` ka A record → VPS IP. Domain doge to HTTPS automatic. Nahi doge to `http://<IP>` pe chalega |
| GitHub repo | Emergent mein **Save to GitHub** karo (public repo = simplest). Private repo ke liye niche dekho |
| Emergent LLM key | AI parsing ke liye (`sk-emergent-...`) — Emergent Profile → Universal Key |

## 2. Ek command (VPS pe root/sudo se)
```bash
curl -fsSL https://raw.githubusercontent.com/<USER>/<REPO>/main/deploy/install.sh | sudo bash -s -- \
  --repo https://github.com/<USER>/<REPO>.git \
  --domain munsiji.example.com --email you@example.com \
  --owner 917205930002 --pin 3366 --llm-key sk-emergent-xxxx
```
- Bina domain: `--domain` aur `--email` hata do → `http://<VPS-IP>` pe chalega.
- **Private repo**: GitHub → Settings → Developer settings → Fine-grained token (repo read) banao, phir:
  ```bash
  git clone https://<TOKEN>@github.com/<USER>/<REPO>.git /opt/munsiji
  sudo bash /opt/munsiji/deploy/install.sh --repo https://<TOKEN>@github.com/<USER>/<REPO>.git --owner 9172... --llm-key sk-emergent-...
  ```
  (token remote URL mein reh jaata hai, isi se updates bhi fetch honge)

Script ye karta hai: Docker install → swap → code clone `/opt/munsiji` → `.env` banata hai (random JWT secret) → Caddy config → systemd updater → `docker compose build && up -d`. 5–10 min. End mein URL, PIN aur **WhatsApp webhook URL** print hota hai.

## 3. Install ke baad
1. Browser mein `https://munsiji.example.com` kholo → PIN se login.
2. **Settings → WhatsApp (wa.9x)**: Base URL, API key daalo, provider **wa.9x live** karo, Save.
3. wa.9x dashboard mein incoming-message webhook: `https://munsiji.example.com/api/whatsapp/webhook`
4. Phone app (APK/Expo Go) ko VPS se connect karna ho: PIN screen ke upar-right **server icon** → apna URL daalo → Save (ya Settings → Server URL).

## 4. Update flow (Emergent → GitHub → VPS)
1. Emergent mein changes ke baad **Save to GitHub**.
2. App **home screen pe upar update bar** aa jaata hai ("Naya update available") → **Update karo**.  
   Ya **Settings → Server & Updates → Update now**. Progress (download → build → restart) wahi dikhta hai; web app khud reload ho jaata hai.
3. **Auto-update** switch on karo to server har 15 min GitHub check karke naya commit khud install karega.
4. Log: Settings → "Update log dekho" ya VPS pe `cat /opt/munsiji/data/updater/update.log`.

Kaise kaam karta hai: app `UPDATE_REQUESTED` flag likhta hai → host pe systemd (`munsiji-updater.path`) `deploy/update.sh` chalata hai → `git reset --hard origin/main` → `docker compose build` → `up -d`. Data (Mongo volume, `.env`) safe rehta hai.

> Note: phone ka native APK update se nahi badalta (uske liye Emergent Publish se naya build). Backend + web app update hote hain.

## 5. Useful commands (VPS)
```bash
cd /opt/munsiji
docker compose -f deploy/docker-compose.yml ps                 # status
docker compose -f deploy/docker-compose.yml logs -f backend    # backend logs
docker compose -f deploy/docker-compose.yml up -d              # .env change ke baad
sudo bash deploy/update.sh                                     # manual update
systemctl status munsiji-updater.path munsiji-autoupdate.timer
nano .env                                                      # config (PIN, owner number, LLM key, PUBLIC_BASE_URL)
```
PIN change: app Settings se. Owner number: app Settings → Whitelist (ya `.env` → `OWNER_WHATSAPP` sirf first install pe use hota hai).

## 6. Backup
```bash
docker exec munsiji-mongo-1 mongodump --archive --db munsiji > munsiji-$(date +%F).archive
```
Restore: `docker exec -i munsiji-mongo-1 mongorestore --archive --drop < file.archive`

## 7. Files
- `deploy/install.sh` — one-command installer (re-run safe)
- `deploy/update.sh` — updater (systemd se chalta hai)
- `deploy/docker-compose.yml`, `Dockerfile.backend`, `Dockerfile.web`, `nginx.conf`, `requirements.txt`
- `deploy/systemd/*` — updater path/service + auto-update timer
- Runtime data: `/opt/munsiji/data/` (Caddyfile, updater status/log), `/opt/munsiji/.env`
