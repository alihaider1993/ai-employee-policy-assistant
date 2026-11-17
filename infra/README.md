# Infrastructure as code

Bicep for the Azure resources this app runs on. Nothing here has been applied: the live
app was created by `deploy/azure/deploy.py`, and these files describe the same resources.

| File | Resources |
|---|---|
| `main.bicep` | Container Apps environment `employee-policy-env` (Consumption only, no Log Analytics) and the app `employee-policy-api` (0.5 vCPU, 1 GiB, 0 to 1 replicas, external HTTPS ingress on port 8000, four secrets, the same settings as `deploy.py`) |
| `search.bicep` | Azure AI Search `employee-policy-search`, free tier |

Not covered, and why:

- **Azure OpenAI.** The accounts and model deployments already exist and are referenced by endpoint and deployment name, so the template takes those as parameters.
- **Search indexes.** They are data-plane objects, not ARM resources. Create them with `app/rag/search_index.py` and fill them with `python -m app.rag.index_documents`.
- **The Neon database.** It is hosted outside Azure.

## Check a change

```powershell
az bicep build --file infra/main.bicep --stdout > $null     # syntax only, touches nothing
az deployment group what-if -g employee-policy-rg -f infra/main.bicep `
  -p image=ghcr.io/alihaider1993/employee-policy-assistant:<sha> cacheVersion=<n> `
     openAiEndpoint=<...> openAiDeployment=<...> embeddingEndpoint=<...> embeddingDeployment=<...> `
     searchEndpoint=<...> searchIndex=<...> `
     databaseUrl=<...> openAiKey=<...> embeddingKey=<...> searchKey=<...>
```

`what-if` only reads, but always read its output before running `az deployment group create`.
Adopting this template for the live resources should show no changes except any drift;
if `what-if` wants to delete or recreate the environment, stop and compare the two
definitions first.

## Secrets

The four `@secure()` parameters (`databaseUrl`, `openAiKey`, `embeddingKey`, `searchKey`)
are never written to a parameter file. Pass them on the command line, or read them from a
key vault.
