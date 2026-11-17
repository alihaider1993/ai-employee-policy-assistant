// Container Apps environment and app for the Employee Policy Assistant.
// Mirrors deploy/azure/deploy.py. Deploy at resource group scope:
//
//   az deployment group what-if -g employee-policy-rg -f infra/main.bicep -p infra/main.bicepparam
//   az deployment group create  -g employee-policy-rg -f infra/main.bicep -p infra/main.bicepparam
//
// Always run what-if first. The secrets are not stored in the parameter file:
// pass them on the command line or from a key vault.

targetScope = 'resourceGroup'

param location string = resourceGroup().location
param environmentName string = 'employee-policy-env'
param appName string = 'employee-policy-api'

@description('Full image reference, for example ghcr.io/alihaider1993/employee-policy-assistant:603cdf7')
param image string

@description('Raise after any prompt, model or search index change so older cached answers are ignored.')
@minLength(1)
@maxLength(32)
param cacheVersion string

param openAiEndpoint string
param openAiDeployment string
param embeddingEndpoint string
param embeddingDeployment string
param searchEndpoint string
param searchIndex string

param rateLimitPerMinute string = '5'
param rateLimitPerDay string = '30'

@secure()
param databaseUrl string
@secure()
param openAiKey string
@secure()
param embeddingKey string
@secure()
param searchKey string

// Consumption-only environment, no Log Analytics workspace: console logs are read
// with `az containerapp logs show`.
resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  properties: {
    zoneRedundant: false
  }
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      secrets: [
        { name: 'database-url', value: databaseUrl }
        { name: 'openai-key', value: openAiKey }
        { name: 'embedding-key', value: embeddingKey }
        { name: 'search-key', value: searchKey }
      ]
    }
    template: {
      containers: [
        {
          name: appName
          image: image
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'ENVIRONMENT', value: 'production' }
            { name: 'GRADIO_ANALYTICS_ENABLED', value: 'False' }
            // Trust the ingress proxy's X-Forwarded-* headers so the app sees https.
            { name: 'FORWARDED_ALLOW_IPS', value: '*' }
            { name: 'TRUSTED_PROXY_HOPS', value: '1' }
            { name: 'RATE_LIMIT_PER_MINUTE', value: rateLimitPerMinute }
            { name: 'RATE_LIMIT_PER_DAY', value: rateLimitPerDay }
            { name: 'CACHE_VERSION', value: cacheVersion }
            { name: 'AZURE_OPENAI_ENDPOINT', value: openAiEndpoint }
            { name: 'AZURE_OPENAI_DEPLOYMENT', value: openAiDeployment }
            { name: 'AZURE_OPENAI_EMBEDDING_ENDPOINT', value: embeddingEndpoint }
            { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: embeddingDeployment }
            { name: 'AZURE_SEARCH_ENDPOINT', value: searchEndpoint }
            { name: 'AZURE_SEARCH_INDEX', value: searchIndex }
            { name: 'DATABASE_URL', secretRef: 'database-url' }
            { name: 'AZURE_OPENAI_API_KEY', secretRef: 'openai-key' }
            { name: 'AZURE_OPENAI_EMBEDDING_KEY', secretRef: 'embedding-key' }
            { name: 'AZURE_SEARCH_API_KEY', secretRef: 'search-key' }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
        rules: [
          {
            name: 'http'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

output appUrl string = 'https://${app.properties.configuration.ingress.fqdn}'
