import os
from dotenv import load_dotenv

load_dotenv()

env = {
    "HOST": os.getenv("HOST", "127.0.0.1"),
    "PORT": os.getenv("PORT", "8000"),
    "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
    "SECRET_KEY": os.getenv("SECRET_KEY", "your-secret-key"),
    "KEY_VAULT_URL": os.getenv("KEY_VAULT_URL", "https://KV-fs-to-autogen.vault.azure.net/"),
    # Azure OpenAI Configuration
    "AZURE_OPENAI_API_KEY": os.getenv("AZURE_OPENAI_API_KEY"),
    "AZURE_OPENAI_ENDPOINT": os.getenv("AZURE_OPENAI_ENDPOINT"),
    "AZURE_OPENAI_API_VERSION": os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
    "AZURE_OPENAI_DEPLOYMENT": os.getenv("AZURE_OPENAI_DEPLOYMENT"),
}