import logging
from openai import AzureOpenAI
from typing import List, Dict, Any, Optional
from env import env
import json
import re
import ast
from utils.llm_call_logger import get_llm_call_logger
from config.azure_clients import get_azure_openai_client, get_azure_config

try:
    import yaml  # type: ignore
    _has_yaml = True
except Exception:
    yaml = None
    _has_yaml = False
logger = logging.getLogger(__name__)

def count_tokens(text: str, model: str = "gpt-4") -> int:
    """Count tokens for Azure OpenAI model (rough estimation)"""
    try:
        # Rough estimation: 1 token ≈ 4 characters
        return len(text) // 4
    except Exception as e:
        logger.warning(f"Failed to count tokens: {e}")
        return len(text) // 4


class AzureOpenAIClient:
    def __init__(self):
        pass

    def _get_client(self) -> AzureOpenAI:
        """Get Azure OpenAI client instance (initialized at server startup)."""
        return get_azure_openai_client()
    
    def _load_config(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get cached Azure configuration (loaded at server startup)."""
        config = get_azure_config()
        # Apply settings overrides if provided
        if settings:
            api_version = settings.get("apiVersion", config.get("api_version"))
            model = settings.get("model", config.get("deployment"))
            return {
                "api_key": config.get("api_key"),
                "endpoint": config.get("endpoint"),
                "api_version": api_version,
                "model": model,
            }
        return {
            "api_key": config.get("api_key"),
            "endpoint": config.get("endpoint"),
            "api_version": config.get("api_version"),
            "model": config.get("deployment"),
        }

    async def generate_content(
            self,
            prompt: str,
            context_sections: List[str] = None,
    ) -> Dict[str, Any]:
        # Kept for backward compatibility: small wrapper around the unified generator.
        return await self.generate_json(prompt_text=prompt, purpose="general", context_sections=context_sections)

    async def generate_processes(
            self,
            capability_name: str,
            description: str,
            domain: str,
            process_type: str,
            prompt_text: str,
    ) -> Dict[str, Any]:
        """Generate processes for a capability in a specific domain with a given process type using Azure OpenAI LLM"""
        return await self.generate_json(prompt_text=prompt_text, purpose="processes", capability_name=capability_name,
                                        domain=domain, process_type=process_type, capability_description=description)

    async def generate_json(self, *, prompt_text: str, purpose: str = "general",
                            context_sections: Optional[List[str]] = None, capability_name: Optional[str] = None,
                            domain: Optional[str] = None, process_type: Optional[str] = None, 
                            capability_description: Optional[str] = None) -> Dict[str, Any]:
        """Unified generator that requests strict JSON and parses robustly using Azure OpenAI.

        - prompt_text: final user-level prompt describing what to generate
        - purpose: optional label (e.g., 'processes') used for logging
        - context_sections: optional list of context snippets to include
        - capability_name: optional capability name for LLM context
        - domain: optional domain name for LLM context
        - process_type: optional process type for LLM context
        - capability_description: optional capability description for LLM context
        """
        try:
            # Import settings manager here to avoid circular imports
            from config.llm_settings import llm_settings_manager
            settings = llm_settings_manager.get_all_settings()

            # Use vault URL from user-configured settings so secret retrieval
            # fails when the vault is misconfigured (preventing generation)
            vault_url = settings.get("vaultName")
            if vault_url:
                self.key_vault_url = vault_url
                config = self._load_config(settings)
            client = self._get_client()

            workspace_content = ""
            if context_sections:
                workspace_content += "\n=== CONTENT SECTIONS ===\n"
                for i, section in enumerate(context_sections, 1):
                    workspace_content += f"\n{i}. {section}\n"

            example_output = json.dumps(
{
  "processes": [
    {
      "name": "Client Onboarding &amp; KYC",
      "category": "Front Office",
      "description": "",
      "sub_processes": [
        {
          "name": "Account Setup",
          "category": "Front Office",
          "description": ""
        },
        {
          "name": "Internal Approvals",
          "category": "Front Office",
          "description": ""
        },
      ]
    },
    {
      "name": "Compliance Monitoring",
      "category": "Middle Office",
      "description": "",
      "sub_processes": [
        {
          "name": "Pre-Trade Checks",
          "category": "Middle Office",
          "description": ""
        },
      ]
    },
    {
      "name": "Trade Settlement",
      "category": "Back Office",
      "description": "",
      "sub_processes": [
        {
          "name": "Trade Matching",
          "category": "Back Office",
          "description": ""
        },
        {
          "name": "Broker/Custodian Confirmation",
          "category": "Back Office",
          "description": ""
        },
        {
          "name": "Exception &amp; Break Resolution",
          "category": "Back Office",
          "description": ""
        }
      ]
    }
  ]
}
, indent=2)

# Create conditional system prompt based on process_type
            if process_type == 'subprocess':
                system_prompt = (
                    f"You are a Senior Enterprise Architect and Process Subject Matter Expert (SME) in the **{domain}** domain, specializing in breaking down business processes into detailed subprocesses."
                    f"\n\n## Task:\n"
                    f"Generate a **comprehensive list of detailed subprocesses** for the parent process **'{capability_name}'** (Description: {capability_description}) within the **{domain}** domain."
                    f"\n\n## Input Variables:\n"
                    f"- **domain**: {domain}\n"
                    f"- **process_name**: {capability_name}\n"
                    f"- **process_description**: {capability_description}\n"
                    f"\n\n## Requirements:\n"
                    f"- The list must be **comprehensive**, capturing all relevant, detailed subprocesses that make up the parent process. **Do not impose a limit on the number of subprocesses.**"
                    f"- Each subprocess must have a **Name**, a **Category** (Front/Middle/Back Office), and a detailed **Description** of the specific activities."
                    f"- The **Category** must be one of: **'Front Office'**, **'Middle Office'**, or **'Back Office'**."
                    f"- Base subprocesses strictly on standard industry practices for the specified domain and process."
                    f"- If the process cannot be broken down into meaningful subprocesses, return: {{'error': 'Unable to generate meaningful subprocesses for {capability_name} in {domain}'}}\n"
                    f"\n\n## Output Format:\n"
                    f"Return the data as a valid JSON object matching the schema below. The output must be an array of subprocess objects."
                    f"\n\n### JSON Schema:\n"
                    f"""
                                        {{
                                          "subprocesses": [
                                            {{
                                              "name": "string (detailed subprocess name)",
                                              "category": "string (Front Office | Middle Office | Back Office)",
                                              "description": "string (detailed description of subprocess activities)"
                                            }},
                                            // ... additional subprocess objects
                                          ]
                                        }}
                    """
                )
            else:
                system_prompt = (
                    f"You are a Senior Enterprise Architect and Process Subject Matter Expert (SME) in the **{domain}** domain, specializing in classifying business capabilities."
                    f"\n\n## Task:\n"
                    f"Generate a **comprehensive list of high-level Business Capabilities (Processes)** for the sub-vertical **'{capability_name}'** within the **{domain}** domain. The processes must be categorized by their **Process Type** (Core or Support)."
                    f"\n\n## Input Variables:\n"
                    f"- **domain**: {domain}\n"
                    f"- **subvertical_name**: {capability_name},{capability_description}\n"
                    f"- **process_type_filter**: {process_type} (Filter: Only generate processes matching this type: 'Core' or 'Support')"
                    f"\n\n## Requirements:\n"
                    f"- The list must be **comprehensive**, capturing all relevant, high-level capabilities in the specified sub-vertical and matching the `{process_type}` filter. **Do not impose a limit on the number of processes.**"
                    f"- Each capability must have a **Name** (Business Process), a **Category** (Front/Middle/Back Office), a **Type** (Core/Support), and a detailed **Description** (Activities and Description)."
                    f"- The **Category** must be one of: **'Front Office'**, **'Middle Office'**, or **'Back Office'**."
                    f"- The **Type** must strictly match the `{process_type}` provided ('Core' or 'Support')."
                    f"- Do not invent processes; base them strictly on standard industry practices for Enterprise Architecture in the specified domain and sub-vertical."
                    f"- If the domain/sub-vertical combination is not recognized or has no relevant processes for the specified type, return: {{'error': 'No relevant {process_type} capabilities found for {capability_name} in {domain}'}}\n"
                    f"\n\n## Output Format:\n"
                    f"Return the data as a valid JSON object matching the schema below. The output must be an array of process objects."
                    f"\n\n### JSON Schema:\n"
                    f"""
                                        {{
                                          "processes": [
                                            {{
                                              "name": "string (e.g., Market research & strategy development,
    • Deal origination & sourcing,
    • Investment screening & initial evaluation,
    • Due Diligence,
    • Financial Analysis & Deal Structuring,
    • Transaction Execution & Closing)",
                                              "category": "string (Front Office | Middle Office | Back Office)",
                                              "process_type": "string (Core | Support)",
                                              "description": "string (description of activities)"
                                            }},
                                            // ... additional process objects
                                          ]
                                        }}
                    """
                )


            response = client.chat.completions.create(
                model=config["model"],
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt_text}
                ],
                frequency_penalty=0.0
            )
            generated = response.choices[0].message.content.strip()

            logger.debug(f"Raw LLM response (first 2000 chars):\n{generated[:2000]}")

            def _clean_candidate(text: str) -> str:
                s = text

                s = re.sub(r"```(?:json|yaml)?\n", "", s)
                s = re.sub(r"```", "", s)
                s = s.replace('`', '')

                s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
                s = re.sub(r"\*([^*]+)\*", r"\1", s)

                match = re.search(r'[{\[]', s)
                if match:
                    start = match.start()
                    s = s[start:]

                try:
                    import html
                    s = html.unescape(s)
                except Exception:
                    pass
                # CRITICAL: Fix double-escaped quotes FIRST: ""key"" -> "key"
                s = re.sub(r'""([^"]*?)""', r'"\1"', s)
                # Normalize all types of quotes to double quotes
                s = s.replace('\u201c', '"').replace('\u201d', '"')  # Smart double quotes
                s = s.replace('\u2018', '"').replace('\u2019', '"')  # Smart single quotes
                s = s.replace('\u201e', '"').replace('\u201f', '"')  # Double low-9 quotes
                s = s.replace('\u2039', '"').replace('\u203a', '"')  # Guillemets
                s = s.replace('«', '"').replace('»', '"')  # French quotes
                # Remove control characters early
                s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)
                # Convert remaining single quotes to double quotes
                s = s.replace("'", '"')
                # Fix escaped quotes
                s = s.replace('\\"', '"')
                # Fix double double quotes (again, in case of complex patterns)
                s = re.sub(r'""\s*([^"\n\r]+?)\s*""', r'"\1"', s)
                # Remove trailing commas in objects/arrays
                s = re.sub(r',\s*(?=[}\]])', '', s)
                # Fix missing colons after quoted keys: "key" {value -> "key": {value
                s = re.sub(r'"([^"]+)"\s*([{[])', r'"\1": \2', s)
                # Fix missing colons: "key" "value" -> "key": "value"
                s = re.sub(r'"([^"]+)"\s+"', r'"\1": "', s)
                # Fix unquoted string values (simple heuristic)
                s = re.sub(r': ([A-Za-z][A-Za-z0-9\s&\-]*?)([,}])', r': "\1"\2', s)
                # Handle truncated strings: close any unclosed quoted string at the end
                if s.rstrip().endswith('"') is False and s.rstrip()[-1] not in '}]':
                    # Find the last unclosed quote
                    last_quote = s.rfind('"')
                    if last_quote != -1:
                        after_quote = s[last_quote + 1:].rstrip()
                        if after_quote and not after_quote.startswith(','):
                            s = s[:last_quote + 1] + after_quote.rstrip(',') + '"'
                # Fix incomplete JSON by closing unclosed structures
                open_braces = s.count('{') - s.count('}')
                open_brackets = s.count('[') - s.count(']')
                s = s.rstrip(',').rstrip() + '}' * open_braces + ']' * open_brackets
                return s

            tried = []
            parsed = None

            # 1) Strict JSON
            try:
                parsed = json.loads(generated)
                tried.append('json(strict)')
            except Exception as primary_err:
                tried.append('json(strict) failed')

                # 2) Clean minimally and try json.loads
                candidate = _clean_candidate(generated).strip()
                logger.debug(f"Cleaned candidate (first 2000 chars):\n{candidate[:2000]}")
                try:
                    parsed = json.loads(candidate)
                    tried.append('json(cleaned)')
                except Exception as clean_err:
                    tried.append(f'json(cleaned) failed: {str(clean_err)[:100]}')
                    logger.debug(f"Clean parse failed: {clean_err}")

                # 3) YAML loader
                if parsed is None and _has_yaml:
                    try:
                        parsed = yaml.safe_load(candidate)
                        tried.append('yaml.safe_load')
                    except Exception:
                        tried.append('yaml failed')

                # 4) ast.literal_eval fallback (convert JS literals to Python)
                if parsed is None:
                    try:
                        candidate_py = candidate.replace('true', 'True').replace('false', 'False').replace('null',
                                                                                                           'None')
                        parsed = ast.literal_eval(candidate_py)
                        tried.append('ast.literal_eval')
                        # Normalize list -> wrapped dict when appropriate
                        if isinstance(parsed, (list, tuple)):
                            parsed = {"Core Processes": list(parsed)}
                    except Exception as ast_err:
                        tried.append(f'ast failed: {ast_err}')

                if parsed is None:
                    logger.error(
                        "Failed to parse LLM response. primary_err=%s tried=%s generated_content_snippet=%s",
                        str(primary_err), tried, generated[:2000]
                    )
                    raise ValueError(f"Failed to parse LLM response as JSON: {primary_err}; tried={tried}")

            logger.info(
                f"Generated ({purpose}) for capability '{capability_name or ''}' in domain '{domain or ''}': parsed keys={list(parsed.keys()) if isinstance(parsed, dict) else type(parsed)}")

            # Log the LLM call
            llm_logger = get_llm_call_logger()
            llm_logger.log_call(
                model_name=config["model"],
                domain=domain,
                capability_name=capability_name,
                user_prompt=prompt_text,
                status="success"
            )

            return {"status": "success", "data": parsed, "raw": generated, "capability_name": capability_name}

        except Exception as e:
            # Log the failed LLM call
            try:
                llm_logger = get_llm_call_logger()
                llm_logger.log_call(
                    model_name=config.get("model", "unknown") if 'config' in locals() else "unknown",
                    domain=domain,
                    capability_name=capability_name,
                    user_prompt=prompt_text if 'prompt_text' in locals() else None,
                    status="failed"
                )
            except Exception as log_err:
                logger.warning(f"Failed to log LLM call error: {log_err}")
            
            logger.error(f"Error generating JSON ({purpose}): {str(e)}")
            raise Exception(f"Process generation failed: {str(e)}")


azure_openai_client = AzureOpenAIClient()
