import logging
import os
import google.generativeai as genai
from typing import List, Dict, Any, Optional
from env import env
import json
import re
import ast
try:
    import yaml  # type: ignore
    _has_yaml = True
except Exception:
    yaml = None
    _has_yaml = False

logger = logging.getLogger(__name__)


def count_tokens(text: str, model: str = "gemini-pro") -> int:
    """Count tokens for Gemini model"""
    try:
        # For Gemini, use the model's built-in token counting
        model_obj = genai.GenerativeModel(model)
        response = model_obj.count_tokens(text)
        return response.total_tokens
    except Exception as e:
        logger.warning(f"Failed to count tokens with Gemini: {e}")
        # Fallback: rough estimation (1 token ≈ 4 characters)
        return len(text) // 4


class GeminiClient:
    def __init__(self):
        self._config = None
        self._client = None

    def _load_config(self):
        """Load config from environment variables"""
        if self._config is None:
            api_key = ""
            model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

            self._config = {
                "api_key": api_key,
                "model": model,
            }
            if self._config.get("model"):
                logger.info(f"Loaded Gemini config - Model: {self._config['model']}")
            if self._config.get("api_key"):
                logger.info(f"API Key starts with: {self._config['api_key'][:5]}...")
        return self._config

    def _get_client(self):
        if self._client is None:
            config = self._load_config()
            if not config.get("api_key"):
                raise ValueError(
                    "Missing required Gemini config: api_key. "
                    "Provide this via environment variable GEMINI_API_KEY."
                )
            genai.configure(api_key=config["api_key"])
            self._client = config
        return self._client

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
        """Generate processes for a capability in a specific domain with a given process type using Gemini LLM
        
        If process_type == 'subprocess', generates subprocesses for a parent process.
        Otherwise, generates processes for a capability.
        """
        return await self.generate_json(
            prompt_text=prompt_text,
            purpose="processes" if process_type != 'subprocess' else "subprocesses",
            capability_name=capability_name,
            domain=domain,
            process_type=process_type,
            capability_description=description
        )

    async def generate_json(self, *, prompt_text: str, purpose: str = "general", context_sections: Optional[List[str]] = None, capability_name: Optional[str] = None, domain: Optional[str] = None, process_type: Optional[str] = None, capability_description: Optional[str] = None) -> Dict[str, Any]:
        """Unified generator that requests strict JSON and parses robustly using Gemini.

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

            # Store vaultName from settings if provided (not used by Gemini client
            # currently, but keep for consistency and future secret retrieval).
            vault_url = settings.get("vaultName")
            if vault_url:
                # attach to instance so other methods could use it later
                setattr(self, "key_vault_url", vault_url)

            config = self._load_config()
            self._get_client()

            # Use configured values from settings, fallback to defaults
            temperature = settings.get("temperature", 0.5)
            top_p = settings.get("topP", 0.9)

            workspace_content = ""
            if context_sections:
                workspace_content += "\n=== CONTENT SECTIONS ===\n"
                for i, section in enumerate(context_sections, 1):
                    workspace_content += f"\n{i}. {section}\n"

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
                              "business_process": "string (e.g., Client Onboarding & KYC)",
                              "category": "string (Front Office | Middle Office | Back Office)",
                              "process_type": "string (Core | Support)",
                              "activities_and_description": "string (Detailed description of activities)"
                            }},
                            // ... additional process objects
                          ]
                        }}
                    """
                )

            # Create the model instance
            model = genai.GenerativeModel(
                model_name=config["model"],
                system_instruction=system_prompt,
                generation_config={
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": 40,
                }
            )

            # Generate content using Gemini
            response = model.generate_content(prompt_text)
            generated = response.text.strip()

            logger.debug(f"Raw LLM response (first 2000 chars):\n{generated[:2000]}")

            def _clean_candidate(text: str) -> str:
                s = text or ""

                # Remove common fenced code markers and backticks
                s = re.sub(r"```(?:json|yaml)?\n", "", s)
                s = re.sub(r"```", "", s)
                s = s.replace('`', '')

                # Unwrap bold/italic markers
                s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
                s = re.sub(r"\*([^*]+)\*", r"\1", s)

                # Unescape HTML entities
                try:
                    import html
                    s = html.unescape(s)
                except Exception:
                    pass

                # Remove control characters that may break JSON parsing
                s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)

                # Try to extract the first balanced JSON object/array from the text.
                def _extract_first_json(sn: str) -> str:
                    start_idx = None
                    for i, ch in enumerate(sn):
                        if ch in '{[':
                            start_idx = i
                            break
                    if start_idx is None:
                        return sn

                    stack = []
                    in_string = False
                    escape = False
                    for j in range(start_idx, len(sn)):
                        c = sn[j]
                        if escape:
                            escape = False
                            continue
                        if c == '\\':
                            escape = True
                            continue
                        if c == '"':
                            in_string = not in_string
                            continue
                        if in_string:
                            continue
                        if c == '{' or c == '[':
                            stack.append(c)
                        elif c == '}' or c == ']':
                            if not stack:
                                # unmatched closing, give up
                                return sn[start_idx:j+1]
                            opening = stack.pop()
                            if (opening == '{' and c != '}') or (opening == '[' and c != ']'):
                                # mismatched, continue searching
                                continue
                            if not stack:
                                return sn[start_idx:j+1]
                    # If we get here, we didn't find a balanced end; return the substring from start
                    return sn[start_idx:]

                extracted = _extract_first_json(s)

                # Trim and return extracted candidate; do not aggressively rewrite quotes/escapes
                return extracted.strip()

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
                        candidate_py = candidate.replace('true', 'True').replace('false', 'False').replace('null', 'None')
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

            logger.info(f"Generated ({purpose}) for capability '{capability_name or ''}' in domain '{domain or ''}': parsed keys={list(parsed.keys()) if isinstance(parsed, dict) else type(parsed)}")

            return {"status": "success", "data": parsed, "raw": generated, "capability_name": capability_name}

        except Exception as e:
            logger.error(f"Error generating JSON ({purpose}): {str(e)}")
            raise Exception(f"Process generation failed: {str(e)}")


gemini_client = GeminiClient()
