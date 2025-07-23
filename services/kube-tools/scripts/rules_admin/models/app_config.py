from pydantic import BaseModel


class AppConfig(BaseModel):
    SECRET_KEY: str
    MONGO_URI: str
    DATABASE_NAME: str
    COLLECTION_NAME: str
    AZURE_AD_CLIENT_ID: str
    AZURE_AD_CLIENT_SECRET: str
    AZURE_AD_TENANT_ID: str
    AZURE_AD_AUTHORITY: str
    AZURE_AD_REDIRECT_PATH: str
    AZURE_AD_SCOPE: str
    GOOGLE_CLIENT_SECRETS_FILE: str
    GOOGLE_SCOPES: str
    GOOGLE_REDIRECT_URI: str
