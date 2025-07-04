"""Chrome trace writer for outputting trace events to JSON files."""

import json
import os
import threading
from typing import List, Optional, TextIO

from .event import TraceEvent


class ChromeTraceWriter:
    """Writer for Chrome tracing format JSON files."""

    def __init__(self, filepath: str, auto_flush: bool = True):
        """Initialize the trace writer.

        Args:
            filepath: Path to the output trace file
            auto_flush: Whether to flush after each write
        """
        self.filepath = filepath
        self.auto_flush = auto_flush
        self._file: Optional[TextIO] = None
        self._lock = threading.Lock()
        self._first_event = True

        # Ensure directory exists
        dir_path = os.path.dirname(filepath)
        if dir_path:  # Only create directory if path is not empty
            os.makedirs(dir_path, exist_ok=True)

    def __enter__(self):
        """Context manager entry."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def open(self):
        """Open the trace file for writing."""
        with self._lock:
            if self._file is None:
                self._file = open(self.filepath, "w", encoding="utf-8")
                # Start JSON array
                self._file.write("[\n")
                self._first_event = True

    def close(self):
        """Close the trace file."""
        with self._lock:
            if self._file is not None:
                # End JSON array
                self._file.write("\n]\n")
                self._file.close()
                self._file = None

    def write_event(self, event: TraceEvent):
        """Write a single trace event to the file.

        Args:
            event: The trace event to write
        """
        with self._lock:
            if self._file is None:
                raise RuntimeError(
                    "Writer is not open. Use 'with' statement or call open() first."
                )

            # Add comma separator for non-first events
            if not self._first_event:
                self._file.write(",\n")
            else:
                self._first_event = False

            # Write event as JSON
            event_json = json.dumps(event.to_dict(), separators=(",", ":"))
            self._file.write(f"  {event_json}")

            if self.auto_flush:
                self._file.flush()

    def write_events(self, events: List[TraceEvent]):
        """Write multiple trace events to the file.

        Args:
            events: List of trace events to write
        """
        for event in events:
            self.write_event(event)

    def write_metadata(self, name: str, args: dict, process_id: Optional[int] = None):
        """Write metadata event.

        Args:
            name: Metadata name (e.g., 'process_name', 'thread_name')
            args: Metadata arguments
            process_id: Process ID for the metadata
        """
        from .event import EventType

        metadata_event = TraceEvent(
            name=name,
            event_type=EventType.METADATA,
            process_id=process_id,
            thread_id=0,  # Metadata events typically use thread 0
            args=args,
        )
        self.write_event(metadata_event)

    def flush(self):
        """Flush the file buffer."""
        with self._lock:
            if self._file is not None:
                self._file.flush()
