# Seedream Demo — FastAPI LLM/image proxy + clients

[![Tests](https://github.com/0ver1ay/Seedream-Demo/actions/workflows/test.yml/badge.svg)](https://github.com/0ver1ay/Seedream-Demo/actions/workflows/test.yml)

Portfolio demo: a **local FastAPI gateway** in front of Replicate image/LLM models, plus optional Photoshop UXP panel and a Tkinter desktop client.

> Public portfolio cut. Use your own `REPLICATE_API_TOKEN`. No baked secrets in this repo.

## What it shows

| Layer | Role |
|-------|------|
| `server/` | FastAPI proxy: generate / enhance, model configs, timeouts & error mapping |
| `desktop-app/` | Tkinter client → HTTP API (buildable to `.exe`) |
| `photoshop-plugin/` | UXP panel calling the same local API |
| `tests/` | Core + HTTP client tests; optional live Replicate test behind env flag |
| CI | `.github/workflows/test.yml` |

Useful as an **LLM/image integration** portfolio piece: packaging a vendor API behind your own REST boundary (auth via env, not client).

## Quick start (server)

```powershell
cd server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:REPLICATE_API_TOKEN = "<your_token>"
uvicorn main:app --host 127.0.0.1 --port 8000
```

Main endpoint: `POST /seedream/generate` → PNG base64 (see OpenAPI at `/docs`).

## Desktop client

```powershell
cd desktop-app
pip install -r requirements.txt
copy secrets.example.json secrets.json   # optional; prefer env on server
$env:SEEDREAM_SERVER = "http://127.0.0.1:8000"
python app.py
```

## Security

- Never commit `secrets.json` or real tokens.
- Prefer server-side `REPLICATE_API_TOKEN`; do not embed keys in the Photoshop panel.

## License

[MIT](LICENSE) — portfolio / demo use. Replicate and model terms apply to upstream APIs.
