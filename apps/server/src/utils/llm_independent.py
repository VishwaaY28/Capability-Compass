"""
Independent LLM Thinking Module

Handles AI reasoning and query processing using Azure OpenAI LLM provider WITHOUT database context.
This module provides independent thinking capabilities for analyzing user queries based on
the LLM's own knowledge, without relying on vertical data from the database.
"""

import logging
import os
import time
from typing import Dict, Any, Tuple
from env import env
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from openai import AzureOpenAI
from openai import OpenAI

logger = logging.getLogger(__name__)

try:
    _has_azure = True
except ImportError:
    _has_azure = False
    logger.warning("Azure libraries not installed. Install them to use Azure OpenAI provider.")


class AzureOpenAIIndependentClient:
    """
    Azure OpenAI Client for independent chain-of-thought reasoning without database context.
    Provides thinking capability to reason through queries using LLM's own knowledge and Azure credentials.
    """

    def __init__(self):
        self._client = None
        self._config = None
        self._last_system_prompt = None

    def _load_config(self) -> Dict[str, Any]:
        """Load Azure OpenAI API configuration from Key Vault with retry logic"""
        if self._config is None:
            try:
                # Retry configuration for credential initialization
                max_retries = 3
                retry_delay = 0.5  # Start with 0.5 seconds
                last_error = None
                
                for attempt in range(max_retries):
                    try:
                        # Initialize credential and Key Vault client
                        credential = DefaultAzureCredential()
                        key_vault_url = "https://fstodevazureopenai.vault.azure.net/"
                        kv_client = SecretClient(vault_url=key_vault_url, credential=credential)
                        
                        # Retrieve secrets from Key Vault
                        # api_key = kv_client.get_secret("llm-api-key").value
                        # endpoint = kv_client.get_secret("llm-base-endpoint").value
                        # deployment = kv_client.get_secret("llm-mini").value
                        api_version = kv_client.get_secret("llm-mini-version").value
                        api_key = kv_client.get_secret("llm-api-key").value
                        endpoint = kv_client.get_secret("llm-base-endpoint").value
                        deployment = kv_client.get_secret("llm-5").value
                        # Strip whitespace from all values
                        api_key = api_key.strip() if api_key else None
                        endpoint = endpoint.strip() if endpoint else None
                        deployment = deployment.strip() if deployment else None
                        api_version = api_version.strip() if api_version else None
                        
                        if not all([api_key, endpoint, deployment, api_version]):
                            logger.warning(f"One or more required Azure secrets are missing (attempt {attempt + 1}/{max_retries})")
                            logger.warning(f"API Key present: {bool(api_key)}, Endpoint: {bool(endpoint)}, Deployment: {bool(deployment)}, API Version: {bool(api_version)}")
                            raise ValueError("Missing required Azure Key Vault secrets")

                        self._config = {
                            "api_key": api_key,
                            "endpoint": endpoint,
                            "deployment": deployment,
                            "api_version": api_version,
                        }
                        logger.info(f"Azure OpenAI config loaded - Endpoint: {endpoint}, Deployment: {deployment}, API Version: {api_version}")
                        break  # Success, exit retry loop
                        
                    except Exception as e:
                        last_error = e
                        if attempt < max_retries - 1:
                            logger.warning(f"Failed to load Azure config (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}")
                            time.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                        else:
                            logger.error(f"Failed to load Azure config after {max_retries} attempts: {e}")
                            raise ValueError(f"Failed to load Azure configuration: {e}")

            except Exception as e:
                logger.error(f"Error loading Azure Key Vault configuration: {e}")
                raise ValueError(f"Failed to load Azure configuration: {e}")

        return self._config

    def _get_client(self) -> AzureOpenAI:
        """Get or create Azure OpenAI client instance"""
        if self._client is None:
            if not _has_azure:
                raise ImportError(
                    "Azure libraries are not installed. Install them with: pip install azure-identity azure-keyvault-secrets openai"
                )
            config = self._load_config()
            
            # Ensure endpoint doesn't have trailing slashes or path
            endpoint = config["endpoint"]
            base_url = endpoint.split("/chat/completions")[0]
            self._client = AzureOpenAI(
                api_key=config["api_key"],
                api_version=config["api_version"],
                azure_endpoint=endpoint
            )
            # self._client = OpenAI(
            #     api_key=config["api_key"],
            #     base_url=base_url
            # )
            logger.info(f"Azure OpenAI client initialized successfully with endpoint: {endpoint}")

        return self._client

    def get_last_system_prompt(self) -> str:
        """Get the last system prompt used"""
        return self._last_system_prompt or ""

    def think_and_analyze(
        self,
        query: str,
        vertical: str,
        vertical_data: Dict[str, Any] = None,
    ) -> Tuple[str, str]:
        """
        Use Azure OpenAI LLM to think through a query with optional vertical context.
        The LLM can use provided vertical data alongside its own knowledge and reasoning.

        Args:
            query: User's query/question
            vertical: Selected vertical/domain
            vertical_data: Optional data structure containing capabilities, processes, etc.

        Returns:
            Tuple of (thinking_process, final_result)
        """
        try:
            client = self._get_client()
            config = self._load_config()

            # Create system prompt for independent thinking
            system_prompt = self._create_system_prompt(vertical)
            # Store the system prompt for logging
            self._last_system_prompt = system_prompt

            # Create user message with optional context
            user_message = self._create_user_message(query, vertical_data)

            # Call Azure OpenAI API with thinking enabled
            deployment = config["deployment"]
            logger.info(f"Calling Azure OpenAI API for independent analysis: {query[:50]}... (Deployment: {deployment})")
            
            try:
                response = client.chat.completions.create(
                    model=deployment,

                    reasoning_effort="high",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                )
            except Exception as api_error:
                logger.error(f"Azure API Error - Deployment: {deployment}, Error: {str(api_error)}")
                raise

            # Extract response content
            response_text = response.choices[0].message.content

            # Parse thinking and result from response
            thinking, result = self._parse_response(response_text)

            logger.info(f"Successfully processed independent query: {query[:50]}...")
            return thinking, result

        except Exception as e:
            logger.error(f"Error in think_and_analyze: {e}")
            raise

    def stream_think_and_analyze(
        self,
        query: str,
        vertical: str,
        vertical_data: Dict[str, Any] = None,
    ):
        """
        Stream the thinking process and analysis result with optional vertical context.
        This allows the frontend to see thinking as it happens.

        Args:
            query: User's query/question
            vertical: Selected vertical/domain
            vertical_data: Optional data structure containing capabilities, processes, etc.

        Yields:
            Tuple of (chunk_type, content) where chunk_type is 'thinking' or 'result'
        """
        try:
            client = self._get_client()
            config = self._load_config()

            system_prompt = self._create_system_prompt(vertical)
            # Store the system prompt for logging
            self._last_system_prompt = system_prompt
            user_message = self._create_user_message(query, vertical_data)

            deployment = config["deployment"]
            logger.info(f"Starting independent stream for query: {query[:50]}... (Deployment: {deployment})")

            try:
                stream = client.chat.completions.create(
                    model=deployment,

                    reasoning_effort="high",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    stream=True,
                )
            except Exception as api_error:
                logger.error(f"Azure API Error - Deployment: {deployment}, Error: {str(api_error)}")
                raise

            buffer = ""
            in_thinking = False
            thinking_started = False

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    buffer += text

                    # Check for thinking section markers
                    if "<thinking>" in buffer:
                        in_thinking = True
                        thinking_started = True
                        before, after = buffer.split("<thinking>", 1)
                        
                        # Yield any text before thinking tags
                        if before.strip():
                            yield ("text", before)
                        
                        buffer = after

                    if "</thinking>" in buffer and in_thinking:
                        thinking_text, after = buffer.split("</thinking>", 1)
                        
                        # Yield the complete thinking section
                        if thinking_text.strip():
                            yield ("thinking", thinking_text.strip())
                        
                        in_thinking = False
                        buffer = after

                    # Yield buffered result content periodically (when not in thinking)
                    if not in_thinking and len(buffer) > 100:
                        yield ("result", buffer)
                        buffer = ""

            # Yield remaining content
            if buffer:
                if in_thinking:
                    # If we're still in thinking mode, yield as thinking
                    yield ("thinking", buffer.strip())
                else:
                    # Otherwise yield as result
                    if buffer.strip():
                        yield ("result", buffer.strip())
            
            logger.info(f"Independent stream completed for query: {query[:50]}...")

        except Exception as e:
            logger.error(f"Error in stream_think_and_analyze: {e}")
            raise

    def _create_system_prompt(self, vertical: str) -> str:
        """Create system prompt for independent thinking with optional context"""
        return f"""You are an expert consultant analyzing business capabilities and processes in the {vertical} domain.

Your task is to:
1. First, think through the user's query step by step
2. Analyze the relevant capabilities and processes using your external knowledge
3. Identify the most relevant answers to the user's intent
4. Provide comprehensive insights based on all available information

If data is not available, explicitly state "This information is not available."

Structure your response as:
<thinking>
[Your step-by-step reasoning process - reference external sources]
</thinking>

[Your final analysis and recommendations - cite specific entities and elements]

Be thorough in your thinking but concise in your final answer."""

    def _create_user_message(self, query: str, vertical_data: Dict[str, Any] = None) -> str:
        """Create the user message with optional vertical context"""
        return f"""
Please provide your independent analysis for this query:

{query}

Use your domain expertise and external knowledge."""


    def _parse_response(self, response_text: str) -> Tuple[str, str]:
        """Parse the LLM response into thinking and result sections"""
        thinking = ""
        result = ""

        try:
            logger.debug(f"[Independent] Raw response length: {len(response_text)}, first 200 chars: {response_text[:200]}")
            
            if "<thinking>" in response_text and "</thinking>" in response_text:
                try:
                    thinking_start = response_text.index("<thinking>") + len("<thinking>")
                    thinking_end = response_text.index("</thinking>")
                    thinking = response_text[thinking_start:thinking_end].strip()
                    
                    # Result is everything after </thinking>
                    result = response_text[thinking_end + len("</thinking>"):].strip()
                    
                    logger.debug(f"[Independent] Successfully parsed - thinking length: {len(thinking)}, result length: {len(result)}")
                    
                    # Validate result is not empty
                    if not result:
                        logger.warning(f"[Independent] Result is empty after parsing thinking tags. Response text: {response_text[:500]}")
                        
                except (ValueError, IndexError) as parse_err:
                    logger.error(f"[Independent] Failed to parse thinking tags: {parse_err}, response: {response_text[:300]}")
                    result = response_text.strip()
                    thinking = "Analysis in progress..."
            else:
                logger.warning(f"[Independent] No thinking tags found in response. Response: {response_text[:300]}")
                result = response_text.strip()
                thinking = "Analysis completed without explicit thinking process"

        except Exception as e:
            logger.error(f"[Independent] Error parsing response: {e}", exc_info=True)
            result = response_text.strip() if response_text else ""
            thinking = "Analysis completed"

        return thinking, result


# Global instance
azure_openai_independent_client = AzureOpenAIIndependentClient()
