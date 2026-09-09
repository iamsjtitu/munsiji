# Munsiji.app — Personal WhatsApp Munim

## Original Problem Statement
Mobile App (Expo React Native + TypeScript) + FastAPI + MongoDB. WhatsApp bot (wa.9x unofficial API behind provider abstraction) is the hero entry channel. Owner sends Hinglish messages ("Biki [Mill] - 50000, Investment account", "10000 - biki mill", "receved 5000 - biki mill", "kal 2000 - biki mill", "cash account ka ledger bhej", "7 jan 2026 se aaj tak ka ledger bhej", "last entry delete karo", "500 nahi 700 tha") → AI (Gemini 3 Flash) parses amount/party/group/direction/date, fuzzy-matches or auto-creates ledgers, records debit/credit with running balance, replies in Hinglish with balance, sends PDF/Excel statements on WhatsApp. App: PIN login, groups → ledgers → Tally-style statement, manual entry/edit, merge/reassign, monthly summary, CSV/Excel/PDF export. Whitelist-only owner number.

## User Choices
- wa.9x keys: not yet — mock provider now, keys entered later from in-app Settings (admin panel)
- AI: Emergent Universal Key, model `gemini-3-flash-preview`
- Owner WhatsApp: 917205930002, PIN: 3366
- Look: light, clean ledger/finance feel (emerald/zinc, green credit / red debit, mono numerals)

## Architecture
- backend/: `server.py` (routes, /api prefix), `bot.py` (message pipeline + pending clarifications), `ai_parser.py` (Gemini + regex fallback), `ledger_service.py` (normalize, rapidfuzz matching, balances, statements, merge), `wa_provider.py` (MockProvider / Wa9xProvider + incoming payload normaliser), `exports.py` (CSV/XLSX/PDF), `auth.py` (bcrypt PIN + JWT), `models.py` (PyObjectId/BaseDocument)
- Mongo collections: groups, ledgers, transactions (soft delete), wa_messages (dedupe by wa_message_id), pending, settings (singleton key=main), export_files, wa_outbox
- frontend/: expo-router stack. `index.tsx` PIN → `(app)/home` (dashboard+groups) → `group/[id]` → `ledger/[id]` (statement, add/edit entry, export, rename/move/merge) · `whatsapp` (log + test chat via /whatsapp/simulate) · `summary` · `settings`
- Balance convention: debit (diya) − credit (mila); + = "lena hai", − = "dena hai"

## Implemented (Sep 2026)
- Phase 1–4 all delivered in MVP: schema, PIN auth, wa.9x adapter (configurable base URL / API key / paths), whitelist, dedupe, AI parsing + fuzzy match + confirm-on-similar, Hinglish replies with running balance, corrections (delete last / amount fix), back-dated entries, statements via WhatsApp (asks PDF/Excel if unspecified, supports date ranges), app screens, manual entry/edit/delete, merge/reassign, monthly summary, PDF/Excel/CSV export (+ send on WhatsApp), settings admin panel
- Tested: iteration_1 — backend 24/24, frontend 20/20 pass
- **Self-host VPS package (deploy/)**: one-command `install.sh` (Docker Compose: mongo + backend + Expo web build via nginx + Caddy auto-HTTPS), host-side updater (`update.sh` + systemd path unit triggered by app, 15-min auto-update timer behind AUTO_UPDATE flag), backend `/api/system/version|update|auto-update` (git-based, `REPO_DIR`/`UPDATER_DIR` env; unsupported → hidden in Emergent preview), Home update banner, Settings "Server & Updates" card (installed/latest commit, check, update now, auto-update switch, log), runtime Server URL override (PIN screen + Settings) so the same app build can point at the VPS. `deploy/README.md` = Hinglish guide. Tested iteration_2 — 9/9 backend, 11/11 frontend
- **Admin keys + email alerts (Sep 2026)**: Settings → Emergent Keys card (LLM key + Email key, write-only/masked, settings override .env), Email Alerts card (owner email admin@munsiji.com, on/off, test email). Backend `emailer.py` (Emergent-managed Resend, guardrail gate, 30-min throttle per kind, `alerts` collection). Alerts: pin_lockout, wa_send_failed, ai_failed, update_failed (watcher loop). Tested iteration_3 — 11/11 backend, 7/7 frontend. Known: munsiji.app has no MX yet → admin@munsiji.com undeliverable until user sets up mailbox; DNS A record still on parking IP.
- Deploy targets: repo github.com/iamsjtitu/munsiji (404 publicly → private or not pushed yet), domain munsiji.app; install.sh/README carry real values and --email-key/--owner-email flags

## Backlog
- P1: Verify real wa.9x payload shape once user provides keys (send/doc endpoint field names may need adjusting in `wa_provider.py`)
- P1: Group-level / all-ledgers export; date-range picker in app
- P2: Multiple owners / staff read-only, reminders for pending balances, dark theme
- P2: RN-web deprecation warnings (shadow* → boxShadow)
