---
sidebar_position: 4
title: Deploy the API
description: Run the patrol as a service with FastAPI, scheduling, and restart-safe approvals.
---

# Deploy the API

The patrol runs as a FastAPI service. The approval state is persisted, so a restart resumes exactly where a paused patrol stopped.

## Minimal server

```python
# serve.py
import uvicorn
from dataquality_agent.api.main import create_app
from dataquality_agent.api.wiring import build_runtime

runtime = build_runtime()          # reads DATA_DIR / DB_PATH / CHECKPOINT_PATH
app = create_app(runtime)          # optionally: create_app(runtime, static_dir="dashboard")
uvicorn.run(app, host="0.0.0.0", port=8000)
```

```bash
python serve.py
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/patrol` | Trigger a patrol; returns `run_id` + `status` |
| `GET` | `/patrols` | List run ids (persisted across restarts) |
| `GET` | `/patrol/{run_id}` | Fetch a patrol's state |
| `POST` | `/patrol/{run_id}/approve` | Approve/reject the high-risk fixes that paused it |
| `GET` | `/health` | Liveness |

## Configuration

Set via environment (or a `.env` loaded by `dqagent init`):

| Variable | Meaning |
|---|---|
| `DEEPSEEK_API_KEY` | LLM for attribution + remediation |
| `DATA_DIR` / `DB_PATH` | Warehouse location |
| `CHECKPOINT_PATH` | HITL checkpoint (SQLite) |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | Optional trace backend |

## Persistence and restart

Two SQLite files hold the runtime state:

- `checkpoints.sqlite` — the LangGraph checkpoint: where an interrupted patrol pauses. Restarting the process and calling `approve` resumes it.
- `runs.sqlite` — the `RunStore`: which runs exist and their status, so `/patrols` and `/patrol/{id}` survive a restart.

Both are plain SQLite for the reference deployment; swap them for a shared store when you run more than one instance.

:::note Roadmap
A `dqagent serve` command that wraps `uvicorn` (and a bundled dashboard) is on the roadmap. Until then, the five-line `serve.py` above is the supported path.
:::
