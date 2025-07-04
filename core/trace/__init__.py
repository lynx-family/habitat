"""Trace module for performance monitoring and debugging.

This module provides tracing capabilities that generate Chrome tracing format files.
Supports async events and events that span across different threads.
"""

from .event import EventType, TraceEvent
from .tracer import Tracer, trace_async_function, trace_function
from .writer import ChromeTraceWriter

# Global tracer instance
_global_tracer = None


def set_global_tracer(tracer):
    """Set the global tracer instance."""
    global _global_tracer
    _global_tracer = tracer


def get_global_tracer():
    """Get the global tracer instance."""
    return _global_tracer


__all__ = [
    "Tracer",
    "trace_function",
    "trace_async_function",
    "TraceEvent",
    "EventType",
    "ChromeTraceWriter",
    "set_global_tracer",
    "get_global_tracer",
]
