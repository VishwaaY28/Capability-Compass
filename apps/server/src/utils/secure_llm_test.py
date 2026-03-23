from openai import AzureOpenAI
from dotenv import load_dotenv
import os

load_dotenv()

OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
AZURE_OPENAI_ENDPOINT = "https://stg-secureapi.hexaware.com/api/azureai"  # e.g., https://<resource>.openai.azure.com
AZURE_OPENAI_API_KEY  = "99dc2149a91688fe-FS-Capability-Compass"   # store securely in .env or Key Vault

AZURE_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")  # <- put your deployment ID here

client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    api_version=OPENAI_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
)

resp = client.chat.completions.create(
    model=AZURE_DEPLOYMENT_NAME,  # <-- deployment name, not "gpt-4.0" unless that's your deployment id
    messages=[
        {"role": "system", "content": "You are an AI assistant."},
        {"role": "user", "content": "What is LLM?"}
    ],
    temperature=0.7,
    max_tokens=256,
    top_p=0.6,
    frequency_penalty=0.7,
)

print(resp)
print("--------------------------------------------------")
print(resp.choices[0].message.content)