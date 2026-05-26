# AI Job Agent Deployment

## Render

Create a Render Web Service from this repository.

Use:

```text
Build Command: pip install -r requirements.txt
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
```

Render's FastAPI docs use the same Uvicorn start command with `$PORT`.

Set environment variables in Render:

```env
META_ACCESS_TOKEN=
META_PHONE_NUMBER_ID=
META_WABA_ID=
META_VERIFY_TOKEN=
META_GRAPH_API_VERSION=v25.0

SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=

GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
GEMINI_FALLBACK_MODEL=gemini-2.5-flash-lite

APP_TIMEZONE=Asia/Kolkata
CRON_SECRET=
SCHEDULER_MAX_CONCURRENCY=3
PUBLIC_BASE_URL=https://your-render-service.onrender.com

ENABLE_AMAZON_JOBS=true
PREFERRED_JOB_QUERIES=SDE-1,Software Development Engineer,Backend Engineer
GREENHOUSE_BOARD_TOKENS=airbnb,stripe
LEVER_COMPANY_SLUGS=
ASHBY_BOARD_NAMES=ashby
```

After deployment, test:

```text
https://your-render-service.onrender.com/health/db
```

## Meta Webhook

Set callback URL:

```text
https://your-render-service.onrender.com/webhook
```

Verify token:

```text
same value as META_VERIFY_TOKEN
```

Subscribe to:

```text
messages
```

## Cron-Job.org

Create one cron job.

Use:

```text
URL: https://your-render-service.onrender.com/execute-daily-search?token=YOUR_CRON_SECRET&limit=5
Method: POST
Schedule: daily at 20:00 Asia/Kolkata
```

For the first run, use:

```text
https://your-render-service.onrender.com/execute-daily-search?token=YOUR_CRON_SECRET&limit=5&dry_run=true
```

Remove `dry_run=true` after confirming the output.

cron-job.org supports custom HTTP methods including POST and can execute scheduled URL requests.

## Local Preflight

Run:

```powershell
.\.venv\Scripts\python.exe preflight.py
```

Fix any failures before deploying.
