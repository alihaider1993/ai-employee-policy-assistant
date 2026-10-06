# Deploying the demo to Hugging Face Spaces

The app runs as a Docker Space: the existing `Dockerfile`, with the Gradio page at `/ui` and the API at `/ask`. The database is a free Neon Postgres, and retrieval uses an Azure AI Search free-tier service. Azure OpenAI is the only part with a running cost (pay per token).

## Before you start: protect your Azure spend

The Space is public, and every new question costs Azure OpenAI tokens.

- **Rate limits are built in**, covering both the page and the API:
  - **Per visitor:** 5 questions a minute (`RATE_LIMIT_PER_MINUTE`), including cached ones. This counter is in memory, so it resets when the Space restarts.
  - **Whole app:** at most 200 questions a day that call Azure (`RATE_LIMIT_PER_DAY`). Cached answers don't count and are still served after the cap is reached. This counter is stored in Postgres, so restarts and redeploys don't reset it.
- **Set an Azure budget alert.** In the Azure portal go to **Cost Management > Budgets**, and create a monthly budget (for example £10) on the subscription, with email alerts at 50%, 80% and 100%. A budget only alerts: it doesn't stop spending.
- **Optionally lower the deployment's quota.** In Azure AI Foundry, open each deployment (chat and embeddings) and reduce its tokens-per-minute limit. That is a hard ceiling on how fast money can be spent.

## 1. Database: Neon (free)

1. Create a project at [neon.tech](https://neon.tech) and copy its connection string.
2. Change the scheme for SQLAlchemy: `postgresql://...` becomes `postgresql+psycopg://...`. Keep the `?sslmode=require` part.
3. Create the tables from your machine, at the repo root. The variable overrides `.env` for this one command:

   ```powershell
   $env:DATABASE_URL = "postgresql+psycopg://<user>:<password>@<host>/<db>?sslmode=require"
   alembic upgrade head
   Remove-Item Env:DATABASE_URL
   ```

## 2. Search: Azure AI Search free tier

Check the pricing tier of your current search service in the Azure portal. If it's already **Free**, reuse it and skip this step.

Otherwise:

1. Create a new Azure AI Search service with the **Free** tier. Each subscription can have one.
2. Copy its endpoint and an admin key into your local `.env` (`AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_API_KEY`), keeping `AZURE_SEARCH_INDEX`.
3. Create and fill the index:

   ```powershell
   python -c "from app.rag.search_index import create_search_index; create_search_index()"
   python -m app.rag.index_documents
   ```

4. Check it with `python -m app.rag.retriever`, then delete the old paid service if nothing else uses it.

## 3. Create the Space

1. Create a free account at [huggingface.co](https://huggingface.co) and a **Space**: choose **Docker** as the SDK, a blank template, and the free CPU hardware.
2. In the Space, open **Settings > Variables and secrets** and add these as **secrets**:

   | Secret | Value |
   |---|---|
   | `DATABASE_URL` | The Neon URL from step 1 |
   | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT` | Chat model resource |
   | `AZURE_OPENAI_EMBEDDING_ENDPOINT`, `AZURE_OPENAI_EMBEDDING_KEY`, `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Embeddings resource |
   | `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_API_KEY`, `AZURE_SEARCH_INDEX` | Search service from step 2 |

3. Add these **variables**, so that libraries write to a folder the Space's non-root user can write to, and Gradio doesn't send usage statistics:

   | Variable | Value |
   |---|---|
   | `HF_HOME` | `/tmp/hf` |
   | `GRADIO_ANALYTICS_ENABLED` | `False` |

4. Optionally add these **variables**:

   | Variable | Default | What it does |
   |---|---|---|
   | `ENVIRONMENT` | `development` | Shown by `/health`; set `production` |
   | `RATE_LIMIT_PER_MINUTE` | `5` | Questions per visitor per minute |
   | `RATE_LIMIT_PER_DAY` | `200` | Questions per day that call Azure, across all visitors |
   | `CACHE_VERSION` | `1` | Part of the answer cache key (see below) |
   | `TRUSTED_PROXY_HOPS` | `1` | Proxies in front of the app that add to `X-Forwarded-For` (see step 5) |

   **Raise `CACHE_VERSION` after any prompt, model or index change** (for example from `1` to `2`). Answers are cached forever under the version they were made with; without the change, visitors keep getting the old answers. Older rows are ignored rather than deleted, so setting the old value again brings them back.

## 4. Upload the code

Log in once with a Hugging Face access token that has write permission:

```powershell
hf auth login
```

Then, from the repo root, upload only what the image needs, plus the Space card:

```powershell
hf upload <your-username>/<space-name> . . --repo-type space --include "app/**" --include requirements.txt --include Dockerfile --exclude "**/__pycache__/**"
hf upload <your-username>/<space-name> deploy/huggingface/README.md README.md --repo-type space
```

The Space builds the image and starts it. The first build takes a few minutes. Then open `https://<your-username>-<space-name>.hf.space`; it redirects to `/ui`.

To deploy a change later, run the same two commands again. If the change includes a new Alembic migration, run step 1's `alembic upgrade head` against Neon first.

## 5. After the first deploy: set TRUSTED_PROXY_HOPS

The per-visitor limit identifies a visitor by the `X-Forwarded-For` entry that Hugging Face's proxy adds; entries further left are sent by the visitor and can be faked.

1. Ask one question on the Space.
2. In the **Logs** tab, find `X-Forwarded-For contains N address(es)`. The app logs only the count, never the addresses.
3. If N is 1, keep the default. If N is larger, open the page in a private window with no VPN: the number of addresses is the number of proxies, so set `TRUSTED_PROXY_HOPS` to N. If you're unsure, leave it at 1. The daily cap protects your spend either way.

## Notes

- **The Space sleeps** after a period without visitors on free hardware. The next visitor waits while it starts again.
- **The cache stores every question forever**, keyed on the question (whitespace tidied, case kept) and `CACHE_VERSION`. See step 3 for when to raise the version.
- **Logs** are in the Space's **Logs** tab. Failed answers are logged there with their stack trace; the visitor only sees a generic message.
