import os
from dotenv import load_dotenv
load_dotenv()

class Settings:
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://onemarinex_user:onemarinex123!@localhost:5432/onemarinex",
    )
    SECRET_KEY = os.getenv("SECRET_KEY", "onemarinexsecret")
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 20160  # 2 weeks (14 days * 24 hours * 60 minutes)
    REFRESH_TOKEN_EXPIRE_MINUTES = int(os.getenv("REFRESH_TOKEN_EXPIRE_MINUTES", "43200"))  # 30 days
    APP_NAME = "OneMarinex API"

    # --- WhatsApp Business Cloud API (Meta Graph API) ---
    WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v21.0")
    WHATSAPP_DEFAULT_COUNTRY_CODE = os.getenv("WHATSAPP_DEFAULT_COUNTRY_CODE", "91")
    WHATSAPP_ENABLED = os.getenv("WHATSAPP_ENABLED", "true").lower() == "true"
    APP_PUBLIC_BASE_URL = os.getenv("APP_PUBLIC_BASE_URL", "https://heyports-56we8.ondigitalocean.app")

settings = Settings()
