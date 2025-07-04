# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import logging

from core.event import Event


class ThreadingEventManager:

    def __init__(self):
        self._event_consumers = {}

    def clear(self):
        for k, event_list in self._event_consumers.items():
            for e in event_list:
                e.set()
        self._event_consumers.clear()

    def register_consumer(self, event_name) -> Event:
        assert isinstance(event_name, str), "event_name can only be str"
        logging.debug(f"register consumer for event {event_name}")
        event = Event(event_name)
        event_list = self._event_consumers.get(event_name, [])
        event_list.append(event)
        self._event_consumers[event_name] = event_list
        return event

    def produce_event(self, event_name):
        logging.debug(f"produce event {event_name}")
        if event_name not in self._event_consumers:
            logging.debug(f"no consumers found for event: {event_name}")
            return
        for event in self._event_consumers[event_name]:
            event.set()
        self._event_consumers[event_name].clear()
