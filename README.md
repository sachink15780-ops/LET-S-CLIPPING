# LET'S CLIPPING ✂️

A browser-based clipping studio for turning videos you own or have permission to use into short clips.

## What currently works
- Upload a video file (backend limit configurable; default 500 MB).
- Paste a public YouTube URL.
- Generate up to 5 highlight candidate clips using speech transcription and a heuristic scorer (Whisper on the server; fallback windows if unavailable).
- Export clips as MP4 in vertical 9:16 or landscape 16:9.
- Backend health endpoint and downloadable clip endpoints.

**Important:** highlight ranking is heuristic and clips need review. Automatic burned-in captions, live-stream monitoring, cloud-drive import, user accounts, and persistent storage are not implemented yet. Render free instances may sleep and local storage may be ephemeral.

## Publish the frontend (GitHub Pages)
1. Open the repository's **Settings → Pages**.
2. Under Build and deployment, select **GitHub Actions** as the source.
3. The included workflow deploys on pushes to `main`. When it succeeds, the site URL is:
   `https://sachink15780-ops.github.io/LET-S-CLIPPING/`

## Deploy the backend (Render Blueprint)
1. Sign in to Render and choose **New → Blueprint**.
2. Connect GitHub and select `sachink15780-ops/LET-S-CLIPPING`.
3. Render reads `render.yaml` and creates `lets-clipping-api`. Confirm the Blueprint and wait for deployment.
4. Copy the public service URL from Render.
5. Paste that URL into the API URL box on the website and press **Check backend connection**.
6. Then upload a video or paste a YouTube URL and generate clips.

Blueprint deploy link (sign in required): https://dashboard.render.com/blueprints

## Backend local development
From the `backend` folder:
```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```
FFmpeg must be installed. Docker deployment installs FFmpeg automatically.

## API
- `GET /health`
- `POST /api/clip` — multipart fields: `file`, optional `ratio` (9:16 or 16:9)
- `POST /api/clip-url` — multipart fields: `url`, optional `ratio`
- `GET /api/jobs/{job}/files/{name}` — download generated MP4

Only process content you own or have permission to use. Don't share the public service URL if you don't want others using the backend.
