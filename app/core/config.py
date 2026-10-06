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

    # Caps on questions, to limit Azure OpenAI spend when the app is public.
    # Per minute applies per visitor to every question; per day is counted in
    # Postgres across all visitors, for questions that call Azure (not cached).
    rate_limit_per_minute: int = 5
    rate_limit_per_day: int = 200
    # Proxies in front of the app that append to X-Forwarded-For; 0 means none.
    trusted_proxy_hops: int = 1

    class Config:
        env_file = ".env"


settings = Settings()