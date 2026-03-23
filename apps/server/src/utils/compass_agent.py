import os
import json
from typing import List, Dict, Any

from deepagents import create_deep_agent
from datetime import datetime

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

from langchain_openai import AzureChatOpenAI
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.tools import tool

system_prompt = """
You are an expert Enterprise Architecture Consultant. Your job is to analyze the user intent and based on the intent you will give response to the user.
examples for user intent -[ Informative, Strategic, Operational, Actionable ]

MANDATORY CHECKLIST:
Make sure you only use the provided input context and dont invent.
Make sure you change the tone and concept depth based on the user intent.
The response structure and response tone should be based on the user intent.

INPUT CONTEXT:
{
  "id": 1,
  "name": "Fund Mandate",
  "description": "",
  "vertical": "Capital Markets",
  "subvertical": "Asset Management",
  "processes": [
    {
      "id": 1,
      "name": "Research and Idea Generation",
      "level": "core",
      "description": "",
      "category": "Back Office",
      "subprocesses": [
        {
          "id": 1,
          "name": "Sector & Industry Research",
          "description": "",
          "category": "Back Office",
          "data_entities": [
            {
              "data_entity_id": 1,
              "data_entity_name": "Base Profile",
              "data_entity_description": "",
              "data_elements": [
                {
                  "data_element_id": 1,
                  "data_element_name": "country",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 2,
                  "data_element_name": "sector",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 3,
                  "data_element_name": "industry",
                  "data_element_description": ""
                }
              ]
            }
          ],
          "application": null,
          "api": null
        },
        {
          "id": 2,
          "name": "Bottom-Up Fundamental Analysis",
          "description": "",
          "category": "Back Office",
          "data_entities": [
            {
              "data_entity_id": 2,
              "data_entity_name": "Financial Parameters",
              "data_entity_description": "",
              "data_elements": [
                {
                  "data_element_id": 4,
                  "data_element_name": "revenue",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 5,
                  "data_element_name": "ebitda",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 6,
                  "data_element_name": "growth",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 7,
                  "data_element_name": "gross_profit_margin",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 8,
                  "data_element_name": "net_income",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 9,
                  "data_element_name": "return_on_equity",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 10,
                  "data_element_name": "debt_to_equity",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 11,
                  "data_element_name": "pe_ratio",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 12,
                  "data_element_name": "price_to_book",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 13,
                  "data_element_name": "market_cap",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 14,
                  "data_element_name": "dividend_yield",
                  "data_element_description": ""
                }
              ]
            }
          ],
          "application": null,
          "api": null
        },
        {
          "id": 3,
          "name": "Risk Assessment of Investment Ideas",
          "description": "",
          "category": "Back Office",
          "data_entities": [
            {
              "data_entity_id": 3,
              "data_entity_name": "Risk Parameters",
              "data_entity_description": "",
              "data_elements": [
                {
                  "data_element_id": 15,
                  "data_element_name": "competitive_position",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 16,
                  "data_element_name": "governance_quality",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 17,
                  "data_element_name": "customer_concentration_risk",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 18,
                  "data_element_name": "vendor_platform_dependency",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 19,
                  "data_element_name": "regulatory_legal_risk",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 20,
                  "data_element_name": "business_model_complexity",
                  "data_element_description": ""
                }
              ]
            }
          ],
          "application": null,
          "api": null
        }
      ]
    }
  ]
}

#FINAL ANALYSIS
-should contain the user intent in the response.
-the response should be strictly in markdown format.

"""

INPUT_CONTEXT: Dict[str, Any] = {
    "id": 1,
    "name": "Fund Mandate",
    "vertical": "Capital Markets",
    "subvertical": "Asset Management",
    "processes": [
        {
            "id": 1,
            "name": "Research and Idea Generation",
            "level": "core",
            "category": "Back Office",
            "subprocesses": [
                {
                    "id": 1,
                    "name": "Sector & Industry Research",
                    "category": "Back Office",
                    "data_entities": [
                        {
                            "data_entity_id": 1,
                            "data_entity_name": "Base Profile",
                            "data_elements": [
                                {"data_element_id": 1, "data_element_name": "country"},
                                {"data_element_id": 2, "data_element_name": "sector"},
                                {"data_element_id": 3, "data_element_name": "industry"},
                            ],
                        }
                    ],
                },
                {
                    "id": 2,
                    "name": "Bottom-Up Fundamental Analysis",
                    "category": "Back Office",
                    "data_entities": [
                        {
                            "data_entity_id": 2,
                            "data_entity_name": "Financial Parameters",
                            "data_elements": [
                                {"data_element_id": 4, "data_element_name": "revenue"},
                                {"data_element_id": 5, "data_element_name": "ebitda"},
                                {"data_element_id": 6, "data_element_name": "growth"},
                                {"data_element_id": 7, "data_element_name": "gross_profit_margin"},
                                {"data_element_id": 8, "data_element_name": "net_income"},
                                {"data_element_id": 9, "data_element_name": "return_on_equity"},
                                {"data_element_id": 10, "data_element_name": "debt_to_equity"},
                                {"data_element_id": 11, "data_element_name": "pe_ratio"},
                                {"data_element_id": 12, "data_element_name": "price_to_book"},
                                {"data_element_id": 13, "data_element_name": "market_cap"},
                                {"data_element_id": 14, "data_element_name": "dividend_yield"},
                            ],
                        }
                    ],
                },
                {
                    "id": 3,
                    "name": "Risk Assessment of Investment Ideas",
                    "category": "Back Office",
                    "data_entities": [
                        {
                            "data_entity_id": 3,
                            "data_entity_name": "Risk Parameters",
                            "data_elements": [
                                {"data_element_id": 15, "data_element_name": "competitive_position"},
                                {"data_element_id": 16, "data_element_name": "governance_quality"},
                                {"data_element_id": 17, "data_element_name": "customer_concentration_risk"},
                                {"data_element_id": 18, "data_element_name": "vendor_platform_dependency"},
                                {"data_element_id": 19, "data_element_name": "regulatory_legal_risk"},
                                {"data_element_id": 20, "data_element_name": "business_model_complexity"},
                            ],
                        }
                    ],
                },
            ],
        }
    ],
}
# --------------------------
# Define real tools (not strings)
# --------------------------
@tool
def research_tool() -> str:
    """Research tool: returns that research was performed."""
    return "research tool used"

@tool
def financial_analyzer() -> str:
    """Financial analysis tool: returns that financial analysis was performed."""
    return "financial analyzer used"

@tool
def risk_analyzer() -> str:
    """Risk analysis tool: returns that risk analysis was performed."""
    return "risk tool used"

@tool
def get_mandate_sector_model_fields() -> str:
    """
    Inspect INPUT_CONTEXT to report if a fixed list of allowed sectors exists.
    Returns a deterministic statement derived ONLY from the provided context.
    """
    base_profile = None
    for p in INPUT_CONTEXT.get("processes", []):
        for sp in p.get("subprocesses", []):
            if sp.get("name", "").lower().startswith("sector"):
                for de in sp.get("data_entities", []):
                    if de.get("data_entity_name") == "Base Profile":
                        base_profile = de
                        break
    if not base_profile:
        return "No Base Profile entity found; cannot determine sector-related fields."

    fields = [e["data_element_name"] for e in base_profile.get("data_elements", [])]
    has_sector_field = "sector" in fields
    if has_sector_field:
        return (
            "The mandate captures a 'sector' field in the Base Profile. "
            "However, there is NO explicit whitelist of allowed sectors in the provided context. "
            "Any sector constraints must be externally defined or derived from research scope."
        )
    return "No 'sector' field present; the context does not define sector capture."

research_subagent = {
    "name": "research-agent",
    "description": "Use for in-depth research questions and to inspect sector/industry fields in context.",
    "system_prompt": "You are a great researcher. Prefer calling tools when they can deterministically inspect the context.",
    "tools": [research_tool, get_mandate_sector_model_fields],
}

financial_subagent = {
    "name": "financial-agent",
    "description": "Use for financial parameter reasoning.",
    "system_prompt": "You are a precise financial analyst. Use tools where helpful.",
    "tools": [financial_analyzer],
}

risk_subagent = {
    "name": "risk-agent",
    "description": "Use for risk parameter reasoning.",
    "system_prompt": "You are a risk analyst. Use tools where helpful.",
    "tools": [risk_analyzer],
}

subagents = [research_subagent, financial_subagent, risk_subagent]

def build_agent_kimi():
    """
    Build Deep Agent with Azure OpenAI via LangChain's AzureChatOpenAI.
    """
    credential = DefaultAzureCredential()
    key_vault_url = "https://fstodevazureopenai.vault.azure.net/"
    kv_client = SecretClient(vault_url=key_vault_url, credential=credential)

    api_version = kv_client.get_secret("llm-mini-version").value
    api_key     = kv_client.get_secret("llm-api-key").value
    endpoint    = kv_client.get_secret("llm-base-endpoint").value
    deployment  = kv_client.get_secret("llm-mini").value

    print("endpoint:", endpoint)
    print("deployment:", deployment)

    llm = AzureChatOpenAI(
        azure_deployment=deployment,
        api_version=api_version,
        azure_endpoint=endpoint,
        api_key=api_key,
        streaming=True,
    )

    agent = create_deep_agent(
        model=llm,
        system_prompt=system_prompt,
        # subagents=subagents,
    )
    return agent

def pretty_print_messages(result):
    msgs = result["messages"] if isinstance(result, dict) and "messages" in result else result
    print("\n[Conversation Trace]")
    print(msgs)

def main():
    agent = build_agent_kimi()
    user_task = "What is the procedure for setting performance targets?"
    result = agent.invoke({"messages": [{"role": "user", "content": user_task}]})
    final_msg = result["messages"][-1].content if isinstance(result, dict) and "messages" in result else str(result)
    print("\nAgent finished. Final message:\n", final_msg)
    pretty_print_messages(result)

if __name__ == "__main__":
    main()
