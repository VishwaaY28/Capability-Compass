import logging
from pathlib import Path
from datetime import datetime
import os

logger = logging.getLogger(__name__)


class LLMCallLogger:
    """Logs all LLM calls with metadata to a .log file in a separate folder."""
    
    def __init__(self, log_dir: str = None):
        """
        Initialize the LLM Call Logger.
        
        Args:
            log_dir: Directory to store LLM call logs. Defaults to 'llm_call_logs' in the project root.
        """
        if log_dir is None:
            # Use 'llm_call_logs' folder at the same level as 'src'
            current_file = Path(__file__)
            log_dir = current_file.parent.parent.parent / "llm_call_logs"
        else:
            log_dir = Path(log_dir)
        
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Log file path with today's date
        self.log_file = self.log_dir / f"llm_calls_{datetime.now().strftime('%Y%m%d')}.log"
        
        # Counter for unique sequential IDs
        self.call_counter = self._load_counter()
        
        logger.info(f"LLM Call Logger initialized. Log directory: {self.log_dir}")
    
    def _load_counter(self) -> int:
        """Load the counter from the log file to maintain sequential IDs."""
        try:
            if self.log_file.exists():
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    if lines:
                        # Extract the last ID from the last line
                        last_line = lines[-1]
                        if 'ID:' in last_line:
                            # Parse the ID number from the last entry
                            parts = last_line.split('ID:')
                            if len(parts) > 1:
                                id_str = parts[1].split('|')[0].strip()
                                try:
                                    return int(id_str)
                                except ValueError:
                                    return 0
            return 0
        except Exception as e:
            logger.warning(f"Failed to load counter from log file: {e}")
            return 0
    
    def log_call(
        self,
        model_name: str,
        domain: str = None,
        capability_name: str = None,
        user_prompt: str = None,
        status: str = "success"
    ) -> int:
        """
        Log an LLM call with metadata.
        
        Args:
            model_name: Name of the deployment model used (e.g., 'gpt-4o')
            domain: Domain for which the LLM was called (optional)
            capability_name: Capability name for which the LLM was called (optional)
            user_prompt: The user prompt text sent to the LLM (optional)
            status: Status of the call (default: 'success')
        
        Returns:
            int: The unique sequential ID assigned to this call
        """
        try:
            # Increment counter to get next ID
            self.call_counter += 1
            unique_id = self.call_counter
            
            # Get current datetime
            call_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            
            # Prepare log entry with pipe-delimited format
            log_entry = (
                f"ID:{unique_id} | "
                f"DateTime:{call_datetime} | "
                f"Model:{model_name} | "
                f"Domain:{domain or 'N/A'} | "
                f"SubVertical:{capability_name or 'N/A'} | "
                f"UserPrompt:{user_prompt or 'N/A'} | "
                f"Status:{status}\n"
            )
            
            # Append to log file
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
            
            logger.debug(f"Logged LLM call with ID: {unique_id}")
            return unique_id
        
        except Exception as e:
            logger.error(f"Failed to log LLM call: {e}")
            raise
    
    def get_log_directory(self) -> Path:
        """Return the log directory path."""
        return self.log_dir
    
    def get_today_log_file(self) -> Path:
        """Return the path to today's log file."""
        return self.log_file


# Global instance
_llm_call_logger = None


def get_llm_call_logger(log_dir: str = None) -> LLMCallLogger:
    """Get or create the global LLM Call Logger instance."""
    global _llm_call_logger
    if _llm_call_logger is None:
        _llm_call_logger = LLMCallLogger(log_dir=log_dir)
    return _llm_call_logger
