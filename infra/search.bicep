// The Azure AI Search service, free tier. Deploy at resource group scope:
//
//   az deployment group what-if -g employee-policy-assistant -f infra/search.bicep
//
// Indexes are data-plane objects, not ARM resources: create them with
// app/rag/search_index.py and fill them with `python -m app.rag.index_documents`.
// The free tier allows one service per subscription, 3 indexes and 50 MB of storage in total.

targetScope = 'resourceGroup'

param location string = resourceGroup().location
param searchName string = 'employee-policy-search'

resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: searchName
  location: location
  sku: {
    name: 'free'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
  }
}

output searchEndpoint string = 'https://${search.name}.search.windows.net'
