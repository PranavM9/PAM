"""M0 data contracts (SPEC §7).

Behavior:
    Each module is a verbatim copy of one §7 code block (§7.12 is split into `reports` and `graph`).
    Changing a contract requires an APPROVED §10 entry.
"""

from __future__ import annotations

import importlib

from pydantic import BaseModel, TypeAdapter

CONTRACT_MODULES = (
    "common", "raw", "episode", "fact", "project", "skill", "agent",
    "retrieval", "working", "writes", "reports", "graph", "config", "api", "connector",
)


def all_models() -> dict[str, type[BaseModel] | TypeAdapter]:
    """Collect every public contract model by name.

    Behavior:
        A public model is a `BaseModel` subclass defined in a contract module whose name has no
        leading underscore; the `PamModel` base is excluded. `ChatEvent`, an annotated union, is
        added as a `TypeAdapter`. Used by `pam schema export` and the round-trip tests.
    Returns:
        Models keyed by name, sorted alphabetically.
    """
    from .api import ChatEvent
    from .common import PamModel

    models: dict[str, type[BaseModel] | TypeAdapter] = {}
    for mod_name in CONTRACT_MODULES:
        mod = importlib.import_module(f"{__name__}.{mod_name}")
        for name, obj in vars(mod).items():
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseModel)
                and obj.__module__ == mod.__name__
                and not name.startswith("_")
                and obj is not PamModel
            ):
                models[name] = obj
    models["ChatEvent"] = TypeAdapter(ChatEvent)
    return dict(sorted(models.items()))
