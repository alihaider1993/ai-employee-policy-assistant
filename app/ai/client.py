from langchain_openai import AzureChatOpenAI

from app.core.config import settings


llm = AzureChatOpenAI(
    azure_endpoint=settings.azure_openai_endpoint,
    api_key=settings.azure_openai_api_key,
    azure_deployment=settings.azure_openai_deployment,
    api_version="2025-01-01-preview",
)