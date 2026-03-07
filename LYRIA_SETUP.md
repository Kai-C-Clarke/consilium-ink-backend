# Google Cloud Setup — Lyria 2 for The Composer

## What you need
- A Google account
- ~10 minutes
- A credit card (but $0.06/request — 100 songs = $6)

---

## Step 1: Create a Google Cloud Project

1. Go to https://console.cloud.google.com
2. Click the project dropdown → **New Project**
3. Name it `composer-ai` (or anything you like)
4. Note your **Project ID** (shown below the name, e.g. `composer-ai-123456`)

---

## Step 2: Enable Vertex AI API

1. In the console, go to **APIs & Services → Library**
2. Search for **"Vertex AI API"**
3. Click it → **Enable**

Alternatively, run in Cloud Shell:
```bash
gcloud services enable aiplatform.googleapis.com
```

---

## Step 3: Create a Service Account

1. Go to **IAM & Admin → Service Accounts**
2. Click **Create Service Account**
3. Name: `composer-lyria`
4. Click **Create and Continue**
5. Add role: **Vertex AI User** (roles/aiplatform.user)
6. Click **Done**

---

## Step 4: Download the JSON Key

1. Click on your new service account
2. Go to **Keys** tab
3. **Add Key → Create new key → JSON**
4. Download the `.json` file (keep this secret — it's your credentials)

---

## Step 5: Set Render Environment Variables

In your Render service dashboard → **Environment**:

| Variable | Value |
|----------|-------|
| `GOOGLE_CLOUD_PROJECT` | Your project ID, e.g. `composer-ai-123456` |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | **The entire contents of your downloaded JSON file** |

For `GOOGLE_SERVICE_ACCOUNT_JSON`: open the .json file in a text editor,
select all, copy, paste as the env var value. It will look like:
```
{"type":"service_account","project_id":"composer-ai-...","private_key_id":"...
```

---

## Step 6: Test Locally (optional)

```bash
export GOOGLE_CLOUD_PROJECT="composer-ai-123456"
export GOOGLE_CLOUD_LOCATION="us-central1"
export GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
export DEEPSEEK_API_KEY="sk-..."

python app.py
```

Then POST to http://localhost:5000/compose:
```json
{"prompt": "I want something stormy and dramatic"}
```

---

## What changes in the app

**Before (DeepSeek ABC):**
```
User prompt → Confucius → ABC notation → abc2midi → FluidSynth → SoX → MP3
```

**After (Lyria):**
```
User prompt → Confucius → Lyria 2 (48kHz WAV) → SoX → MP3
```

The Dockerfile is now much simpler — no fluidsynth, abcmidi, or mido needed.
Just sox + lame for post-processing.

---

## Pricing reminder

- Lyria 2: **$0.06 per 30-second clip**
- Google Cloud free tier: $300 credit for new accounts
- 100 test generations = $6
