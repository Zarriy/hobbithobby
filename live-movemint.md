# Deployment Guide — hobbithobby.quest

**Backend**: FastAPI → VPS → `api.hobbithobby.quest`
**Frontend**: React/Vite → Netlify → `hobbithobby.quest`
**Domain**: Namecheap (DNS stays on Namecheap, no nameserver transfer needed)

---

## Overview

```
Your Browser
  ├── loads page  →  Netlify CDN  (hobbithobby.quest)
  └── API calls   →  VPS nginx    (api.hobbithobby.quest)
                          │
                     FastAPI :8001
                          │
                     SQLite DB + Binance + Telegram
```

Follow the parts **in order**. DNS must propagate before you can get SSL certs.

---

## Part 1 — Code Changes ✅ Already Done

These were applied to the codebase. Just confirming what changed:

| File | Change |
|------|--------|
| `frontend/src/api/client.ts` | `BASE` now reads `VITE_API_URL` env var |
| `main.py` | CORS now includes `FRONTEND_URL` env var |
| `frontend/netlify.toml` | Created — Netlify build config |
| `.env.example` | Created — reference for VPS `.env` |

---

## Part 2 — Push Code to GitHub

Netlify will pull from GitHub. Do this before setting up Netlify.

```bash
# On your Mac, from the project root
cd /Users/mackbookpro/Desktop/trading-zones/crypto-signal-engine

git init                          # if not already a git repo
git add .
git commit -m "initial commit"

# Create a new repo on github.com (do this in browser, name it e.g. crypto-signal-engine)
# Then link and push:
git remote add origin https://github.com/<your-username>/crypto-signal-engine.git
git branch -M main
git push -u origin main
```

> Add a `.gitignore` first so you don't commit secrets or the SQLite DB:
> ```
> .env
> db/
> data/
> reports/
> __pycache__/
> .venv/
> *.pyc
> *.pkl
> node_modules/
> frontend/dist/
> ```

---

## Part 3 — Namecheap DNS

Log in to **namecheap.com** → Domain List → `hobbithobby.quest` → **Manage** → **Advanced DNS** tab.

Delete any default A/CNAME records that Namecheap pre-fills, then add these:

### 3A — Point API subdomain to your VPS (do this FIRST — certbot needs it)

| Type | Host | Value | TTL |
|------|------|-------|-----|
| A Record | `api` | `YOUR_VPS_IP` | Automatic |

### 3B — Point root domain to Netlify

| Type | Host | Value | TTL |
|------|------|-------|-----|
| A Record | `@` | `75.2.60.5` | Automatic |
| CNAME Record | `www` | `YOUR-SITE.netlify.app` | Automatic |

> You won't have your Netlify site URL yet — come back and fill in the CNAME after Part 5.

**Check propagation** (run from your Mac, repeat until it resolves):
```bash
nslookup api.hobbithobby.quest
# Should return your VPS IP. Takes 10 min–48 hours.
```

---

## Part 4 — VPS Setup

SSH into your VPS. All commands below run as `root` unless noted.

### 4A — Connect and update

```bash
ssh root@YOUR_VPS_IP

apt update && apt upgrade -y
```

### 4B — Install Python 3.13

```bash
apt install -y software-properties-common
add-apt-repository ppa:deadsnakes/ppa -y
apt update
apt install -y python3.13 python3.13-venv python3.13-dev build-essential
```

Verify:
```bash
python3.13 --version
# Python 3.13.x
```

### 4C — Install nginx + certbot

```bash
apt install -y nginx certbot python3-certbot-nginx
systemctl enable nginx
systemctl start nginx
```

### 4D — Open firewall ports

```bash
ufw allow OpenSSH
ufw allow 'Nginx Full'    # opens ports 80 and 443
ufw enable
ufw status
```

### 4E — Create app user

```bash
useradd -m -s /bin/bash signalbot
```

### 4F — Upload project files (run from your Mac)

```bash
# On your Mac:
scp -r /Users/mackbookpro/Desktop/trading-zones/crypto-signal-engine/* \
  root@YOUR_VPS_IP:/home/signalbot/app/

# Fix ownership on VPS:
ssh root@YOUR_VPS_IP "chown -R signalbot:signalbot /home/signalbot/app"
```

> Alternatively, once GitHub is set up: `git clone https://github.com/<you>/crypto-signal-engine /home/signalbot/app`

### 4G — Install Python dependencies

```bash
# On VPS:
cd /home/signalbot/app
python3.13 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

### 4H — Create the .env file

```bash
nano /home/signalbot/app/.env
```

Paste and fill in:
```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
COINGLASS_API_KEY=
FRONTEND_URL=https://hobbithobby.quest
```

Save: `Ctrl+X` → `Y` → `Enter`

Lock down permissions:
```bash
chmod 600 /home/signalbot/app/.env
chown signalbot:signalbot /home/signalbot/app/.env
```

### 4I — Test the app runs

```bash
su - signalbot
cd /home/signalbot/app
.venv/bin/python main.py &
sleep 3
curl http://localhost:8001/api/status
# Should return JSON. Kill the test process:
kill %1
exit
```

### 4J — Install tmux and start the engine

```bash
apt install -y tmux
```

Create a named tmux session and start the app inside it:

```bash
tmux new-session -d -s signal-api
tmux send-keys -t signal-api 'cd /home/signalbot/app && source .env && .venv/bin/python main.py' Enter
```

Check it started:
```bash
tmux attach -t signal-api
# You should see FastAPI/uvicorn startup logs
# Detach without stopping it: Ctrl+B then D
```

Confirm the API is responding:
```bash
curl http://localhost:8001/api/status
```

### 4K — Auto-start on VPS reboot

tmux sessions don't survive a reboot on their own. Add a cron job to recreate the session automatically:

```bash
crontab -e
```

Add this line at the bottom:
```
@reboot sleep 10 && tmux new-session -d -s signal-api && tmux send-keys -t signal-api 'cd /home/signalbot/app && source .env && .venv/bin/python main.py' Enter
```

The `sleep 10` gives the network time to come up before the app starts fetching from Binance.

**Useful tmux commands:**

| Command | What it does |
|---------|-------------|
| `tmux attach -t signal-api` | Reconnect to the running session |
| `Ctrl+B D` | Detach (leave app running) |
| `tmux ls` | List all active sessions |
| `tmux kill-session -t signal-api` | Stop the engine |

---

## Part 5 — nginx + SSL for api.hobbithobby.quest

> **Wait until `nslookup api.hobbithobby.quest` returns your VPS IP before running certbot.**

### 5A — Create nginx site config

```bash
nano /etc/nginx/sites-available/signal-api
```

Paste:
```nginx
server {
    listen 80;
    server_name api.hobbithobby.quest;

    location / {
        proxy_pass         http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 60s;
    }
}
```

Enable and reload:
```bash
ln -s /etc/nginx/sites-available/signal-api /etc/nginx/sites-enabled/
nginx -t        # must say: syntax is ok
systemctl reload nginx
```

### 5B — Get SSL certificate

```bash
certbot --nginx -d api.hobbithobby.quest
```

Follow the prompts:
- Enter your email address
- Agree to Terms of Service: `A`
- Choose option `2` (Redirect HTTP to HTTPS)

Certbot automatically edits your nginx config to add SSL and auto-renews every 90 days.

### 5C — Verify HTTPS

```bash
curl https://api.hobbithobby.quest/api/status
# Should return JSON like: {"scheduler_running": true, ...}
```

---

## Part 6 — Netlify Deployment

### 6A — Create the Netlify site

1. Go to **app.netlify.com** → Sign in (or create account)
2. Click **"Add new site"** → **"Import an existing project"**
3. Choose **GitHub** → Authorize Netlify → Select your `crypto-signal-engine` repo
4. Build settings (should be auto-detected from `netlify.toml`):
   - Base directory: `frontend`
   - Build command: `npm run build`
   - Publish directory: `frontend/dist`
5. Click **"Deploy site"**

Netlify gives you a random URL like `https://dazzling-fox-abc123.netlify.app` — note this down.

### 6B — Set environment variable

In Netlify: **Site configuration** → **Environment variables** → **Add a variable**:
- Key: `VITE_API_URL`
- Value: `https://api.hobbithobby.quest`

Then **trigger a redeploy**: Deploys tab → "Trigger deploy" → "Deploy site".

### 6C — Add custom domain

1. **Site configuration** → **Domain management** → **Add a domain**
2. Enter `hobbithobby.quest` → Confirm
3. Also add `www.hobbithobby.quest`
4. Netlify will show DNS instructions — you already handled this in Part 3

### 6D — Back to Namecheap — fill in the CNAME

Go back to Namecheap Advanced DNS and update the `www` CNAME with your actual Netlify URL:

| Type | Host | Value |
|------|------|-------|
| CNAME Record | `www` | `dazzling-fox-abc123.netlify.app` |

### 6E — Wait for SSL on Netlify

Netlify auto-provisions a free Let's Encrypt SSL cert for your custom domain. It shows up in Domain Management as "Certificate provisioned" — takes 1–5 minutes after DNS propagates.

---

## Part 7 — Verification Checklist

Run through these after everything is deployed:

```bash
# From your Mac terminal:

# 1. Backend API is live and serving JSON
curl https://api.hobbithobby.quest/api/status

# 2. CORS header is present for your frontend domain
curl -I -H "Origin: https://hobbithobby.quest" https://api.hobbithobby.quest/api/status
# Look for:  Access-Control-Allow-Origin: https://hobbithobby.quest

# 3. DNS resolves correctly
nslookup hobbithobby.quest      # should return 75.2.60.5 (Netlify)
nslookup api.hobbithobby.quest  # should return YOUR_VPS_IP
```

In the browser:
- [ ] `https://hobbithobby.quest` loads the dashboard (padlock in address bar)
- [ ] Header shows **"● Live"** (not "⚠ Offline")
- [ ] Signal cards show data for BTC, ETH, SOL, XRP, TAO
- [ ] Open DevTools → Console — no red CORS errors
- [ ] `https://api.hobbithobby.quest/docs` shows the FastAPI Swagger UI

On the VPS:
```bash
tmux attach -t signal-api   # attach to the running session, check for errors
# Detach: Ctrl+B D
tmux ls                     # should show: signal-api: 1 windows
```

---

## Ongoing Operations

### Update the backend after code changes

```bash
# On your Mac — push to GitHub:
git add .
git commit -m "your change"
git push

# On VPS — pull and restart:
ssh root@YOUR_VPS_IP
cd /home/signalbot/app
git pull
tmux send-keys -t signal-api C-c              # stop the running process
tmux send-keys -t signal-api '.venv/bin/python main.py' Enter   # restart it
tmux attach -t signal-api                     # verify it started cleanly
```

### Update the frontend after code changes

Just push to GitHub — Netlify auto-deploys on every push to `main`.

### View backend logs

```bash
ssh root@YOUR_VPS_IP
tmux attach -t signal-api   # live output, Ctrl+B D to detach
```

### Renew SSL cert (auto, but manual test)

```bash
certbot renew --dry-run   # should say "Congratulations, all renewals succeeded"
```

---

## Troubleshooting

| Problem | Check |
|---------|-------|
| Dashboard shows "⚠ Offline" | `curl https://api.hobbithobby.quest/api/status` — is the API reachable? |
| CORS error in browser console | CORS is hardcoded in `main.py` — verify `hobbithobby.quest` is in the `allow_origins` list. Re-deploy if you changed it. |
| Netlify build fails | Check build logs on Netlify → is `npm run build` passing locally? |
| `certbot` fails with "could not connect to server" | DNS hasn't propagated yet — wait and retry |
| API returns 502 Bad Gateway | FastAPI isn't running: `tmux ls` to check; `tmux attach -t signal-api` to view logs |
| `api.hobbithobby.quest` not resolving | Check Namecheap A record for `api` host → correct VPS IP? |
