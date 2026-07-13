"""
ContextBuilder - gathers non-video context for an incident, fail-safe.

Runs each registered provider, guards every string against accusatory language
(reusing the same validator rules the rest of the system enforces), and returns
a ContextBundle. A provider that raises becomes exactly one UNAVAILABLE item;
the pipeline never crashes because a side data source is down.
"""

from typing import List, Optional

from alibi.schemas import Incident
from alibi.config import VantageConfig, DEFAULT_CONFIG
from alibi.validator import contains_forbidden_language, suggest_neutral_alternative
from alibi.context.schemas import Availability, ContextBundle, ContextItem
from alibi.context.provider import ContextProvider
from alibi.context.providers.baseline import BaselineContextProvider
from alibi.context.providers.intelligence import IntelligenceContextProvider
from alibi.context.providers.known_persons import KnownPersonsContextProvider


def default_providers() -> List[ContextProvider]:
    """Internal, real-data providers enabled by default (no external integrations)."""
    return [
        BaselineContextProvider(),
        IntelligenceContextProvider(),
        KnownPersonsContextProvider(),
    ]


def _neutralize(text: str) -> str:
    """Ensure context text can never smuggle accusatory language into the prompt."""
    if not text:
        return text
    if not contains_forbidden_language(text):
        return text
    fixed = suggest_neutral_alternative(text)
    if contains_forbidden_language(fixed):
        # Last resort: drop the wording entirely rather than leak an accusation.
        return "[context redacted for neutral language]"
    return fixed


def build_context(
    incident: Incident,
    config: Optional[VantageConfig] = None,
    providers: Optional[List[ContextProvider]] = None,
) -> ContextBundle:
    """
    Gather context for an incident. Never raises.

    Args:
        incident: the incident being assessed
        config: optional config (DEFAULT_CONFIG if omitted)
        providers: override the provider set (defaults to internal real-data providers)
    """
    if config is None:
        config = DEFAULT_CONFIG
    if providers is None:
        providers = default_providers()

    items: List[ContextItem] = []
    for provider in providers:
        try:
            produced = provider.fetch(incident, config) or []
        except Exception as e:  # fail-safe: one UNAVAILABLE item, never crash
            items.append(ContextItem(
                provider=getattr(provider, "name", provider.__class__.__name__),
                label=getattr(provider, "name", provider.__class__.__name__),
                availability=Availability.UNAVAILABLE,
                summary="",
                source="provider error",
                metadata={"error": str(e)[:200]},
            ))
            continue

        for item in produced:
            item.summary = _neutralize(item.summary)
            item.caution_signals = [_neutralize(s) for s in item.caution_signals]
            items.append(item)

    return ContextBundle(items=items)
