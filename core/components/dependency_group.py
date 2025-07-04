# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import logging
import os
from abc import ABC
from pathlib import Path

from core.components.component import Component
from core.event_manager import ThreadingEventManager
from core.exceptions import HabitatException
from core.fetchers.local_fetcher import LocalFetcher
from core.settings import MAX_DEPENDENCY_WAIT_TIME
from core.trace import get_global_tracer
from core.utils import cycle_detection


async def fetch_child(child, *args, events=None, **kwargs):
    logging.debug(
        f'fetch child {child.name} parent: {child.parent} children: {getattr(child, "children", [])}'
    )
    for e in events or []:
        logging.debug(f"Waiting on event {e}")
        try:
            await asyncio.wait_for(e.wait(), MAX_DEPENDENCY_WAIT_TIME)
        except asyncio.TimeoutError:
            raise HabitatException(
                f"Timeout of {MAX_DEPENDENCY_WAIT_TIME} "
                f"seconds expired when waiting on event {e} for {child.name}."
            )
        logging.debug(f"Got event {e}")
    await child.fetch(*args, **kwargs)


def get_final_components_to_fetch(components_to_fetch):
    has_new_skipped_component = False
    logging.debug(f"Before filter: components => {components_to_fetch.keys()}")
    for name in list(components_to_fetch.keys()):
        require = getattr(components_to_fetch[name], "require", [])
        if set(require) - set(components_to_fetch.keys()):
            has_new_skipped_component = True
            logging.warning(
                f"Skip component {name} due to the fact that some requirements were skipped"
            )
            components_to_fetch.pop(name, None)

    logging.debug(f"After filter: components => {components_to_fetch.keys()}")
    if has_new_skipped_component:
        get_final_components_to_fetch(components_to_fetch)


class DependencyGroup(Component, ABC):
    def __init__(
        self,
        target_dir: Path,
        config_dict: dict,
        parent: Component = None,
        entries=None,
    ):
        super().__init__(target_dir, config_dict, parent, entries)
        self._children = []
        self._event_manager = ThreadingEventManager()

    @property
    def children(self):
        return self._children

    @property
    def event_manager(self):
        return self._event_manager

    def produce_event(self, event_name):
        self._event_manager.produce_event(event_name)

    def add_child(self, child: Component):
        self._children.append(child)
        if not getattr(child, "parent", None):
            child.set_parent(child)

    async def fetch(
        self, root_dir, options, existing_sources=None, existing_targets=None
    ):
        await super(DependencyGroup, self).fetch(
            root_dir, options, existing_sources, existing_targets
        )
        await self.fetch_children(root_dir, options, existing_sources, existing_targets)
        self.on_children_fetched(root_dir, options)

    async def fetch_children(
        self, root_dir, options, existing_sources=None, existing_targets=None
    ):
        tracer = get_global_tracer()
        async_id = None
        if tracer:
            async_id = tracer.async_begin(
                f"fetch_children_{self.name}",
                category="dependency_group",
                args={"children_count": len(self._children) if self._children else 0},
            )

        logging.info(f"Sync dependency group {self.name}")
        if not self._children:
            if tracer and async_id:
                tracer.async_instant(
                    async_id,
                    f"fetch_children_{self.name}_no_children",
                    category="dependency_group",
                )
                tracer.async_end(async_id)
            return

        try:
            futures = []
            existing_sources = existing_sources or {}
            existing_targets = existing_targets or {}
            components_to_fetch = {}
            for child in self._children:
                if not child.condition:
                    logging.info(
                        f"skip dependency {child.name} due to unsatisfied condition"
                    )
                    continue

                # check if dependencies conflict
                source_item = existing_sources.get(child.source)
                if source_item:
                    if source_item.source_stamp != child.source_stamp:
                        message = (
                            f"source stamps conflict:\n  {source_item.source_stamp} ({source_item.target_dir})"
                            f" vs {child.source_stamp} ({child.target_dir})"
                        )
                        if options.strict:
                            # In strict mode, conflicts of source stamp conflicts are allowed
                            raise HabitatException(message)

                        logging.warning(message)
                    if set(getattr(source_item, "paths", [])) == set(
                        getattr(child, "paths", [])
                    ):
                        # We can simply create a symbolic if two packages have the same paths sources
                        child.fetcher = LocalFetcher(
                            child, source_item, symlink=not child.disable_link
                        )
                        components_to_fetch[child.name] = child
                        continue

                # Same targets but different sources
                target_normpath = os.path.normpath(child.target_dir)
                target_item = existing_targets.get(target_normpath)
                if target_item:
                    if target_item.source != child.source:
                        logging.warning(
                            f"Skip fetching {child.source} to {child.target_dir} "
                            f"because another source {target_item.source} exists in the same directory"
                        )
                    continue
                components_to_fetch[child.name] = child

            # Filter out components whose require has been skipped recursively
            get_final_components_to_fetch(components_to_fetch)

            # cycle detection
            if tracer:
                tracer.async_instant(
                    async_id,
                    f"fetch_children_{self.name}_cycle_detection",
                    category="dependency_group",
                )
            cycle_detection(components_to_fetch)

            # Fetch children
            if tracer:
                tracer.async_instant(
                    async_id,
                    f"fetch_children_{self.name}_start_parallel_fetch",
                    category="dependency_group",
                )
            for name, child in components_to_fetch.items():
                require = getattr(child, "require", [])
                events = []

                for r in require:
                    events.append(self._event_manager.register_consumer(r))

                f = fetch_child(
                    child,
                    root_dir,
                    options,
                    existing_sources,
                    existing_targets,
                    events=events,
                )
                futures.append(f)
                target_normpath = os.path.normpath(child.target_dir)
                existing_targets[target_normpath] = child
                if not existing_sources.get(child.source):
                    existing_sources[child.source] = child

            await asyncio.gather(*futures)
        except Exception as e:
            if tracer and async_id:
                tracer.async_instant(
                    async_id,
                    f"fetch_children_{self.name}_error",
                    category="dependency_group",
                    args={"error": str(e)},
                )
            self._event_manager.clear()
            raise
        finally:
            if tracer and async_id:
                tracer.async_end(async_id)

    def on_children_fetched(self, root_dir, options):
        pass
