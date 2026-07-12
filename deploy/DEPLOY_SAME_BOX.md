# Deploying Vantage on the same box as Grounded / BE AI READY

Vantage runs as its **own service** (FastAPI on `127.0.0.1:8000`) behind the
box's existing **Caddy**, served at `https://vantage.developai.co.za`. The
Grounded/BAIR Node app (`:3001`) and Postgres are untouched. Once it's live,
paste the URL into **BE AI READY admin → Vantage**.

> ⚠️ **Footprint.** Vantage pulls `torch`, `transformers`, `onnxruntime`,
> `opencv` (several GB on disk) and loads detection/ReID models into RAM at
> inference. On a shared box, watch memory — add swap if the instance is small,
> and consider `ALIBI_DFINE_MODEL=ustc-community/dfine-nano-coco` (default) to
> keep it light. This co-location was an explicit choice; monitor it.

## Prerequisites on the box
- Python 3.11+, `python3-venv`, and system libs for OpenCV:
  `sudo apt-get install -y python3-venv libgl1-mesa-glx libglib2.0-0 ffmpeg`
- Node 18+ (already present for the Node app) to build the console.

## 1. Get the code
```bash
cd /home/ubuntu
git clone https://github.com/pauldevelopai/vantage.git
cd vantage
```

## 2. Python env + dependencies (heavy; first run also downloads models)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt          # torch/transformers/onnxruntime/opencv — sizeable
```

## 3. Build the console (static SPA that Caddy serves)
```bash
cd alibi/console
npm ci
npm run build                            # produces alibi/console/dist/
cd ../..
```

## 4. Production config
```bash
cp alibi/config/production.env.template alibi/config/production.env
chmod 600 alibi/config/production.env
```
Edit `alibi/config/production.env` and set at least:
```
ALIBI_API_HOST=127.0.0.1        # localhost only — Caddy fronts it
ALIBI_API_PORT=8000
ALIBI_REQUIRE_HTTPS=true
# generate: python -c "import secrets; print(secrets.token_urlsafe(32))"
ALIBI_JWT_SECRET=<paste a strong secret>
# OPENAI_API_KEY=sk-...          # optional (scene descriptions); omit to run local-only
```

> 🔐 **Change default logins before exposing publicly.** Vantage ships demo
> users (`admin/admin123`, `operator1/operator123`). Rotate them — see
> `DEPLOYMENT_SECURITY_GUIDE.md`.

## 5. Run it as a service
```bash
sudo cp deploy/vantage.service /etc/systemd/system/vantage.service
sudo systemctl daemon-reload
sudo systemctl enable --now vantage
systemctl status vantage
curl -s http://127.0.0.1:8000/            # {"service":"Alibi API",...}
```

## 6. Caddy (subdomain → this service)
```bash
sudo cp deploy/caddy/vantage.developai.co.za.caddy /etc/caddy/sites/
sudo systemctl restart caddy              # restart, NOT reload (box runs `admin off`)
```

## 7. DNS
In the developai.co.za control panel, add an **A record**:
`vantage` → the box IP (the same one Grounded uses, `52.56.143.231`).
Caddy auto-provisions HTTPS once DNS resolves.

## 8. Wire it into the admin dashboard
- Open `https://beaiready.developai.co.za/admin/vantage` (admin login).
- Set **Deployed URL** = `https://vantage.developai.co.za`, Save.
- The **Open Vantage ↗** button now launches it.

## Verify
- `https://vantage.developai.co.za` loads the Vantage console over HTTPS.
- Login works; a camera/search page renders.
- From BAIR admin → Vantage, the launcher opens it in a new tab.
- Grounded (`grounded.developai.co.za`) and BAIR are unchanged.

## Updating later
```bash
cd /home/ubuntu/vantage && git pull
source .venv/bin/activate && pip install -r requirements.txt
cd alibi/console && npm ci && npm run build && cd ../..
sudo systemctl restart vantage
```
