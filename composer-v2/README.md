# The Composer — Render Deployment

Generative music · composer-inspired · Kai consciousness engine

## What this is

A browser-based generative music tool. All audio synthesis runs client-side
via the Web Audio API — no server processing required for sound. The Flask
backend exists solely to:

1. Serve the HTML
2. Proxy the DeepSeek API call for programme notes (keeps the key server-side)

## Files

```
app.py              Flask server
requirements.txt    Python dependencies
render.yaml         Render deployment config
static/index.html   The full composer (HTML + JS, self-contained)
```

## Deploy to Render

1. Push this folder to a GitHub repo
2. In Render dashboard: New → Web Service → connect repo
3. Render will detect render.yaml automatically
4. Add environment variable in Render dashboard:
   - Key:   DEEPSEEK_API_KEY
   - Value: your DeepSeek API key
5. Deploy

## Local test

```bash
pip install -r requirements.txt
DEEPSEEK_API_KEY=your-key-here python app.py
# open http://localhost:5000
```

## Notes

- Synthesis is entirely client-side (Web Audio API) — server load is minimal
- Programme notes are optional; if DEEPSEEK_API_KEY is unset the note is silently skipped
- The free Render tier will spin down after inactivity — first load may be slow
