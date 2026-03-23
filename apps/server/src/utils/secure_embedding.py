from openai import AzureOpenAI
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential

# -----------------------------------------------------------
# 1. Load environment variables
# -----------------------------------------------------------
#load_dotenv()
OPENAI_API_VERSION = "2023-05-15"
AZURE_OPENAI_ENDPOINT = "https://fs-openai-1.openai.azure.com"
keyVaultName = "kvCapabilityCompass"
KVUri = f"https://kvCapabilityCompass.vault.azure.net/"
secretKeyName = "kvEmbeddingCCKey"

vCredential = DefaultAzureCredential()
kvClient = SecretClient(vault_url=KVUri, credential=vCredential)

DEPLOYMENT_NAME = "text-embedding-ada-002"  # Your model deployment name in Azure
secret_object = kvClient.get_secret(secretKeyName)
AZURE_OPENAI_API_KEY = secret_object.value

# -----------------------------------------------------------
# 2. Azure OpenAI client
# -----------------------------------------------------------
client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    api_version=OPENAI_API_VERSION,
    base_url=f"{AZURE_OPENAI_ENDPOINT}/openai/deployments/{DEPLOYMENT_NAME}"
)

# # -----------------------------------------------------------
# # 3. Request with a prompt
# -----------------------------------------------------------
# Create embeddings
response = client.embeddings.create(model=DEPLOYMENT_NAME, input="The food was delicious and the waiter...")
print(response.data[0].embedding)  # Vector representation

# from neo4j_graphrag.embeddings.openai import AzureOpenAIEmbeddings
#
# embedder = AzureOpenAIEmbeddings(
#     model="text-embedding-ada-002",          # Your embedding deployment/model
#     api_key=AZURE_OPENAI_API_KEY,
#     api_version=OPENAI_API_VERSION,
#     base_url=f"{AZURE_OPENAI_ENDPOINT}/openai/deployments/text-embedding-ada-002"
# )