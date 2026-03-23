import csv
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CSVExporter:
    """Handles exporting LLM responses to CSV files"""

    def __init__(self, output_folder: str = "llm_responses"):
        """
        Initialize the CSV exporter.
        
        Args:
            output_folder: The folder where CSV files will be saved (relative to project root)
        """
        self.output_folder = Path(output_folder)
        self.output_folder.mkdir(exist_ok=True, parents=True)
        logger.info(f"CSV exporter initialized with output folder: {self.output_folder.absolute()}")

    def export_process_generation(
        self,
        capability_name: str,
        domain: str,
        process_type: str,
        generated_data: Dict[str, Any],
        provider: str = "unknown",
    ) -> str:
        """
        Export LLM-generated processes to a CSV file.
        
        Args:
            capability_name: The name of the capability
            domain: The domain name
            process_type: The type of process (e.g., 'core', 'enterprise')
            generated_data: The LLM response data containing processes
            provider: The LLM provider used (e.g., 'azure', 'gemini')
        
        Returns:
            The path to the created CSV file
        """
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # Include milliseconds
        filename = f"llm_response_{capability_name}_{timestamp}.csv"
        filepath = self.output_folder / filename

        try:
            # Extract processes from the response
            processes = self._extract_processes(generated_data)

            # Write to CSV
            with open(filepath, "w", newline="", encoding="utf-8") as csvfile:
                fieldnames = [
                    "Vertical",
                    "capability_name",
                    "process_type",
                    "process_name",
                    "process_description",
                    "process_category",
                    "subprocess_name",
                    "subprocess_description",
                    "subprocess_category",
                    "data_entity_name",
                    "data_entity_description",
                    "data_element_name",
                    "data_element_description",
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

                # Write each process and its subprocesses
                for process in processes:
                    subprocesses = process.get("subprocesses", [])
                    
                    if not subprocesses:
                        # Write process without subprocesses
                        writer.writerow({
                            "Vertical": domain,
                            "capability_name": capability_name,
                            "process_type": process_type,
                            "process_name": process.get("name", ""),
                            "process_description": process.get("description", ""),
                            "process_category": process.get("category", ""),
                            "subprocess_name": "",
                            "subprocess_description": "",
                            "subprocess_category": "",
                            "data_entity_name": "",
                            "data_entity_description": "",
                            "data_element_name": "",
                            "data_element_description": "",
                        })
                    else:
                        # Write process with each subprocess on a separate row
                        for subprocess in subprocesses:
                            writer.writerow({
                                "Vertical": domain,
                                "capability_name": capability_name,
                                "process_type": process_type,
                                "process_name": process.get("name", ""),
                                "process_description": process.get("description", ""),
                                "process_category": process.get("category", ""),
                                "subprocess_name": subprocess.get("name", ""),
                                "subprocess_description": subprocess.get("description", ""),
                                "subprocess_category": subprocess.get("category", ""),
                                "data_entity_name": "",
                                "data_entity_description": "",
                                "data_element_name": "",
                                "data_element_description": "",
                            })

            logger.info(f"CSV file created successfully: {filepath.absolute()}")
            logger.info(f"Exported {len(processes)} processes to {filename}")
            return str(filepath.absolute())

        except Exception as e:
            logger.error(f"Error exporting processes to CSV: {str(e)}")
            raise

    def _extract_processes(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract processes from LLM response data.
        
        Handles various response formats from different LLM providers.
        
        Args:
            data: The LLM response data
            
        Returns:
            A list of process dictionaries
        """
        if isinstance(data, list):
            return self._normalize_processes(data)

        if not isinstance(data, dict):
            logger.warning(f"Expected dict or list, got {type(data)}")
            return []

        # Try common variants (case / spacing / snake/camel)
        candidates = [
            "core_processes",
            "coreProcesses",
            "Core Processes",
            "core processes",
            "core-processes",
            "processes",
            "core",
        ]
        for key in candidates:
            if key in data:
                val = data.get(key)
                if isinstance(val, list):
                    return self._normalize_processes(val)

        # Try a case-insensitive, punctuation-insensitive match
        lookup = {self._normalize_key(k): v for k, v in data.items()}
        for target in ("coreprocesses", "coreprocess", "processes"):
            if target in lookup:
                val = lookup[target]
                if isinstance(val, list):
                    return self._normalize_processes(val)

        logger.warning(f"No processes found in response. Available keys: {list(data.keys())}")
        return []

    def _normalize_processes(self, processes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Normalize process dictionaries to ensure consistent field names.
        
        Handles both old format (name, description) and new format (business_process, activities_and_description)
        """
        normalized = []
        for proc in processes:
            if not isinstance(proc, dict):
                logger.warning(f"Skipping non-dict process: {proc}")
                continue
            
            # Create normalized process dict
            normalized_proc = {
                "name": proc.get("business_process") or proc.get("name", "Unnamed"),
                "description": proc.get("activities_and_description") or proc.get("description", ""),
                "category": proc.get("category", ""),
                "subprocesses": proc.get("subprocesses", [])
            }
            normalized.append(normalized_proc)
        
        return normalized

    @staticmethod
    def _normalize_key(key: str) -> str:
        """Normalize a key for comparison (lowercase, remove punctuation)"""
        import re
        return re.sub(r"[^a-z0-9]", "", key.lower())


# Global instance
_csv_exporter = None


def get_csv_exporter(output_folder: str = "llm_responses") -> CSVExporter:
    """Get or create the global CSV exporter instance"""
    global _csv_exporter
    if _csv_exporter is None:
        _csv_exporter = CSVExporter(output_folder)
    return _csv_exporter
