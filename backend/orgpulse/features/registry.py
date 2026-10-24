"""Feature modules gated by a capability.

A module registers its capability key, API router, sync job and UI cards, so a
new paid feature is one new file in orgpulse/modules/ and one import line.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter


@dataclass(frozen=True)
class UiCard:
    id: str
    title: str
    description: str  # one line on what it shows; used on the locked card too


@dataclass
class FeatureModule:
    key: str  # capability key, e.g. "vault"
    title: str
    requires: str  # shown on locked cards, e.g. "Business Plus or above"
    description: str
    how_to_enable: str  # URL
    page: str  # frontend route
    paid: bool = True
    router: APIRouter | None = None
    sync: Callable[[uuid.UUID], Any] | None = None
    # APScheduler trigger kwargs, e.g. {"trigger": "interval", "hours": 6}
    schedule: dict[str, Any] = field(default_factory=lambda: {"trigger": "interval", "hours": 6})
    cards: list[UiCard] = field(default_factory=list)


REGISTRY: dict[str, FeatureModule] = {}


def register(module: FeatureModule) -> FeatureModule:
    if module.key in REGISTRY:
        raise ValueError(f"feature {module.key!r} registered twice")
    REGISTRY[module.key] = module
    return module


def load_modules() -> dict[str, FeatureModule]:
    import orgpulse.modules  # noqa: F401  (each module registers itself on import)

    return REGISTRY
