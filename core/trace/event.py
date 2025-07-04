"""Trace event definitions for Chrome tracing format."""

import asyncio
import hashlib
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional


class EventType(Enum):
    """Chrome tracing event types."""

    DURATION_BEGIN = "B"  # Begin duration event
    DURATION_END = "E"  # End duration event
    COMPLETE = "X"  # Complete duration event
    INSTANT = "i"  # Instant event
    COUNTER = "C"  # Counter event
    ASYNC_START = "b"  # Async start event
    ASYNC_INSTANT = "n"  # Async instant event
    ASYNC_END = "e"  # Async end event
    FLOW_START = "s"  # Flow start event
    FLOW_STEP = "t"  # Flow step event
    FLOW_END = "f"  # Flow end event
    METADATA = "M"  # Metadata event


def _get_coroutine_thread_id() -> int:
    """Generate a unique thread ID for the current coroutine.

    This function creates a unique thread ID based on the current task ID
    to ensure different coroutines appear on separate tracks in the trace viewer.

    Returns:
        Unique thread ID for the current coroutine
    """
    try:
        # Get current asyncio task
        current_task = asyncio.current_task()
        if current_task is not None:
            # Create a unique thread ID based on task ID
            task_id = str(id(current_task))
            # Use hash to create a more manageable thread ID
            hash_obj = hashlib.md5(task_id.encode())
            # Convert to integer and ensure it's positive
            thread_id = int(hash_obj.hexdigest()[:8], 16)
            # Add base offset to distinguish from real thread IDs
            return 0x10000000 + (thread_id % 0x10000000)
        else:
            # Not in async context, use regular thread ID
            return threading.current_thread().ident or 0
    except RuntimeError:
        # Not in async context, use regular thread ID
        return threading.current_thread().ident or 0


def _serialize_args(args: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize arguments to JSON-compatible format.

    Converts Path objects to strings and handles other non-serializable types.

    Args:
        args: Dictionary of arguments to serialize

    Returns:
        Dictionary with JSON-serializable values
    """
    if not args:
        return {}

    serialized = {}
    for key, value in args.items():
        if isinstance(value, Path):
            serialized[key] = str(value)
        elif isinstance(value, dict):
            serialized[key] = _serialize_args(value)
        elif isinstance(value, (list, tuple)):
            serialized[key] = [
                str(item) if isinstance(item, Path) else item for item in value
            ]
        else:
            serialized[key] = value
    return serialized


class TraceEvent:
    """Represents a single trace event in Chrome tracing format."""

    def __init__(
        self,
        name: str,
        event_type: EventType,
        timestamp: Optional[float] = None,
        duration: Optional[float] = None,
        process_id: Optional[int] = None,
        thread_id: Optional[int] = None,
        category: str = "default",
        args: Optional[Dict[str, Any]] = None,
        async_id: Optional[str] = None,
    ):
        """Initialize a trace event.

        Args:
            name: Event name
            event_type: Type of the event
            timestamp: Event timestamp in microseconds (defaults to current time)
            duration: Event duration in microseconds (for complete events)
            process_id: Process ID (defaults to current process)
            thread_id: Thread ID (defaults to current thread)
            category: Event category for filtering
            args: Additional event arguments
            async_id: Async event ID for correlating async events
        """
        self.name = name
        self.event_type = event_type
        self.timestamp = timestamp if timestamp is not None else time.time() * 1_000_000
        self.duration = duration
        self.process_id = (
            process_id
            if process_id is not None
            else (threading.current_thread().ident or 0)
        )
        self.thread_id = (
            thread_id if thread_id is not None else _get_coroutine_thread_id()
        )
        self.category = category
        self.args = args or {}
        self.async_id = async_id

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to Chrome tracing format dictionary."""
        event_dict = {
            "name": self.name,
            "ph": self.event_type.value,
            "ts": int(self.timestamp),
            "pid": self.process_id,
            "tid": self.thread_id,
            "cat": self.category,
        }

        if self.duration is not None:
            event_dict["dur"] = int(self.duration)

        if self.args:
            event_dict["args"] = _serialize_args(self.args)

        if self.async_id is not None:
            event_dict["id"] = self.async_id

        return event_dict

    def __repr__(self) -> str:
        return f"TraceEvent(name='{self.name}', type={self.event_type}, ts={self.timestamp})"
