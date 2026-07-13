"""
alibi.context - external-data fusion for the incident advisor.

Public API:
    build_context(incident, config=None, providers=None) -> ContextBundle
    ContextBundle, ContextItem, Availability
    ContextProvider  (subclass to add a new data source)
"""

from alibi.context.schemas import Availability, ContextBundle, ContextItem
from alibi.context.provider import ContextProvider
from alibi.context.builder import build_context, default_providers

__all__ = [
    "Availability",
    "ContextBundle",
    "ContextItem",
    "ContextProvider",
    "build_context",
    "default_providers",
]
