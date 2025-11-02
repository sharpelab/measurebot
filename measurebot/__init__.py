"""
MeasureBot - Simple notifications via Discord and email for lab automation.

This package provides easy-to-use functions for sending notifications
from Python scripts, particularly useful in laboratory automation and
data analysis workflows.
"""

__version__ = "0.1.0"
__author__ = "Aaron Sharpe"
__email__ = "measureme@aaronsharpe.science"

# Import main functionality for easy access
from .alerts import (
    set_defaults,
    show_config,
    send_discord_message,
    send_email,
    discord,
    email,
    alert
)

# Also import the alerts module itself
from . import alerts

__all__ = [
    'alerts',
    'set_defaults',
    'show_config', 
    'send_discord_message',
    'send_email',
    'discord',
    'email',
    'alert'
]