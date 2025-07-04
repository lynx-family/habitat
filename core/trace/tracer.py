"""Main tracer implementation for performance monitoring."""

import functools
import hashlib
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Dict, Optional, TypeVar, Union

from .event import EventType, TraceEvent
from .writer import ChromeTraceWriter

F = TypeVar("F", bound=Callable[..., Any])


class Tracer:
    """Main tracer class for collecting and writing trace events."""

    def __init__(self, output_file: str = "trace.json", enabled: bool = True):
        """Initialize the tracer.

        Args:
            output_file: Path to output trace file
            enabled: Whether tracing is enabled
        """
        self.output_file = output_file
        self.enabled = enabled
        self._writer: Optional[ChromeTraceWriter] = None
        self._lock = threading.Lock()
        self._active_spans: Dict[str, TraceEvent] = {}
        self._async_events: Dict[str, TraceEvent] = {}
        self._async_thread_ids: Dict[str, int] = (
            {}
        )  # Map async_id to consistent thread_id

    def start(self):
        """Start the tracer and open output file."""
        if not self.enabled:
            return

        with self._lock:
            if self._writer is None:
                self._writer = ChromeTraceWriter(self.output_file)
                self._writer.open()

                # Write process metadata
                self._writer.write_metadata(
                    "process_name",
                    {"name": "Habitat Process"},
                    process_id=threading.current_thread().ident,
                )

    def stop(self):
        """Stop the tracer and close output file."""
        if not self.enabled:
            return

        with self._lock:
            if self._writer is not None:
                self._writer.close()
                self._writer = None

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()

    def _write_event(self, event: TraceEvent):
        """Write an event to the trace file."""
        if not self.enabled or self._writer is None:
            return
        self._writer.write_event(event)

    def metadata(
        self, name: str, args: Dict[str, Any], process_id: Optional[int] = None
    ):
        """Write metadata event.

        Args:
            name: Metadata name
            args: Metadata arguments
            process_id: Process ID (defaults to current thread ID)
        """
        if not self.enabled or self._writer is None:
            return

        if process_id is None:
            process_id = threading.current_thread().ident or 0

        self._writer.write_metadata(name, args, process_id)

    def _get_async_thread_id(self, async_id: str) -> int:
        """Get or create a consistent thread ID for an async event.

        Args:
            async_id: Async event ID

        Returns:
            Consistent thread ID for this async event
        """
        with self._lock:
            if async_id not in self._async_thread_ids:
                # Generate a unique thread ID based on async_id
                hash_obj = hashlib.md5(async_id.encode())
                thread_id = int(hash_obj.hexdigest()[:8], 16)
                # Add base offset to distinguish from real thread IDs and coroutine IDs
                self._async_thread_ids[async_id] = 0x20000000 + (thread_id % 0x10000000)
            return self._async_thread_ids[async_id]

    def instant(
        self,
        name: str,
        category: str = "default",
        args: Optional[Dict[str, Any]] = None,
    ):
        """Record an instant event.

        Args:
            name: Event name
            category: Event category
            args: Additional event arguments
        """
        event = TraceEvent(
            name=name, event_type=EventType.INSTANT, category=category, args=args
        )
        self._write_event(event)

    def counter(self, name: str, value: Union[int, float], category: str = "default"):
        """Record a counter event.

        Args:
            name: Counter name
            value: Counter value
            category: Event category
        """
        event = TraceEvent(
            name=name,
            event_type=EventType.COUNTER,
            category=category,
            args={"value": value},
        )
        self._write_event(event)

    @contextmanager
    def span(
        self,
        name: str,
        category: str = "default",
        args: Optional[Dict[str, Any]] = None,
    ):
        """Create a duration span context manager.

        Args:
            name: Span name
            category: Event category
            args: Additional event arguments
        """
        start_time = time.time() * 1_000_000

        try:
            yield
        finally:
            end_time = time.time() * 1_000_000
            duration = end_time - start_time

            event = TraceEvent(
                name=name,
                event_type=EventType.COMPLETE,
                timestamp=start_time,
                duration=duration,
                category=category,
                args=args,
            )
            self._write_event(event)

    def begin_span(
        self,
        name: str,
        category: str = "default",
        args: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Begin a duration span that can end in a different thread.

        Args:
            name: Span name
            category: Event category
            args: Additional event arguments

        Returns:
            Span ID for ending the span later
        """
        span_id = str(uuid.uuid4())

        begin_event = TraceEvent(
            name=name, event_type=EventType.DURATION_BEGIN, category=category, args=args
        )

        with self._lock:
            self._active_spans[span_id] = begin_event

        self._write_event(begin_event)
        return span_id

    def end_span(self, span_id: str, args: Optional[Dict[str, Any]] = None):
        """End a duration span started with begin_span.

        Args:
            span_id: Span ID returned by begin_span
            args: Additional event arguments for the end event
        """
        with self._lock:
            begin_event = self._active_spans.pop(span_id, None)

        if begin_event is None:
            return

        end_event = TraceEvent(
            name=begin_event.name,
            event_type=EventType.DURATION_END,
            category=begin_event.category,
            args=args,
        )
        self._write_event(end_event)

    def async_begin(
        self,
        name: str,
        async_id: Optional[str] = None,
        category: str = "default",
        args: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Begin an async event.

        Args:
            name: Event name
            async_id: Async event ID (generated if not provided)
            category: Event category
            args: Additional event arguments

        Returns:
            Async event ID
        """
        if async_id is None:
            async_id = str(uuid.uuid4())

        # Get consistent thread ID for this async operation
        thread_id = self._get_async_thread_id(async_id)

        event = TraceEvent(
            name=name,
            event_type=EventType.ASYNC_START,
            category=category,
            args=args,
            async_id=async_id,
            thread_id=thread_id,
        )

        with self._lock:
            self._async_events[async_id] = event

        self._write_event(event)
        return async_id

    def async_instant(
        self,
        async_id: str,
        name: str,
        category: str = "default",
        args: Optional[Dict[str, Any]] = None,
    ):
        """Record an async instant event.

        Args:
            async_id: Async event ID
            name: Event name
            category: Event category
            args: Additional event arguments
        """
        # Get consistent thread ID for this async operation
        thread_id = self._get_async_thread_id(async_id)

        event = TraceEvent(
            name=name,
            event_type=EventType.ASYNC_INSTANT,
            category=category,
            args=args,
            async_id=async_id,
            thread_id=thread_id,
        )
        self._write_event(event)

    def async_end(self, async_id: str, args: Optional[Dict[str, Any]] = None):
        """End an async event.

        Args:
            async_id: Async event ID
            args: Additional event arguments
        """
        with self._lock:
            begin_event = self._async_events.pop(async_id, None)
            # Get thread ID before potentially cleaning it up
            thread_id = self._async_thread_ids.get(async_id)

        if begin_event is None:
            return

        # Use the same thread ID as the begin event
        if thread_id is None:
            thread_id = begin_event.thread_id

        event = TraceEvent(
            name=begin_event.name,
            event_type=EventType.ASYNC_END,
            category=begin_event.category,
            args=args,
            async_id=async_id,
            thread_id=thread_id,
        )
        self._write_event(event)

        # Clean up thread ID mapping after the async operation is complete
        with self._lock:
            self._async_thread_ids.pop(async_id, None)


# Global tracer instance
_global_tracer: Optional[Tracer] = None
_tracer_lock = threading.Lock()


def get_global_tracer() -> Optional[Tracer]:
    """Get the global tracer instance."""
    return _global_tracer


def set_global_tracer(tracer: Tracer):
    """Set the global tracer instance."""
    global _global_tracer
    with _tracer_lock:
        _global_tracer = tracer


def trace_function(
    name: Optional[str] = None,
    category: str = "function",
    args: Optional[Dict[str, Any]] = None,
):
    """Decorator to trace function execution.

    Args:
        name: Trace name (defaults to function name)
        category: Event category
        args: Additional event arguments
    """

    def decorator(func: F) -> F:
        trace_name = name or func.__name__

        @functools.wraps(func)
        def wrapper(*args_tuple, **kwargs):
            tracer = get_global_tracer()
            if tracer is None or not tracer.enabled:
                return func(*args_tuple, **kwargs)

            with tracer.span(trace_name, category, args):
                return func(*args_tuple, **kwargs)

        return wrapper

    return decorator


def trace_async_function(
    name: Optional[str] = None,
    category: str = "async_function",
    args: Optional[Dict[str, Any]] = None,
):
    """Decorator to trace async function execution.

    Args:
        name: Trace name (defaults to function name)
        category: Event category
        args: Additional event arguments
    """

    def decorator(func: F) -> F:
        trace_name = name or func.__name__

        @functools.wraps(func)
        async def async_wrapper(*args_tuple, **kwargs):
            tracer = get_global_tracer()
            if tracer is None or not tracer.enabled:
                return await func(*args_tuple, **kwargs)

            async_id = tracer.async_begin(trace_name, category=category, args=args)
            try:
                result = await func(*args_tuple, **kwargs)
                return result
            finally:
                tracer.async_end(async_id)

        return async_wrapper

    return decorator
