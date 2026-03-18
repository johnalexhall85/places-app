# Temporary Public Demo Deployment (HTTP + Nginx)

This repository keeps the backend private on localhost and exposes only Nginx on port 80.

## Quick toggle script (recommended)

```bash
cd /home/john/places-app
./demo-public.sh up
```

Script behavior:
- Brings the demo stack up and opens `80/tcp` in UFW while running.
- Blocks in foreground until `Ctrl+C`.
- On exit, removes all UFW `ALLOW IN` rules for `80/tcp`.

Other commands:

```bash
./demo-public.sh status
./demo-public.sh down
```

## 1) Build frontend assets

```bash
cd /home/john/places-app/frontend
npm install
npm run build
sudo mkdir -p /var/www/places
sudo rsync -a --delete /home/john/places-app/frontend/dist/ /var/www/places/
```

Build output is `frontend/dist` and is mirrored to `/var/www/places` for Nginx.

## 2) Start backend as a localhost-only systemd service

```bash
sudo cp /home/john/places-app/infra/systemd/places-backend.service /etc/systemd/system/places-backend.service
sudo systemctl daemon-reload
sudo systemctl enable --now places-backend
sudo systemctl restart places-backend
sudo systemctl status --no-pager places-backend
```

## 3) Install/reload Nginx site config

```bash
sudo cp /home/john/places-app/infra/nginx/places-demo.conf /etc/nginx/sites-available/places-demo
sudo ln -sfn /etc/nginx/sites-available/places-demo /etc/nginx/sites-enabled/places-demo
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

## 4) Verify

```bash
# App shell
curl -I http://<server-ip>/

# Backend through Nginx reverse proxy
curl http://<server-ip>/api/health

# Confirm backend is not listening on public interfaces
ss -ltnp | rg ':80|:8000'
```

Expected listener for backend: `127.0.0.1:8000` (or `localhost:8000` only).

## 5) Firewall / Vultr ports

- Allow inbound TCP `80` from your colleague IP range (or `0.0.0.0/0` for short demo if needed).
- Keep SSH (`22`) allowed for your admin access.
- Do not expose backend port `8000` publicly.
- Outbound egress should stay open for map/geocoder/data calls as needed by the app.
