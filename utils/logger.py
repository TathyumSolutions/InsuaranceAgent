"""
Logging Utility
Provides consistent logging across the application
"""
import logging
import os
from logging.handlers import RotatingFileHandler
import colorlog


def setup_logger(name: str, log_file: str = None, level: str = "INFO"):
    """
    Setup logger with both console and file handlers
    
    Args:
        name: Logger name
        log_file: Path to log file (optional)
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    
    # Remove existing handlers
    logger.handlers = []
    
    # Console handler with colors
    console_handler = colorlog.StreamHandler()
    console_handler.setLevel(getattr(logging, level.upper()))
    
    console_format = colorlog.ColoredFormatter(
        '%(log_color)s%(asctime)s - %(levelname)-8s%(reset)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        }
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # File handler (if log file specified)
    if log_file:
        # Create logs directory if it doesn't exist
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(getattr(logging, level.upper()))
        
        file_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    
    return logger


def get_call_logger(call_sid: str, log_file: str = None):
    """
    Get a logger specific to a call
    
    Args:
        call_sid: Twilio call SID
        log_file: Optional log file path
    
    Returns:
        Logger with call-specific prefix
    """
    logger = setup_logger(f"call.{call_sid}", log_file)
    
    # Add call SID to all log messages
    class CallFilter(logging.Filter):
        def filter(self, record):
            record.call_sid = call_sid
            return True
    
    logger.addFilter(CallFilter())
    
    return logger
