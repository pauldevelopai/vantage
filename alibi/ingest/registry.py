"""Connectors, by name.

Adding a source type means writing a fetch() and registering it here. Nothing
in the core changes, which is the whole reason the split exists.
"""

from typing import Dict

from alibi.ingest.source import Connector

_REGISTRY: Dict[str, Connector] = {}


def register(connector: Connector) -> Connector:
    _REGISTRY[connector.name] = connector
    return connector


def get(name: str) -> Connector:
    if name not in _REGISTRY:
        raise KeyError(f"no connector named {name!r}; have {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def available() -> list:
    return sorted(_REGISTRY)
