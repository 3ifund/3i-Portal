"""
3i Fund Portal — Configuration
Loads settings from environment variables / .env file.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # FastAPI
    app_name: str = "3i Fund Portal API"
    debug: bool = False

    # CORS — frontend origin(s)
    cors_origins: list[str] = ["http://localhost:5500", "http://127.0.0.1:5500"]

    # JWT
    jwt_secret: str = "CHANGE-ME-IN-PRODUCTION"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480  # 8 hours

    # DealTermsServer base URL (all on-prem API: workflow, pricing, shares, documents)
    onprem_base_url: str = "http://localhost:9000"
    onprem_timeout_seconds: int = 30

    # MongoDB — three_i_fund_portal database
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "three_i_fund_portal"

    # PostgreSQL — DealTerms DB (on-prem)
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_database: str = "DealTerms"
    pg_user: str = "postgres"
    pg_password: str = ""

    # Twilio SMS
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    # Approval page base URL (for links in SMS)
    approval_base_url: str = "http://localhost:8001"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
