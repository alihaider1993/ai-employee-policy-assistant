# Deploying to Azure Container Apps

## How the app is hosted

| Part | What | Notes |
|---|---|---|
| App | Container App `employee-policy-api` in environment `employee-policy-env`, resource group `employee-policy-rg` (uksouth) | Consumption-only environment, no Log Analytics workspace. Scales to zero when idle, at most 1 replica; 0.5 vCPU / 1 GiB; single revision mode |
| Ingress | External, HTTPS only, target port 8000 | `/` redirects to the page at `/ui`; the API is `/ask`, documented at `/docs` |
| Image | `ghcr.io/alihaider1993/employee-policy-assistant:<short commit sha>` | Public package on GitHub Container Registry, so the app pulls it without credentials |
| Database | Neon Postgres (free) | The answer cache and the daily question count. Migrations are not run on start |
| Search | Azure AI Search `employee-policy-search`, Free tier | In resource group `employee-policy-assistant` |
| Models | Azure OpenAI `gpt-4o` and `text-embedding-3-small` | The only part with a running cost: pay per token |

Settings on the app:

- **Secrets** (referenced with `secretRef`): `database-url`, `openai-key`, `embedding-key`, `search-key`.
- **From `.env`** (plain): the Azure OpenAI and embedding endpoints and deployment names, `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_INDEX`.
- **Fixed by `deploy.py`**: `ENVIRONMENT=production`, `GRADIO_ANALYTICS_ENABLED=False`, `FORWARDED_ALLOW_IPS=*` (so the app sees HTTPS behind the ingress proxy), `TRUSTED_PROXY_HOPS=1` (confirmed from the logs), `RATE_LIMIT_PER_MINUTE=5`, `RATE_LIMIT_PER_DAY=30`, and `CACHE_VERSION` (from `--cache-version`; without it, the live app's current value is kept, and a new app gets `1`).

## Deploy a new version

You need Docker running, `docker login ghcr.io` with a GitHub token that has `write:packages`, `az login`, and the virtual environment active. Run everything from the repo root in PowerShell.

1. **Commit and push the code**, and check the working tree is clean. Docker builds the files on disk, not the commit, so uncommitted changes would end up in an image labelled with a commit that doesn't contain them.

   ```powershell
   git status
   ```

2. **Build and push an image tagged with the short commit sha:**

   ```powershell
   $sha = git rev-parse --short HEAD
   $image = "ghcr.io/alihaider1993/employee-policy-assistant:$sha"
   docker build --label org.opencontainers.image.source=https://github.com/alihaider1993/ai-employee-policy-assistant --label org.opencontainers.image.revision=$(git rev-parse HEAD) -t $image .
   docker push $image
   ```

   Optionally test it locally first: `docker run --rm --env-file .env -e DATABASE_URL=postgresql+psycopg://app_user:local_dev_password@host.docker.internal:5433/employee_policy -p 8000:8000 $image`, then open `http://localhost:8000`. The `DATABASE_URL` override is needed because `localhost` inside the container is the container itself.

3. **If the version adds an Alembic migration**, apply it to Neon before deploying:

   ```powershell
   $env:DATABASE_URL = "postgresql+psycopg://<user>:<password>@<host>/<db>?sslmode=require"
   alembic upgrade head
   Remove-Item Env:DATABASE_URL
   ```

4. **Deploy the image:**

   ```powershell
   python deploy/azure/deploy.py --image-tag $sha
   ```

   Add `--cache-version <n>` if the version changes a prompt, the model or the search index (see below). The script asks for the Neon `DATABASE_URL` with a hidden prompt, asks you to confirm, and prints the app URL when the new revision is running. `--dry-run` shows the commands with secrets masked, without reading `.env` or calling Azure. The script is safe to re-run.

5. **Check it:** open the URL, ask a question, and confirm the answer has sources. Then check the logs (below) for errors.

## When to raise the cache version

Answers are cached forever, keyed on the question and `CACHE_VERSION`. After any change to a prompt, the model or the search index, deploy with a higher `--cache-version` (for example `2`), or visitors keep getting answers from the old version. Older rows are ignored rather than deleted, so deploying with the old number again brings them back.

When you leave out `--cache-version`, `deploy.py` keeps the version currently set on the live app (and prints which one it used), so a routine deploy never switches back to older cached answers. Only a brand-new app gets `1`.

## Roll back

Deploy the previous image again, passing the cache version it used. Without `--cache-version`, the live app's current (newer) version would be kept, and the old code would serve answers cached by the newer one.

```powershell
python deploy/azure/deploy.py --image-tag <previous sha> --cache-version <its version>
```

`az containerapp revision list -g employee-policy-rg -n employee-policy-api -o table` shows the revisions and their images. If the version you're rolling back from added a migration, check that the older code still works with the newer schema first.

## Logs and troubleshooting

```powershell
az containerapp logs show -g employee-policy-rg -n employee-policy-api --type console --tail 100
az containerapp logs show -g employee-policy-rg -n employee-policy-api --type system --tail 100
```

Console logs are the app's output; system logs show image pulls, scaling and crashes. With no Log Analytics workspace, logs aren't kept: they can only be read from a running replica, so open the app first if it has scaled to zero.

- **A secret changed but the app still uses the old value:** re-running `deploy.py` with only a new secret value doesn't restart the running revision. Run `az containerapp revision restart -g employee-policy-rg -n employee-policy-api --revision <name>`.
- **The first request after a quiet spell is slow:** the app scales to zero and takes about 20 seconds to start.
- **"The demo has reached its daily question limit":** `RATE_LIMIT_PER_DAY` questions that called Azure have been asked today (UTC). Cached answers are still served.

## Costs

The app scales to zero, so it costs nothing while idle, and light use stays within the Container Apps monthly free allowance. Neon and the search service are free tiers. Azure OpenAI is billed per token; the daily cap limits it, and an Azure budget alert warns you if spending rises. Lowering the deployments' tokens-per-minute limit is a hard ceiling.
