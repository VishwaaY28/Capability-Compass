"""
LLM Settings Management Module

Handles persistent storage and retrieval of LLM configuration settings using JSON file
"""
from typing import Dict, Any
import logging
import json
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Default settings
DEFAULT_SETTINGS = {
    "provider": "azure",
    "vaultName": "https://fstodevazureopenai.vault.azure.net/",
    "temperature": 0.5,
    "topP": 0.9,
}

# Settings file path
SETTINGS_FILE = Path(__file__).parent.parent / "config" / "llm_settings.json"


class LLMSettingsManager:
    """Manages LLM configuration settings with JSON file persistence"""
    
    def __init__(self):
        self._settings_cache = None
        self._ensure_settings_file()
    
    def _ensure_settings_file(self):
        """Ensure settings file exists with defaults"""
        if not SETTINGS_FILE.exists():
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(DEFAULT_SETTINGS, f, indent=2)
            logger.info(f"Created default settings file: {SETTINGS_FILE}")
    
    def _load_settings(self) -> Dict[str, Any]:
        """Load settings from JSON file"""
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
            return settings
        except Exception as e:
            logger.warning(f"Failed to load settings file, using defaults: {e}")
            return DEFAULT_SETTINGS.copy()
    
    def _save_settings(self, settings: Dict[str, Any]):
        """Save settings to JSON file"""
        try:
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(settings, f, indent=2)
            self._settings_cache = settings
            logger.info("Settings saved successfully")
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
            raise

    def get_all_settings(self) -> Dict[str, Any]:
        """Get all current settings"""
        if self._settings_cache is None:
            self._settings_cache = self._load_settings()
        return self._settings_cache.copy()

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a specific setting"""
        settings = self.get_all_settings()
        return settings.get(key, default)

    def update_settings(self, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        """Update settings and persist to file"""
        current = self.get_all_settings()
        
        # Map frontend keys to storage keys (handle both formats)
        if "vaultName" in new_settings:
            current["vaultName"] = new_settings["vaultName"]
        if "vault_name" in new_settings:
            current["vaultName"] = new_settings["vault_name"]
        if "provider" in new_settings:
            current["provider"] = new_settings["provider"]
        if "temperature" in new_settings:
            current["temperature"] = new_settings["temperature"]
        if "topP" in new_settings:
            current["topP"] = new_settings["topP"]
        if "top_p" in new_settings:
            current["topP"] = new_settings["top_p"]
        
        self._save_settings(current)
        return current

    def reset_to_defaults(self) -> Dict[str, Any]:
        """Reset all settings to defaults"""
        self._save_settings(DEFAULT_SETTINGS.copy())
        return DEFAULT_SETTINGS.copy()


# Global instance
llm_settings_manager = LLMSettingsManager()
