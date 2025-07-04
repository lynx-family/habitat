#!/usr/bin/env python3
"""
Integration example showing how the trace module works with Habitat components.
This script demonstrates the tracing functionality across different components.
"""

import asyncio
import logging
import tempfile
from pathlib import Path

# Import trace module
from . import Tracer, get_global_tracer, set_global_tracer

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


# Mock classes to simulate Habitat components
class MockOptions:
    def __init__(self):
        self.force = False
        self.clean = False
        self.strict = False


class MockComponent:
    def __init__(self, name, source, target_dir):
        self.name = name
        self.source = source
        self.target_dir = target_dir
        self.type = "mock"
        self.source_stamp = f"{source}@main"
        self.fetched_paths = []

    def up_to_date(self):
        return False

    def on_fetched(self, root_dir, options):
        pass


class MockFetcher:
    def __init__(self, component):
        self.component = component

    async def fetch(self, root_dir, options):
        tracer = get_global_tracer()
        if tracer:
            with tracer.span(
                f"mock_fetch_{self.component.name}", category="mock_fetcher"
            ):
                # Simulate some work
                await asyncio.sleep(0.1)
                logging.info(f"Mock fetching {self.component.source}")
                await asyncio.sleep(0.1)
        else:
            await asyncio.sleep(0.2)
            logging.info(f"Mock fetching {self.component.source}")
        return [self.component.target_dir]


class MockComponentWithTrace(MockComponent):
    def __init__(self, name, source, target_dir):
        super().__init__(name, source, target_dir)
        self.fetcher = MockFetcher(self)

    async def fetch(
        self, root_dir, options, existing_sources=None, existing_targets=None
    ):
        tracer = get_global_tracer()
        async_id = None
        if tracer:
            async_id = tracer.async_begin(
                f"fetch_{self.name}",
                category="component_fetch",
                args={"component_type": self.type, "source": self.source},
            )

        logging.info(f"Sync dependency {self.name}")
        try:
            if not self.up_to_date():
                if tracer:
                    tracer.async_instant(
                        async_id,
                        f"fetch_{self.name}_start_fetching",
                        category="component_fetch",
                    )
                self.fetched_paths = await self.fetcher.fetch(root_dir, options)
            else:
                if tracer:
                    tracer.async_instant(
                        async_id,
                        f"fetch_{self.name}_skip_cached",
                        category="component_fetch",
                    )
            self.on_fetched(root_dir, options)
        except Exception as e:
            if tracer and async_id:
                tracer.async_instant(
                    async_id,
                    f"fetch_{self.name}_error",
                    category="component_fetch",
                    args={"error": str(e)},
                )
            raise
        finally:
            if tracer and async_id:
                tracer.async_end(async_id)


class MockSolution:
    def __init__(self, name, components):
        self.name = name
        self.components = components

    async def fetch(self, root_dir, options):
        tracer = get_global_tracer()
        async_id = None
        if tracer:
            async_id = tracer.async_begin(
                f"solution_fetch_{self.name}",
                category="solution",
                args={
                    "solution_name": self.name,
                    "components_count": len(self.components),
                },
            )

        logging.info(f"Sync solution {self.name}")
        try:
            # Fetch all components in parallel
            tasks = []
            for component in self.components:
                task = asyncio.create_task(component.fetch(root_dir, options))
                tasks.append(task)

            await asyncio.gather(*tasks)

            if tracer:
                tracer.async_instant(
                    async_id,
                    f"solution_fetch_{self.name}_complete",
                    category="solution",
                )
        except Exception as e:
            if tracer and async_id:
                tracer.async_instant(
                    async_id,
                    f"solution_fetch_{self.name}_error",
                    category="solution",
                    args={"error": str(e)},
                )
            raise
        finally:
            if tracer and async_id:
                tracer.async_end(async_id)


async def main():
    # Initialize tracer
    trace_file = "habitat_integration_trace.json"

    with Tracer(trace_file) as tracer:
        set_global_tracer(tracer)

        logging.info(f"Starting Habitat integration example with tracing to {trace_file}")

        try:
            with tracer.span("habitat_integration_example", category="main"):
                # Create mock components
                components = [
                    MockComponentWithTrace(
                        "component1",
                        "https://github.com/example/repo1.git",
                        "deps/repo1",
                    ),
                    MockComponentWithTrace(
                        "component2",
                        "https://github.com/example/repo2.git",
                        "deps/repo2",
                    ),
                    MockComponentWithTrace(
                        "component3",
                        "https://github.com/example/repo3.git",
                        "deps/repo3",
                    ),
                ]

                # Create mock solution
                solution = MockSolution("example_solution", components)

                # Create temporary directory
                with tempfile.TemporaryDirectory() as temp_dir:
                    root_dir = Path(temp_dir)
                    options = MockOptions()

                    # Fetch solution
                    await solution.fetch(root_dir, options)

                tracer.instant("integration_example_complete", category="main")
                logging.info("Integration example completed successfully")

        except Exception as e:
            tracer.instant(
                "integration_example_error", category="main", args={"error": str(e)}
            )
            logging.error(f"Integration example failed: {e}")
            raise

    logging.info(f"Trace written to {trace_file}")


if __name__ == "__main__":
    asyncio.run(main())
