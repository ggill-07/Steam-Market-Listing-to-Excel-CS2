from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


PROVIDER_STEAM = "steam"
PROVIDER_SKINPORT = "skinport"
PROVIDER_CSFLOAT = "csfloat"


@dataclass(frozen=True)
class ProviderDefinition:
    key: str
    display_name: str
    requires_auth: bool
    supports_wear_items: bool
    supports_no_wear_price_snapshots: bool
    supports_exact_name_validation: bool
    readiness: str
    notes: str


PROVIDER_DEFINITIONS: Dict[str, ProviderDefinition] = {
    PROVIDER_STEAM: ProviderDefinition(
        key=PROVIDER_STEAM,
        display_name="Steam (native)",
        requires_auth=False,
        supports_wear_items=True,
        supports_no_wear_price_snapshots=True,
        supports_exact_name_validation=True,
        readiness="ready",
        notes="Current authoritative source for listings, floats, and market snapshots.",
    ),
    PROVIDER_SKINPORT: ProviderDefinition(
        key=PROVIDER_SKINPORT,
        display_name="Skinport (official API)",
        requires_auth=False,
        supports_wear_items=False,
        supports_no_wear_price_snapshots=True,
        supports_exact_name_validation=False,
        readiness="research",
        notes=(
            "Official public item summaries look promising for cross-checking commodity prices, "
            "but the in-app adapter is still being wired up."
        ),
    ),
    PROVIDER_CSFLOAT: ProviderDefinition(
        key=PROVIDER_CSFLOAT,
        display_name="CSFloat (auth required)",
        requires_auth=True,
        supports_wear_items=True,
        supports_no_wear_price_snapshots=True,
        supports_exact_name_validation=False,
        readiness="auth_required",
        notes=(
            "Live listing access appears possible, but the market search flow requires an "
            "authenticated session or token before we can rely on it."
        ),
    ),
}


def list_provider_definitions() -> List[ProviderDefinition]:
    return [PROVIDER_DEFINITIONS[key] for key in (PROVIDER_STEAM, PROVIDER_SKINPORT, PROVIDER_CSFLOAT)]


def get_provider_definition(provider_key: str) -> ProviderDefinition:
    return PROVIDER_DEFINITIONS.get(provider_key, PROVIDER_DEFINITIONS[PROVIDER_STEAM])


def get_provider_choice_labels() -> List[str]:
    return [definition.display_name for definition in list_provider_definitions()]


def get_provider_choice_mapping() -> Dict[str, str]:
    return {definition.display_name: definition.key for definition in list_provider_definitions()}


def get_provider_label(provider_key: str) -> str:
    return get_provider_definition(provider_key).display_name


def describe_provider_status(provider_key: str) -> str:
    definition = get_provider_definition(provider_key)
    if definition.key == PROVIDER_STEAM:
        return "Steam is the active source. This mode is fully implemented."
    if definition.requires_auth:
        return (
            f"{definition.display_name} is feasible, but it needs authentication before we can "
            "trust it for live market results."
        )
    return (
        f"{definition.display_name} looks feasible for future price cross-checks. "
        "This branch is preparing the adapter surface now."
    )
