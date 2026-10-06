# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

RAG-based employee policy Q&A API: FastAPI → PostgreSQL exact-match cache → LangGraph workflow → Azure OpenAI (GPT-4o + `text-embedding-3-small`) and Azure AI Search. Deployed as a Docker image to Azure Container Apps. Python 3.12.

## Rules

- Never read, print, or copy `.env`. Learn required variables from `app/core/config.py` and `.env.example`.
- Unit tests must not call live Azure OpenAI, Azure AI Search, or the real database — mock them. Existing tests violate this (see below); don't add more that do.
- Work on feature branches. Don't commit or push unless asked.
- Before calling a code change done, run pytest `tests/test_graph.py` and report the result, including failures you didn't fix. Don't run `tests/test_main.py` — it hits live services until it's isolated (see below).
- Don't change Azure resources, the Dockerfile base image, or deployment config without asking.
- When you fix an item under "Things that will trip you up", update or remove it in this file.

## Commands

Windows / PowerShell, from the repo root:

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

docker compose up -d postgres        # local Postgres 16 on host port 5433
alembic upgrade head                 # apply migrations
uvicorn app.main:app --reload        # API at http://localhost:8000/docs

docker compose up -d                 # API + Postgres both in containers

pytest                               # all tests
pytest tests/test_graph.py           # one file
pytest tests/test_graph.py::test_route_review   # one test
```

All direct dependencies in `requirements.txt` are pinned to exact versions (`==`), including `alembic`.

New migration after changing a model: `alembic revision --autogenerate -m "message"`.

One-off RAG scripts (run as modules so `app.*` imports resolve):

```powershell
python -c "from app.rag.search_index import create_search_index; create_search_index()"   # create the Azure AI Search index
python -m app.rag.index_documents    # chunk, embed and upload data/policies/fca_employee_handbook.pdf
python -m app.rag.retriever          # smoke-test retrieval with a sample question
```

There is no linter, formatter, or CI configuration.

## Things that will trip you up

- **Importing almost anything under `app/` needs a complete `.env`.** `app/core/config.py` instantiates `Settings()` at import time with no defaults for the database, Azure OpenAI, or Azure Search fields, and `app/ai/client.py`, `app/ai/embeddings.py`, `app/rag/retriever.py`, `app/database/connection.py`, and `app/graph/workflow.py` all build their clients / compile the graph as module-level singletons. This applies to `pytest` and `alembic` too.
- **Rate limits are in memory.** `app/core/rate_limit.py` counts requests per process, so limits reset on restart and apply per replica. `/ask` and the UI share one limiter, and cached answers count too.
- **Alembic's URL comes from `settings.database_url`**, not `alembic.ini` — `alembic/env.py` overrides `sqlalchemy.url`. Local host URL: `postgresql+psycopg://app_user:local_dev_password@localhost:5433/employee_policy`. Inside Compose the `api` service overrides `DATABASE_URL` to use `postgres:5432`.
- **The cache stores every answer, forever.** `/ask` caches answers from every branch, including the out-of-scope message and the rejected-answer fallback, keyed on the exact question string with no expiry. After changing a prompt, re-asking the same question returns the old cached answer. To test the change, delete the matching `conversations` rows or reword the question.
- **New models must be exported from `app/models/__init__.py`.** `alembic/env.py` imports `app.models` to populate `Base.metadata`, so autogenerate can't see a model that isn't exported there.
- **Tests are not isolated.** `tests/test_main.py::test_ask_returns_cached_answer` uses the real `SessionLocal` against the configured database; on a cache miss it runs the full graph against live Azure OpenAI / Azure AI Search and writes a row. Nothing is mocked. `tests/test_graph.py` only covers the pure routing functions, but still needs `.env` to import. `tests/test_rate_limit.py` and `tests/test_ui.py` use fakes and don't need `.env`; keep `app/core/rate_limit.py` and `app/ui.py` free of `app.core.config` imports so they stay that way.

## Architecture

### Request flow (`app/main.py`)

`POST /ask` checks the rate limiter (429 when over a limit), then calls `answer_question`, which the Gradio page in `app/ui.py` (mounted at `/ui`; `/` redirects there) also uses. Questions are 1–500 characters (`MAX_QUESTION_LENGTH` in `app/schemas/ask.py`). `answer_question` opens a `SessionLocal()` directly (no FastAPI dependency), looks up the most recent `Conversation` whose `question` exactly equals the request string, and returns its answer if found. Cached responses carry **no `sources`** — only `question`/`answer` are persisted. On a miss it invokes `policy_graph` with a fully initialised state dict, saves a `Conversation` with a fresh random `session_id` (not a real session — every request gets a new one), and returns the answer plus sources.

### LangGraph workflow (`app/graph/`)

`state.py` defines `PolicyAssistantState` (`question`, `question_type`, `answer`, `review_status`, `sources`). `workflow.py` wires nodes from `nodes.py`:

```
classify_question ─┬─ policy_question  → generate_policy_rag_answer → review_policy_answer ─┬─ approved → END
                   ├─ general_question → generate_answer → END                              └─ rejected → handle_rejected_answer → END
                   └─ out_of_scope     → handle_out_of_scope → END
```

Routing uses the raw LLM text: `classify_question` stores `response.content.strip()` and `review_policy_answer` stores `.strip().lower()`, and the router functions return those strings as edge keys. Any output outside the expected labels has no matching edge and fails the request, so prompt changes to these two nodes must keep the exact label vocabulary in sync with the edge maps in `workflow.py`.

The review node sees only the question and answer, not the retrieved context. Only the policy branch is reviewed.

### RAG (`app/rag/`)

- `loader.py` — `PyPDFLoader` + `RecursiveCharacterTextSplitter` (1000 / 200).
- `search_index.py` — index schema: `id`, `content`, `source`, `page`, `content_vector` (1536 dims, HNSW). The dimension is tied to `text-embedding-3-small`.
- `index_documents.py` — offline ingestion. IDs are positional (`chunk-{i}`), so re-indexing a different document overwrites earlier chunks rather than adding to them. `source` comes from the PDF's `title` metadata.
- `retriever.py` — pure vector search (`search_text=None`), `top_k=3`.
- `generator.py` — builds the grounded prompt from retrieved chunks and returns `{"answer", "sources"}` with de-duplicated `{document, page}` pairs. Pages given to the model and returned in `sources` are printed pages (the index's 0-based page + 1); this shape must match `Source` in `app/schemas/ask.py`.

### Azure clients (`app/ai/`)

Chat and embeddings are configured as separate Azure OpenAI resources (separate endpoint/key/deployment settings) with different pinned `api_version`s.

### Deployment

`Dockerfile` (`python:3.12-slim`, `uvicorn app.main:app` on 8000) → Azure Container Registry → Azure Container Apps (0–1 replicas), with secrets supplied as Container Apps secret references and Azure Database for PostgreSQL over SSL. The image does not run migrations on start.

The same image also runs as a free public demo on a Hugging Face Docker Space, with Neon Postgres and an Azure AI Search free-tier service. Steps are in `deploy/huggingface/DEPLOY.md`; `deploy/huggingface/README.md` is the Space card (it sets `app_port: 8000`).
