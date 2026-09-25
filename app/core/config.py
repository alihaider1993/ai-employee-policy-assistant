from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "AI Employee Policy Assistant"
    app_version: str = "0.1.0"
    environment: str = "development"

    database_url: str

    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_deployment: str
    
    azure_openai_embedding_endpoint: str
    azure_openai_embedding_key: str
    azure_openai_embedding_deployment: str
    
    azure_search_endpoint: str
    azure_search_api_key: str
    azure_search_index: str

    class Config:
        env_file = ".env"


settings = Settings()