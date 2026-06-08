"""
Centralized Azure OpenAI Clients Initialization Module

This module initializes all Azure OpenAI clients (regular, thinking, independent, embedding)
once at server startup to avoid repeated initialization overhead on every API call.

The clients are initialized with retry logic and cached as global instances.
"""

import logging
import time
from typing import Dict, Any, Optional, Tuple
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from openai import AzureOpenAI
from langchain_openai import AzureChatOpenAI

logger = logging.getLogger(__name__)

# Global client instances - initialized once at startup
_azure_openai_client: Optional[AzureOpenAI] = None
_azure_openai_thinking_client: Optional[AzureOpenAI] = None
_azure_openai_independent_client: Optional[AzureOpenAI] = None
_azure_chat_openai_client: Optional[AzureChatOpenAI] = None
_azure_embedding_client: Optional[AzureOpenAI] = None

# Configuration cache
_azure_config: Dict[str, Any] = {}
_azure_embedding_config: Dict[str, Any] = {}


def _load_azure_config(vault_url: str = "https://fstodevazureopenai.vault.azure.net/") -> Dict[str, Any]:
    """
    Load Azure OpenAI configuration from Key Vault with retry logic.
    
    Args:
        vault_url: Azure Key Vault URL
        
    Returns:
        Dictionary with api_key, endpoint, api_version, and deployment
    """
    try:
        max_retries = 3
        retry_delay = 0.5
        last_error = None
        
        for attempt in range(max_retries):
            try:
                credential = DefaultAzureCredential()
                kv_client = SecretClient(vault_url=vault_url, credential=credential)
                
                api_key = kv_client.get_secret("llm-api-key").value.strip()
                endpoint = kv_client.get_secret("llm-base-endpoint").value.strip()
                api_version = kv_client.get_secret("llm-mini-version").value.strip()
                deployment = kv_client.get_secret("llm-5").value.strip()
                
                if not all([api_key, endpoint, api_version, deployment]):
                    raise ValueError("One or more required Azure secrets are missing")
                
                logger.info(f"Azure config loaded from Key Vault (attempt {attempt + 1}/{max_retries})")
                
                return {
                    "api_key": api_key,
                    "endpoint": endpoint,
                    "api_version": api_version,
                    "deployment": deployment,
                }
                
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    logger.warning(f"Failed to load Azure config (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.error(f"Failed to load Azure config after {max_retries} attempts: {e}")
                    raise ValueError(f"Failed to load Azure configuration: {e}")
                    
    except Exception as e:
        logger.error(f"Critical error loading Azure configuration: {e}")
        raise


def _load_embedding_config() -> Dict[str, Any]:
    """
    Load Azure Embedding configuration from Key Vault.
    
    Returns:
        Dictionary with embedding api_key, endpoint, and deployment
    """
    try:
        max_retries = 3
        retry_delay = 0.5
        
        for attempt in range(max_retries):
            try:
                credential = DefaultAzureCredential()
                kv_client = SecretClient(
                    vault_url="https://kvcapabilitycompass.vault.azure.net/",
                    credential=credential
                )
                
                api_key = kv_client.get_secret("kvEmbeddingCCKey").value.strip()
                
                logger.info(f"Azure embedding config loaded from Key Vault (attempt {attempt + 1}/{max_retries})")
                
                return {
                    "api_key": api_key,
                    "endpoint": "https://fs-openai-1.openai.azure.com",
                    "deployment": "text-embedding-ada-002",
                    "api_version": "2023-05-15",
                }
                
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Failed to load embedding config (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.error(f"Failed to load embedding config after {max_retries} attempts: {e}")
                    raise ValueError(f"Failed to load embedding configuration: {e}")
                    
    except Exception as e:
        logger.error(f"Critical error loading embedding configuration: {e}")
        raise


def initialize_azure_clients():
    """
    Initialize all Azure OpenAI clients at server startup.
    This function should be called once when the FastAPI server starts.
    
    Initializes:
    - Regular AzureOpenAI client (for general LLM tasks)
    - Thinking AzureOpenAI client (for chain-of-thought reasoning)
    - Independent AzureOpenAI client (for independent reasoning)
    - AzureChatOpenAI client (for LangChain integration)
    - Embedding AzureOpenAI client (for embeddings)
    """
    global _azure_openai_client, _azure_openai_thinking_client, _azure_openai_independent_client
    global _azure_chat_openai_client, _azure_embedding_client, _azure_config, _azure_embedding_config
    
    try:
        logger.info("Initializing Azure OpenAI clients...")
        
        # Load configurations
        _azure_config = _load_azure_config()
        _azure_embedding_config = _load_embedding_config()
        
        # Clean up endpoint - remove any trailing slashes or /openai paths
        endpoint = _azure_config["endpoint"].strip()
        if endpoint.endswith("/"):
            endpoint = endpoint.rstrip("/")
        if "/openai" in endpoint:
            endpoint = endpoint.split("/openai")[0]
        
        # Initialize regular Azure OpenAI client
        _azure_openai_client = AzureOpenAI(
            api_key=_azure_config["api_key"],
            api_version=_azure_config["api_version"],
            azure_endpoint=endpoint
        )
        logger.info("✓ Regular Azure OpenAI client initialized")
        
        # Initialize thinking client (same as regular for now, but separate instance if needed)
        _azure_openai_thinking_client = AzureOpenAI(
            api_key=_azure_config["api_key"],
            api_version=_azure_config["api_version"],
            azure_endpoint=endpoint
        )
        logger.info("✓ Thinking Azure OpenAI client initialized")
        
        # Initialize independent client (same as regular for now, but separate instance if needed)
        _azure_openai_independent_client = AzureOpenAI(
            api_key=_azure_config["api_key"],
            api_version=_azure_config["api_version"],
            azure_endpoint=endpoint
        )
        logger.info("✓ Independent Azure OpenAI client initialized")
        
        # Initialize LangChain Azure Chat OpenAI client for DeepAgent.
        # ``max_retries=5`` lets the underlying OpenAI SDK ride out the
        # typical Azure TPM-bucket refill window (30-60s) on 429s using
        # exponential backoff, instead of bubbling the rate-limit error
        # up after only 2 quick retries (the SDK default).
        # ``timeout=120`` covers the long agent invocations that send
        # full document context to the model in a single request.
        _azure_chat_openai_client = AzureChatOpenAI(
            azure_deployment=_azure_config["deployment"],
            api_version=_azure_config["api_version"],
            azure_endpoint=endpoint,
            api_key=_azure_config["api_key"],
            streaming=True,
            max_retries=5,
            timeout=120,
        )
        logger.info("✓ AzureChatOpenAI client initialized")

        # Initialize embedding client
        _azure_embedding_client = AzureOpenAI(
            api_key=_azure_embedding_config["api_key"],
            api_version=_azure_embedding_config["api_version"],
            base_url=f"{_azure_embedding_config['endpoint']}/openai/deployments/{_azure_embedding_config['deployment']}"
        )
        logger.info("✓ Azure embedding client initialized")

        logger.info("All Azure OpenAI clients initialized successfully!")

    except Exception as e:
        logger.error(f"Failed to initialize Azure clients: {e}")
        raise


def get_azure_openai_client() -> AzureOpenAI:
    """Get the regular Azure OpenAI client instance (initialized at startup)."""
    global _azure_openai_client
    if _azure_openai_client is None:
        raise RuntimeError("Azure OpenAI client not initialized. Call initialize_azure_clients() at startup.")
    return _azure_openai_client


def get_azure_openai_thinking_client() -> AzureOpenAI:
    """Get the thinking Azure OpenAI client instance (initialized at startup)."""
    global _azure_openai_thinking_client
    if _azure_openai_thinking_client is None:
        raise RuntimeError("Azure OpenAI thinking client not initialized. Call initialize_azure_clients() at startup.")
    return _azure_openai_thinking_client


def get_azure_openai_independent_client() -> AzureOpenAI:
    """Get the independent Azure OpenAI client instance (initialized at startup)."""
    global _azure_openai_independent_client
    if _azure_openai_independent_client is None:
        raise RuntimeError("Azure OpenAI independent client not initialized. Call initialize_azure_clients() at startup.")
    return _azure_openai_independent_client


def get_azure_chat_openai_client() -> AzureChatOpenAI:
    """Get the LangChain Azure Chat OpenAI client instance (initialized at startup)."""
    global _azure_chat_openai_client
    if _azure_chat_openai_client is None:
        raise RuntimeError("AzureChatOpenAI client not initialized. Call initialize_azure_clients() at startup.")
    return _azure_chat_openai_client


def get_azure_embedding_client() -> AzureOpenAI:
    """Get the embedding Azure OpenAI client instance (initialized at startup)."""
    global _azure_embedding_client
    if _azure_embedding_client is None:
        raise RuntimeError("Azure embedding client not initialized. Call initialize_azure_clients() at startup.")
    return _azure_embedding_client


def get_azure_config() -> Dict[str, Any]:
    """Get the cached Azure configuration (loaded at startup)."""
    if not _azure_config:
        raise RuntimeError("Azure config not loaded. Call initialize_azure_clients() at startup.")
    return _azure_config


def get_azure_embedding_config() -> Dict[str, Any]:
    """Get the cached Azure embedding configuration (loaded at startup)."""
    if not _azure_embedding_config:
        raise RuntimeError("Azure embedding config not loaded. Call initialize_azure_clients() at startup.")
    return _azure_embedding_config