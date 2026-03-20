"""
Configuration management for TurtleBot Web UI
Handles settings persistence and validation
"""
import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

# Setup logging
LOG_DIR = Path(__file__).parent / 'logs'
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'app.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

@dataclass
class RobotConfig:
    """Robot connection configuration"""
    rosbridge_ip: str = '192.168.1.100'
    rosbridge_port: int = 9090
    base_speed: float = 0.2
    turn_speed: float = 0.5
    max_speed: float = 1.0
    min_speed: float = 0.1

@dataclass
class UIConfig:
    """User interface configuration"""
    dark_mode: bool = False
    show_fps: bool = True
    keyboard_control: bool = True
    mouse_control: bool = False
    auto_reconnect: bool = True
    reconnect_interval: int = 5

@dataclass
class AppConfig:
    """Main application configuration"""
    robot: RobotConfig
    ui: UIConfig
    last_updated: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'robot': asdict(self.robot),
            'ui': asdict(self.ui),
            'last_updated': self.last_updated
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AppConfig':
        """Create from dictionary"""
        robot_config = RobotConfig(**data.get('robot', {}))
        ui_config = UIConfig(**data.get('ui', {}))
        return cls(
            robot=robot_config,
            ui=ui_config,
            last_updated=data.get('last_updated', '')
        )

class ConfigManager:
    """Manages application configuration with persistence"""
    
    def __init__(self, config_file: str = 'config.json'):
        self.config_file = Path(__file__).parent / config_file
        self._config: Optional[AppConfig] = None
        self.load_config()
    
    def load_config(self) -> AppConfig:
        """Load configuration from file or create default"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                self._config = AppConfig.from_dict(data)
                logger.info(f"Configuration loaded from {self.config_file}")
            else:
                self._config = AppConfig(
                    robot=RobotConfig(),
                    ui=UIConfig()
                )
                self.save_config()
                logger.info("Default configuration created")
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            self._config = AppConfig(
                robot=RobotConfig(),
                ui=UIConfig()
            )
        
        return self._config
    
    def save_config(self) -> bool:
        """Save current configuration to file"""
        try:
            if self._config:
                self._config.last_updated = datetime.now().isoformat()
                with open(self.config_file, 'w') as f:
                    json.dump(self._config.to_dict(), f, indent=2)
                logger.info(f"Configuration saved to {self.config_file}")
                return True
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
        return False
    
    def get_config(self) -> AppConfig:
        """Get current configuration"""
        if self._config is None:
            self.load_config()
        return self._config
    
    def update_robot_config(self, **kwargs) -> bool:
        """Update robot configuration"""
        try:
            if self._config:
                for key, value in kwargs.items():
                    if hasattr(self._config.robot, key):
                        setattr(self._config.robot, key, value)
                return self.save_config()
        except Exception as e:
            logger.error(f"Error updating robot config: {e}")
        return False
    
    def update_ui_config(self, **kwargs) -> bool:
        """Update UI configuration"""
        try:
            if self._config:
                for key, value in kwargs.items():
                    if hasattr(self._config.ui, key):
                        setattr(self._config.ui, key, value)
                return self.save_config()
        except Exception as e:
            logger.error(f"Error updating UI config: {e}")
        return False
    
    def reset_to_default(self) -> bool:
        """Reset configuration to default values"""
        try:
            self._config = AppConfig(
                robot=RobotConfig(),
                ui=UIConfig()
            )
            return self.save_config()
        except Exception as e:
            logger.error(f"Error resetting configuration: {e}")
        return False

# Global configuration instance
config_manager = ConfigManager()

def get_config() -> AppConfig:
    """Get the global configuration instance"""
    return config_manager.get_config()

def update_robot_config(**kwargs) -> bool:
    """Update robot configuration globally"""
    return config_manager.update_robot_config(**kwargs)

def update_ui_config(**kwargs) -> bool:
    """Update UI configuration globally"""
    return config_manager.update_ui_config(**kwargs)

def reset_config() -> bool:
    """Reset configuration to defaults"""
    return config_manager.reset_to_default()
