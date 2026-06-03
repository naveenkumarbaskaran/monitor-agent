"""Monitor Agent — automatic monitoring setup from app config."""

from .agent import MonitorAgent
from .analyzer import AppAnalyzer

__all__ = ["MonitorAgent", "AppAnalyzer"]
__version__ = "0.1.0"
