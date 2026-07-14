
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "3i Fund Portal API"
    debug: bool = False

    cors_origins: list[str] = ["http://localhost:5500", "http://127.0.0.1:5500"]

    jwt_secret: str = "CHANGE-ME-IN-PRODUCTION"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    refresh_expire_minutes: int = 43200

    onprem_base_url: str = "http://localhost:9000"
    onprem_timeout_seconds: int = 30

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "three_i_fund_portal"

    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_database: str = "DealTerms"
    pg_user: str = "postgres"
    pg_password: str = ""

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    approval_base_url: str = "http://localhost:8001"

    allow_test_login: bool = True

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
