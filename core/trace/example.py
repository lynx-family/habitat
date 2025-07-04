"""Example usage of the trace module."""

import asyncio
import threading
import time

from .tracer import Tracer, set_global_tracer, trace_async_function, trace_function


@trace_function(name="sync_work", category="computation")
def do_sync_work(duration: float):
    """Example synchronous function with tracing."""
    time.sleep(duration)
    return f"Sync work completed in {duration}s"


@trace_async_function(name="async_work", category="async_computation")
async def do_async_work(duration: float):
    """Example asynchronous function with tracing."""
    await asyncio.sleep(duration)
    return f"Async work completed in {duration}s"


def worker_thread(tracer: Tracer, thread_id: int):
    """Example worker thread that creates spans across threads."""
    # Begin a span in this thread
    span_id = tracer.begin_span(f"worker_thread_{thread_id}", category="threading")

    # Do some work
    time.sleep(0.1)
    tracer.instant(f"worker_{thread_id}_checkpoint", category="threading")

    # End the span
    tracer.end_span(span_id)


async def async_worker(tracer: Tracer, worker_id: int):
    """Example async worker with manual async tracing."""
    # Begin async event
    async_id = tracer.async_begin(f"async_worker_{worker_id}", category="async_work")

    # Simulate async work
    await asyncio.sleep(0.05)
    tracer.async_instant(
        async_id, f"async_worker_{worker_id}_progress", category="async_work"
    )

    await asyncio.sleep(0.05)

    # End async event
    tracer.async_end(async_id)


def demonstrate_tracing():
    """Demonstrate various tracing features."""
    # Create and configure tracer
    tracer = Tracer("example_trace.json")
    set_global_tracer(tracer)

    with tracer:
        # Basic span usage
        with tracer.span("main_operation", category="example"):
            # Instant events
            tracer.instant("operation_start", category="example")

            # Counter events
            tracer.counter("memory_usage", 1024, category="metrics")

            # Traced function calls
            result1 = do_sync_work(0.1)
            print(result1)

            # Cross-thread spans
            threads = []
            for i in range(3):
                thread = threading.Thread(target=worker_thread, args=(tracer, i))
                threads.append(thread)
                thread.start()

            for thread in threads:
                thread.join()

            # Async operations
            async def async_demo():
                # Traced async function
                result2 = await do_async_work(0.1)
                print(result2)

                # Manual async tracing
                tasks = []
                for i in range(3):
                    task = asyncio.create_task(async_worker(tracer, i))
                    tasks.append(task)

                await asyncio.gather(*tasks)

            # Run async demo
            asyncio.run(async_demo())

            tracer.instant("operation_end", category="example")

    print(f"Trace written to {tracer.output_file}")


if __name__ == "__main__":
    demonstrate_tracing()
