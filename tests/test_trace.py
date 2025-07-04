"""Basic tests for the trace module."""

import asyncio
import json
import os
import tempfile
import threading
import time
import unittest

from core.trace.event import EventType, TraceEvent
from core.trace.tracer import Tracer, set_global_tracer, trace_async_function, trace_function
from core.trace.writer import ChromeTraceWriter


class TestTraceEvent(unittest.TestCase):
    """Test TraceEvent class."""

    def test_event_creation(self):
        """Test basic event creation."""
        event = TraceEvent("test_event", EventType.INSTANT)
        self.assertEqual(event.name, "test_event")
        self.assertEqual(event.event_type, EventType.INSTANT)
        self.assertIsNotNone(event.timestamp)
        self.assertIsNotNone(event.process_id)
        self.assertIsNotNone(event.thread_id)

    def test_event_to_dict(self):
        """Test event serialization to dictionary."""
        event = TraceEvent(
            "test_event",
            EventType.COMPLETE,
            timestamp=1000000,
            duration=500000,
            args={"key": "value"},
        )

        event_dict = event.to_dict()
        self.assertEqual(event_dict["name"], "test_event")
        self.assertEqual(event_dict["ph"], "X")
        self.assertEqual(event_dict["ts"], 1000000)
        self.assertEqual(event_dict["dur"], 500000)
        self.assertEqual(event_dict["args"], {"key": "value"})


class TestChromeTraceWriter(unittest.TestCase):
    """Test ChromeTraceWriter class."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.trace_file = os.path.join(self.temp_dir, "test_trace.json")

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.trace_file):
            os.remove(self.trace_file)
        os.rmdir(self.temp_dir)

    def test_write_single_event(self):
        """Test writing a single event."""
        event = TraceEvent("test", EventType.INSTANT)

        with ChromeTraceWriter(self.trace_file) as writer:
            writer.write_event(event)

        # Verify file content
        with open(self.trace_file, "r") as f:
            content = f.read()

        self.assertTrue(content.startswith("["))
        self.assertTrue(content.endswith("]\n"))

        # Parse JSON to verify structure
        trace_data = json.loads(content)
        self.assertEqual(len(trace_data), 1)
        self.assertEqual(trace_data[0]["name"], "test")

    def test_write_multiple_events(self):
        """Test writing multiple events."""
        events = [
            TraceEvent("event1", EventType.INSTANT),
            TraceEvent("event2", EventType.INSTANT),
            TraceEvent("event3", EventType.INSTANT),
        ]

        with ChromeTraceWriter(self.trace_file) as writer:
            writer.write_events(events)

        # Verify file content
        with open(self.trace_file, "r") as f:
            trace_data = json.load(f)

        self.assertEqual(len(trace_data), 3)
        self.assertEqual(trace_data[0]["name"], "event1")
        self.assertEqual(trace_data[1]["name"], "event2")
        self.assertEqual(trace_data[2]["name"], "event3")


class TestTracer(unittest.TestCase):
    """Test Tracer class."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.trace_file = os.path.join(self.temp_dir, "test_trace.json")
        self.tracer = Tracer(self.trace_file)

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.trace_file):
            os.remove(self.trace_file)
        os.rmdir(self.temp_dir)

    def test_span_context_manager(self):
        """Test span context manager."""
        with self.tracer:
            with self.tracer.span("test_span"):
                time.sleep(0.01)  # Small delay to ensure duration > 0

        # Verify trace file was created and contains events
        self.assertTrue(os.path.exists(self.trace_file))

        with open(self.trace_file, "r") as f:
            trace_data = json.load(f)

        # Should have at least the span event and process metadata
        self.assertGreater(len(trace_data), 0)

        # Find the span event
        span_events = [e for e in trace_data if e.get("name") == "test_span"]
        self.assertEqual(len(span_events), 1)
        self.assertEqual(span_events[0]["ph"], "X")  # Complete event
        self.assertGreater(span_events[0]["dur"], 0)  # Should have duration

    def test_cross_thread_spans(self):
        """Test spans that begin and end in different threads."""
        span_id = None

        def start_span():
            nonlocal span_id
            span_id = self.tracer.begin_span("cross_thread_span")

        def end_span():
            self.tracer.end_span(span_id)

        with self.tracer:
            # Start span in one thread
            thread1 = threading.Thread(target=start_span)
            thread1.start()
            thread1.join()

            # End span in another thread
            thread2 = threading.Thread(target=end_span)
            thread2.start()
            thread2.join()

        # Verify events were written
        with open(self.trace_file, "r") as f:
            trace_data = json.load(f)

        span_events = [e for e in trace_data if e.get("name") == "cross_thread_span"]
        self.assertEqual(len(span_events), 2)  # Begin and end events

        begin_event = next(e for e in span_events if e["ph"] == "B")
        end_event = next(e for e in span_events if e["ph"] == "E")

        self.assertIsNotNone(begin_event)
        self.assertIsNotNone(end_event)

    def test_async_events(self):
        """Test async event tracking."""

        async def async_test():
            async_id = self.tracer.async_begin("async_operation")
            await asyncio.sleep(0.01)
            self.tracer.async_instant(async_id, "async_checkpoint")
            await asyncio.sleep(0.01)
            self.tracer.async_end(async_id)

        with self.tracer:
            asyncio.run(async_test())

        # Verify async events
        with open(self.trace_file, "r") as f:
            trace_data = json.load(f)

        async_events = [e for e in trace_data if e.get("name") == "async_operation"]
        self.assertEqual(len(async_events), 2)  # Start and end events

        start_event = next(e for e in async_events if e["ph"] == "b")
        end_event = next(e for e in async_events if e["ph"] == "e")

        self.assertIsNotNone(start_event)
        self.assertIsNotNone(end_event)
        self.assertEqual(start_event["id"], end_event["id"])


class TestDecorators(unittest.TestCase):
    """Test tracing decorators."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.trace_file = os.path.join(self.temp_dir, "test_trace.json")
        self.tracer = Tracer(self.trace_file)
        set_global_tracer(self.tracer)

    def tearDown(self):
        """Clean up test fixtures."""
        set_global_tracer(None)
        if os.path.exists(self.trace_file):
            os.remove(self.trace_file)
        os.rmdir(self.temp_dir)

    def test_function_decorator(self):
        """Test function tracing decorator."""

        @trace_function("decorated_function")
        def test_function():
            time.sleep(0.01)
            return "result"

        with self.tracer:
            result = test_function()

        self.assertEqual(result, "result")

        # Verify trace was recorded
        with open(self.trace_file, "r") as f:
            trace_data = json.load(f)

        function_events = [
            e for e in trace_data if e.get("name") == "decorated_function"
        ]
        self.assertEqual(len(function_events), 1)
        self.assertEqual(function_events[0]["ph"], "X")  # Complete event

    def test_async_function_decorator(self):
        """Test async function tracing decorator."""

        @trace_async_function("decorated_async_function")
        async def test_async_function():
            await asyncio.sleep(0.01)
            return "async_result"

        async def run_test():
            result = await test_async_function()
            return result

        with self.tracer:
            result = asyncio.run(run_test())

        self.assertEqual(result, "async_result")

        # Verify async trace was recorded
        with open(self.trace_file, "r") as f:
            trace_data = json.load(f)

        async_events = [
            e for e in trace_data if e.get("name") == "decorated_async_function"
        ]
        self.assertEqual(len(async_events), 2)  # Start and end events


if __name__ == "__main__":
    unittest.main()
