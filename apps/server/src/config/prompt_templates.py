"""
Prompt Template Management Module

Handles storage and retrieval of LLM prompt templates using JSON file
"""
from typing import Dict, Optional
import logging
import json
from pathlib import Path

logger = logging.getLogger(__name__)

# Prompt templates file path
TEMPLATES_FILE = Path(__file__).parent.parent / "config" / "prompt_templates.json"

# Default prompt templates
DEFAULT_TEMPLATES = {
    "enterprise": """You are a Senior Enterprise Architect and Process Subject Matter Expert (SME) specializing in classifying business capabilities.

## Task:
Generate a comprehensive list of enterprise-level Business Capabilities (Processes) for the given capability. The processes must be categorized by their Process Type (Core or Support).

## Requirements:
- The list must be comprehensive, capturing all relevant, enterprise-level capabilities
- Each capability must have a Name (Business Process), a Category (Front/Middle/Back Office), a Type (Core/Support), and a detailed Description
- The Category must be one of: 'Front Office', 'Middle Office', or 'Back Office'
- The Type must strictly match the process_type provided ('Core' or 'Support')
- Do not invent processes; base them strictly on standard industry practices for Enterprise Architecture

## Output Format:
Return the data as a valid JSON object matching the schema below. The output must be an array of process objects.

### JSON Schema:
{
  "processes": [
    {
      "name": "string (e.g., Strategic Planning & Governance)",
      "category": "string (Front Office | Middle Office | Back Office)",
      "process_type": "string (Core | Support)",
      "description": "string (description of activities)"
    }
  ]
}""",
    
    "core": """You are a Senior Enterprise Architect and Process Subject Matter Expert (SME) specializing in classifying business capabilities.

## Task:
Generate a comprehensive list of high-level Business Capabilities (Processes) for the given capability. The processes must be categorized by their Process Type (Core or Support).

## Requirements:
- The list must be comprehensive, capturing all relevant, high-level capabilities
- Each capability must have a Name (Business Process), a Category (Front/Middle/Back Office), a Type (Core/Support), and a detailed Description
- The Category must be one of: 'Front Office', 'Middle Office', or 'Back Office'
- The Type must strictly match the process_type provided ('Core' or 'Support')
- Do not invent processes; base them strictly on standard industry practices for Enterprise Architecture

## Output Format:
Return the data as a valid JSON object matching the schema below. The output must be an array of process objects.

### JSON Schema:
{
  "processes": [
    {
      "name": "string (e.g., Market research & strategy development, Deal origination & sourcing, Investment screening & initial evaluation, Due Diligence, Financial Analysis & Deal Structuring, Transaction Execution & Closing)",
      "category": "string (Front Office | Middle Office | Back Office)",
      "process_type": "string (Core | Support)",
      "description": "string (description of activities)"
    }
  ]
}""",
    
    "process": """You are a Senior Enterprise Architect and Process Subject Matter Expert (SME) specializing in classifying business capabilities.

## Task:
Generate a comprehensive list of detailed Business Processes for the given capability. The processes must be categorized by their Process Type (Core or Support).

## Requirements:
- The list must be comprehensive, capturing all relevant, detailed processes
- Each process must have a Name (Business Process), a Category (Front/Middle/Back Office), a Type (Core/Support), and a detailed Description
- The Category must be one of: 'Front Office', 'Middle Office', or 'Back Office'
- The Type must strictly match the process_type provided ('Core' or 'Support')
- Do not invent processes; base them strictly on standard industry practices for Enterprise Architecture

## Output Format:
Return the data as a valid JSON object matching the schema below. The output must be an array of process objects.

### JSON Schema:
{
  "processes": [
    {
      "name": "string (detailed process name)",
      "category": "string (Front Office | Middle Office | Back Office)",
      "process_type": "string (Core | Support)",
      "description": "string (detailed description of activities)"
    }
  ]
}""",
    
    "subprocess": """You are a Senior Enterprise Architect and Process Subject Matter Expert (SME) specializing in breaking down business processes into detailed subprocesses.

## Task:
Generate a comprehensive list of detailed subprocesses for the parent process. Each subprocess should represent a specific activity or step.

## Requirements:
- The list must be comprehensive, capturing all relevant subprocesses
- Each subprocess must have a Name, a Category (Front/Middle/Back Office), and a detailed Description
- The Category must be one of: 'Front Office', 'Middle Office', or 'Back Office'
- Base subprocesses strictly on standard industry practices

## Output Format:
Return the data as a valid JSON object matching the schema below. The output must be an array of subprocess objects.

### JSON Schema:
{
  "subprocesses": [
    {
      "name": "string (detailed subprocess name)",
      "category": "string (Front Office | Middle Office | Back Office)",
      "description": "string (detailed description of subprocess activities)"
    }
  ]
}"""
}


class PromptTemplateManager:
    """Manages prompt templates with JSON file persistence"""
    
    def __init__(self):
        self._templates_cache = None
        self._ensure_templates_file()
    
    def _ensure_templates_file(self):
        """Ensure templates file exists with defaults"""
        if not TEMPLATES_FILE.exists():
            TEMPLATES_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(TEMPLATES_FILE, 'w') as f:
                json.dump(DEFAULT_TEMPLATES, f, indent=2)
            logger.info(f"Created default prompt templates file: {TEMPLATES_FILE}")
    
    def _load_templates(self) -> Dict[str, str]:
        """Load templates from JSON file"""
        try:
            with open(TEMPLATES_FILE, 'r') as f:
                templates = json.load(f)
            return templates
        except Exception as e:
            logger.warning(f"Failed to load templates file, using defaults: {e}")
            return DEFAULT_TEMPLATES.copy()
    
    def _save_templates(self, templates: Dict[str, str]):
        """Save templates to JSON file"""
        try:
            with open(TEMPLATES_FILE, 'w') as f:
                json.dump(templates, f, indent=2)
            self._templates_cache = templates
            logger.info("Templates saved successfully")
        except Exception as e:
            logger.error(f"Failed to save templates: {e}")
            raise
    
    async def get_template(self, process_level: str) -> Optional[str]:
        """Get prompt template for a specific process level"""
        if self._templates_cache is None:
            self._templates_cache = self._load_templates()
        
        return self._templates_cache.get(process_level.lower())
    
    async def get_all_templates(self) -> Dict[str, str]:
        """Get all prompt templates"""
        if self._templates_cache is None:
            self._templates_cache = self._load_templates()
        return self._templates_cache.copy()
    
    async def update_template(self, process_level: str, prompt: str) -> Dict[str, str]:
        """Update a specific template"""
        if self._templates_cache is None:
            self._templates_cache = self._load_templates()
        
        self._templates_cache[process_level.lower()] = prompt
        self._save_templates(self._templates_cache)
        return self._templates_cache.copy()
    
    async def reset_to_defaults(self) -> Dict[str, str]:
        """Reset all templates to defaults"""
        self._save_templates(DEFAULT_TEMPLATES.copy())
        return DEFAULT_TEMPLATES.copy()


# Global instance
prompt_template_manager = PromptTemplateManager()
