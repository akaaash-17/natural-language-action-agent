from typing import Any


# Rules remain available for the lifetime of the application process.
RULE_STORE: list[dict[str, Any]] = []


def add_rule(rule: dict[str, Any]) -> dict[str, Any]:
    """
    Store an alert rule in memory and return the stored rule.
    """

    RULE_STORE.append(rule)

    return rule


def get_rules(device_id: str | None = None) -> list[dict[str, Any]]:
    """
    Return all stored rules, optionally filtered by device.
    """

    if device_id is None:
        return RULE_STORE.copy()

    return [
        rule
        for rule in RULE_STORE
        if rule.get("device_id") == device_id
    ]


def clear_rules() -> None:
    """
    Clear all stored rules.

    Useful for tests.
    """

    RULE_STORE.clear()