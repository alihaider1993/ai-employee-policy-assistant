from langchain_openai import AzureOpenAIEmbeddings

from app.core.config import settings


embeddings = AzureOpenAIEmbeddings(
    azure_endpoint=settings.azure_openai_embedding_endpoint,
    api_key=settings.azure_openai_embedding_key,
    azure_deployment=settings.azure_openai_embedding_deployment,
    api_version="2023-05-15",
)