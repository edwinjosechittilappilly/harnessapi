---
title: Deploy to production
description: How to deploy a harnessapi app to production — Railway, Fly.io, Docker, or any ASGI host.
---

harnessapi is a standard ASGI app (FastAPI subclass) — it deploys anywhere that runs Python ASGI apps.

## Railway (recommended — one click)

1. Push your project to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Set the start command:

   ```
   uvicorn main:app --host 0.0.0.0 --port $PORT
   ```

4. Add environment variables (e.g. `OPENAI_API_KEY`)
5. Deploy — Railway provides a public URL automatically

## Fly.io

```bash
fly launch
fly secrets set OPENAI_API_KEY=sk-...
fly deploy
```

`fly.toml`:

```toml
[http_service]
  internal_port = 8000
  force_https = true
```

## Docker

```dockerfile title="Dockerfile"
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install uv && uv sync --no-dev
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t my-skills .
docker run -p 8000:8000 -e OPENAI_API_KEY=sk-... my-skills
```

## Gunicorn (multi-worker)

```bash
pip install gunicorn uvicorn
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

## Environment variables

Store secrets as environment variables — never in `skill.toml` or handler files:

```python title="skills/summarize/handler.py"
import os
api_key = os.environ["OPENAI_API_KEY"]
```

## Disable edit endpoints in production

```python title="main.py"
import os
app = HarnessAPI(
    skills_dir="./skills",
    enable_edit_endpoints=os.getenv("ENABLE_EDIT") == "true",
)
```

## Connect MCP clients to production

Update your Claude Desktop or Cursor config to point to your deployed URL:

```json
{
  "mcpServers": {
    "my-skills": {
      "url": "https://your-app.railway.app/mcp"
    }
  }
}
```
