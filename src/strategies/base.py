"""Managed strategy interface; compatibility brokers are not plugins."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class StrategyPlugin(Protocol):
    """Declare native execution and separate decision features from future labels."""

    name: str
    native_execution_capabilities: frozenset[str]

    def generate_events(self, features: Any) -> Any: ...

    def compute_Primary_Signal(self, features: Any) -> Any: ...

    def get_feature_manifest(self) -> dict[str, Any]: ...

    def get_barrier_config(self) -> dict[str, Any] | None: ...
