"""Stable adapter contract and registry."""

from .base import (
    AdapterCapability,
    AdapterContext,
    AdapterDetection,
    AgentAdapter,
    CapabilityStatus,
)
from .manifest import AdapterManifest
from .registry import AdapterRegistry

__all__ = [
    "AdapterCapability",
    "AdapterContext",
    "AdapterDetection",
    "AdapterManifest",
    "AdapterRegistry",
    "AgentAdapter",
    "CapabilityStatus",
]
