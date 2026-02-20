"""
Configuration loader for ircquotes application.
Loads settings from config.json and provides easy access to configuration values.
"""

import json
import os
from typing import Any, Dict

class Config:
    """Configuration manager for ircquotes application."""
    
    def __init__(self, config_file: str = "config.json"):
        """Initialize configuration from JSON file."""
        self.config_file = config_file
        self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        if not os.path.exists(self.config_file):
            raise FileNotFoundError(f"Configuration file {self.config_file} not found")
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in configuration file: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value using dot notation (e.g., 'app.host')."""
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """Get entire configuration section."""
        return self._config.get(section, {})
    
    def reload(self):
        """Reload configuration from file."""
        self._config = self._load_config()
    
    # Convenience properties for commonly used settings
    @property
    def app_name(self) -> str:
        return self.get('app.name', 'ircquotes')
    
    @property
    def app_host(self) -> str:
        return self.get('app.host', '0.0.0.0')
    
    @property
    def app_port(self) -> int:
        return self.get('app.port', 5050)
    
    @property
    def debug_mode(self) -> bool:
        return self.get('app.debug', False)
    
    @property
    def database_uri(self) -> str:
        return self.get('database.uri', 'sqlite:///quotes.db')
    
    @property
    def csrf_enabled(self) -> bool:
        return self.get('security.csrf_enabled', True)
    
    @property
    def rate_limiting_enabled(self) -> bool:
        return self.get('rate_limiting.enabled', True)
    
    @property
    def quotes_per_page(self) -> int:
        return self.get('quotes.per_page', 25)
    
    @property
    def min_quote_length(self) -> int:
        return self.get('quotes.min_length', 10)
    
    @property
    def max_quote_length(self) -> int:
        return self.get('quotes.max_length', 5000)
    
    @property
    def admins(self) -> list:
        # Fallback for old style config to maintain compatibility if needed, though we updated config.json
        admins = self.get('admins')
        if admins:
            return admins
        
        # Fallback to legacy single admin if 'admins' list is missing
        legacy_username = self.get('admin.username')
        legacy_hash = self.get('admin.password_hash')
        if legacy_username and legacy_hash:
            return [{'username': legacy_username, 'password_hash': legacy_hash}]
            
        return []
    
    @property
    def logging_level(self) -> str:
        return self.get('logging.level', 'WARNING')

# Global configuration instance
config = Config()