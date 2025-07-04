# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import logging
from abc import ABC
from pathlib import Path
from typing import Any

from core.exceptions import HabitatException
from core.fetchers.dummy_fetcher import DummyFetcher
from core.trace import get_global_tracer


class Component(ABC):
    type = None
    source_attributes = None
    source_stamp_attributes = None
    is_component = True
    defined_fields = {}
    _defined_fields = {
        "condition": {"default": True},
        "require": {"optional": True},
        "ignore_in_git": {"default": False},
        "fetch_mode": {"default": None},
        "disable_link": {"default": False},
    }

    def __init__(
        self,
        target_dir: Path,
        config_dict: dict,
        parent: "Component" = None,
        entries=None,
    ):
        self._attr_dict = {
            "target_dir": target_dir,
            "parent": parent,
            "global_entries": entries,
            **config_dict,
        }
        self.fetcher = DummyFetcher(self)
        self.fetched = False
        self.fetched_paths = []
        self.check_and_populate_config()

    def __getattr__(self, item):
        if item.startswith("__"):
            return super().__getattr__(item)
        try:
            return self._attr_dict[item]
        except KeyError:
            raise AttributeError(f"attribute {item} not found")

    def __str__(self):
        return f"{self.name}(target_dir: {self.target_dir} fetched:{self.fetched})"

    @property
    def attributes(self):
        return self._attr_dict

    @property
    def is_root(self):
        return self.parent is None

    @property
    def source(self):
        return ":".join(getattr(self, a) for a in self.source_attributes)

    @property
    def source_stamp(self):
        return (
            self.source
            + "@"
            + "+".join(
                [
                    getattr(self, a, "")
                    for a in self.source_stamp_attributes
                    if hasattr(self, a) and getattr(self, a)
                ]
            )
        )

    def set_attr(self, name, value, override=False):
        if name in self._attr_dict and not override:
            raise HabitatException(f"attribute {name} exists")
        self._attr_dict[name] = value

    def list_deps(self):
        root = self
        while not root.is_root:
            root = root.parent

        components = [root]
        while components:
            p = components.pop(0)
            children = getattr(p, "children", [])
            yield p
            for c in children:
                components.append(c)

    def get_pretty_dependency_tree(self):
        root = self
        while not root.is_root:
            root = root.parent

        components = [root]
        tree_str = root.name
        indent = ""
        while components:
            p = components.pop(0)
            children = getattr(p, "children", [])
            indent += "   "
            for c in children:
                tree_str += f"\n{indent}└──{c.name}"
                components.append(c)
        return tree_str

    def check_and_populate_config(self):
        fields = {**self._defined_fields, **self.defined_fields}
        for name, field_attr in fields.items():
            optional = field_attr.get("optional", False)
            if not optional and not hasattr(self, name) and "default" not in field_attr:
                raise HabitatException(
                    f"field {name} is required for {self} but not exist."
                )

            value = getattr(self, name, None)
            if value is None and not optional:
                default_value = field_attr["type"]() if "type" in field_attr else None
                value = field_attr.get("default", default_value)
                setattr(self, name, value)

            if (
                value
                and "validator" in field_attr
                and not field_attr["validator"](value, self)
            ):
                raise HabitatException(
                    f"invalid value {value} for field {name} in {self}"
                )

            _type: Any = field_attr.get("type")
            if _type and not optional and not isinstance(getattr(self, name), _type):
                raise HabitatException(
                    f"field {name} require a {_type}, but got a {type(value)}"
                )

    def set_parent(self, parent: "Component"):
        setattr(self, "parent", parent)

    def on_fetched(self, root_dir, options):
        self.fetched = True

    def up_to_date(self):
        return self.local_source_stamps.get(self.name) == self.source_stamp

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
            if options.force or not self.up_to_date():
                if tracer:
                    tracer.async_instant(
                        async_id,
                        f"fetch_{self.name}_start_fetching",
                        category="component_fetch",
                    )
                self.fetched_paths = await self.fetcher.fetch(root_dir, options)
            else:
                logging.debug(
                    f"local source stamp cache cache of {self.name} is synchronized with source stamp, "
                    f"skip fetching"
                )
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
            raise HabitatException(
                f"failed to fetch dependency {self.source_stamp} to {self.target_dir}"
            ) from e
        finally:
            if tracer and async_id:
                tracer.async_end(async_id)
            if hasattr(self, "parent") and self.parent:
                self.parent.produce_event(self.name)

    def __repr__(self):
        return str(self._attr_dict)
