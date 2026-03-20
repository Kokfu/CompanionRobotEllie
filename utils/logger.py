"""
Centralized logging system for TurtleBot Web UI
Provides structured logging with proper file organization
"""
import os
import logging
import logging.handlers
from pathlib import Path
from datetime import datetime
from typing import Optional

class TurtleBotLogger:
    """Centralized logging system for the application"""
    
    def __init__(self, log_dir: str = 'logs'):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # Create subdirectories for different log types
        (self.log_dir / 'app').mkdir(exist_ok=True)
        (self.log_dir / 'ros').mkdir(exist_ok=True)
        (self.log_dir / 'errors').mkdir(exist_ok=True)
        (self.log_dir / 'telemetry').mkdir(exist_ok=True)
        
        self._setup_loggers()
    
    def _setup_loggers(self):
        """Setup different loggers for different components"""
        
        # Main application logger
        self.app_logger = self._create_logger(
            'app',
            self.log_dir / 'app' / 'app.log',
            level=logging.INFO
        )
        
        # ROS communication logger
        self.ros_logger = self._create_logger(
            'ros',
            self.log_dir / 'ros' / 'ros.log',
            level=logging.INFO
        )
        
        # Error logger
        self.error_logger = self._create_logger(
            'error',
            self.log_dir / 'errors' / 'errors.log',
            level=logging.ERROR
        )
        
        # Telemetry logger
        self.telemetry_logger = self._create_logger(
            'telemetry',
            self.log_dir / 'telemetry' / 'telemetry.log',
            level=logging.INFO
        )
        
        # Fall detection logger
        self.fall_logger = self._create_logger(
            'fall',
            self.log_dir / 'app' / 'fall.log',
            level=logging.INFO
        )
    
    def _create_logger(self, name: str, log_file: Path, level: int = logging.INFO) -> logging.Logger:
        """Create a logger with file and console handlers"""
        logger = logging.getLogger(name)
        logger.setLevel(level)
        
        # Clear existing handlers
        logger.handlers.clear()
        
        # File handler with rotation
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(level)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        return logger
    
    def log_app(self, message: str, level: int = logging.INFO):
        """Log application events"""
        self.app_logger.log(level, message)
    
    def log_ros(self, message: str, level: int = logging.INFO):
        """Log ROS communication events"""
        self.ros_logger.log(level, message)
    
    def log_error(self, message: str, exception: Optional[Exception] = None):
        """Log errors with optional exception details"""
        if exception:
            self.error_logger.error(f"{message}: {str(exception)}", exc_info=True)
        else:
            self.error_logger.error(message)
    
    def log_telemetry(self, data: dict):
        """Log telemetry data"""
        timestamp = datetime.now().isoformat()
        self.telemetry_logger.info(f"Telemetry: {timestamp} - {data}")
    
    def log_fall_detection(self, label: str, confidence: float, angle: float):
        """Log fall detection events"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.fall_logger.info(f"[{timestamp}] {label} - conf={confidence:.3f} angle={angle:.1f}")
    
    def get_log_files(self) -> dict:
        """Get list of available log files"""
        log_files = {}
        for subdir in ['app', 'ros', 'errors', 'telemetry']:
            subdir_path = self.log_dir / subdir
            if subdir_path.exists():
                log_files[subdir] = list(subdir_path.glob('*.log'))
        return log_files

# Global logger instance
turtlebot_logger = TurtleBotLogger()

# Convenience functions
def log_app(message: str, level: int = logging.INFO):
    """Log application events"""
    turtlebot_logger.log_app(message, level)

def log_ros(message: str, level: int = logging.INFO):
    """Log ROS communication events"""
    turtlebot_logger.log_ros(message, level)

def log_error(message: str, exception: Optional[Exception] = None):
    """Log errors"""
    turtlebot_logger.log_error(message, exception)

def log_telemetry(data: dict):
    """Log telemetry data"""
    turtlebot_logger.log_telemetry(data)

def log_fall_detection(label: str, confidence: float, angle: float):
    """Log fall detection events"""
    turtlebot_logger.log_fall_detection(label, confidence, angle)
