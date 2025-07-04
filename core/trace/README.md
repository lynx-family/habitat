# Trace Module

A comprehensive tracing module for performance monitoring and debugging that generates Chrome tracing format files. This module supports synchronous operations, asynchronous events, and events that span across different threads.

## Features

- **Chrome Tracing Format**: Generates JSON files compatible with Chrome's `chrome://tracing` viewer
- **Thread-Safe**: Safe to use across multiple threads
- **Async Support**: Full support for async/await operations
- **Cross-Thread Events**: Events can begin in one thread and end in another
- **Multiple Event Types**: Supports duration, instant, counter, async, and metadata events
- **Decorators**: Easy-to-use decorators for function and async function tracing
- **Context Managers**: Convenient span context managers for scoped tracing

## Quick Start

### Basic Usage

```python
from oss.core.trace import Tracer, set_global_tracer

# Create and configure tracer
tracer = Tracer('my_trace.json')
set_global_tracer(tracer)

with tracer:
    # Record an instant event
    tracer.instant('application_start')
    
    # Use span context manager
    with tracer.span('main_operation'):
        # Your code here
        pass
    
    # Record counter values
    tracer.counter('memory_usage', 1024)
```

### Function Decorators

```python
from oss.core.trace import trace_function, trace_async_function

@trace_function(name='my_function', category='computation')
def my_function(x, y):
    return x + y

@trace_async_function(name='my_async_function', category='async_computation')
async def my_async_function():
    await asyncio.sleep(1)
    return 'done'
```

### Cross-Thread Events

```python
import threading

def worker_thread(tracer):
    # Begin span in this thread
    span_id = tracer.begin_span('worker_operation')
    
    # Do work...
    time.sleep(1)
    
    # End span (can be called from different thread)
    tracer.end_span(span_id)

# Start worker thread
thread = threading.Thread(target=worker_thread, args=(tracer,))
thread.start()
thread.join()
```

### Async Events

```python
async def async_operation(tracer):
    # Begin async event
    async_id = tracer.async_begin('async_task')
    
    # Async work
    await asyncio.sleep(0.5)
    tracer.async_instant(async_id, 'checkpoint')
    
    await asyncio.sleep(0.5)
    
    # End async event
    tracer.async_end(async_id)
```

## API Reference

### Tracer Class

The main tracer class for collecting and writing trace events.

#### Constructor

```python
Tracer(output_file='trace.json', enabled=True)
```

- `output_file`: Path to output trace file
- `enabled`: Whether tracing is enabled

#### Methods

##### Context Management

- `start()`: Start the tracer and open output file
- `stop()`: Stop the tracer and close output file
- Can be used as context manager: `with tracer:`

##### Event Recording

- `instant(name, category='default', args=None)`: Record instant event
- `counter(name, value, category='default')`: Record counter event
- `span(name, category='default', args=None)`: Context manager for duration spans

##### Cross-Thread Spans

- `begin_span(name, category='default', args=None)`: Begin duration span, returns span ID
- `end_span(span_id, args=None)`: End duration span using span ID

##### Async Events

- `async_begin(name, async_id=None, category='default', args=None)`: Begin async event
- `async_instant(async_id, name, category='default', args=None)`: Record async instant
- `async_end(async_id, args=None)`: End async event

### Decorators

#### trace_function

```python
@trace_function(name=None, category='function', args=None)
def my_function():
    pass
```

Decorator for tracing synchronous function execution.

#### trace_async_function

```python
@trace_async_function(name=None, category='async_function', args=None)
async def my_async_function():
    pass
```

Decorator for tracing asynchronous function execution.

### Global Tracer

- `get_global_tracer()`: Get the global tracer instance
- `set_global_tracer(tracer)`: Set the global tracer instance

## Event Types

The module supports various Chrome tracing event types:

- **Duration Events**: `DURATION_BEGIN` (B), `DURATION_END` (E), `COMPLETE` (X)
- **Instant Events**: `INSTANT` (i)
- **Counter Events**: `COUNTER` (C)
- **Async Events**: `ASYNC_START` (b), `ASYNC_INSTANT` (n), `ASYNC_END` (e)
- **Flow Events**: `FLOW_START` (s), `FLOW_STEP` (t), `FLOW_END` (f)
- **Metadata Events**: `METADATA` (M)

## Viewing Traces

1. Open Chrome browser
2. Navigate to `chrome://tracing`
3. Click "Load" and select your trace file
4. Explore the timeline visualization

## Best Practices

1. **Use Context Managers**: Prefer `with tracer.span()` for automatic cleanup
2. **Meaningful Names**: Use descriptive names for events and categories
3. **Appropriate Categories**: Group related events with consistent categories
4. **Global Tracer**: Set up global tracer early in application lifecycle
5. **Conditional Tracing**: Use `enabled` parameter to disable tracing in production
6. **Resource Management**: Always use context managers or explicit start/stop calls

## Thread Safety

The tracer is fully thread-safe and supports:

- Multiple threads writing events simultaneously
- Events that begin in one thread and end in another
- Async operations across different event loops
- Cross-thread span correlation

## Performance Considerations

- Events are written immediately to file (configurable buffering)
- Minimal overhead when tracing is disabled
- Efficient JSON serialization
- Thread-safe operations with minimal locking

## Example Output

The generated trace file is a JSON array of events compatible with Chrome tracing:

```json
[
  {
    "name": "main_operation",
    "ph": "X",
    "ts": 1234567890123456,
    "dur": 1000000,
    "pid": 12345,
    "tid": 67890,
    "cat": "default"
  },
  {
    "name": "async_task",
    "ph": "b",
    "ts": 1234567890123456,
    "pid": 12345,
    "tid": 67890,
    "cat": "async",
    "id": "async-123"
  }
]
```

## Testing

Run the test suite:

```bash
python -m unittest oss.core.trace.test_trace
```

Or run the example:

```bash
python -m oss.core.trace.example
```