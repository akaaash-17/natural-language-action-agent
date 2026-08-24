from app.models import (
    CreateAlertRule,
    QueryStatus,
    ListRules,
    Unsupported,
)
from app.registry import DEVICE_REGISTRY


def validate_device(device_id: str) -> None:
    """Check whether a device exists in our registry."""
    if device_id not in DEVICE_REGISTRY:
        raise ValueError(
            f"Device '{device_id}' does not exist in the device registry."
        )


def validate_metric(device_id: str, metric: str) -> None:
    """Check whether a metric is supported by the given device."""
    validate_device(device_id)

    supported_metrics = DEVICE_REGISTRY[device_id]["metrics"]

    if metric not in supported_metrics:
        raise ValueError(
            f"Metric '{metric}' is not supported by device '{device_id}'."
        )


def validate_action(action) -> None:
    """
    Validate an action against our mock facility registry.
    Raises ValueError when the action cannot be executed safely.
    """

    if isinstance(action, CreateAlertRule):
        validate_metric(action.device_id, action.metric)

    elif isinstance(action, QueryStatus):
        validate_device(action.device_id)

        if action.metric is not None:
            validate_metric(action.device_id, action.metric)

    elif isinstance(action, ListRules):
        if action.device_id is not None:
            validate_device(action.device_id)

    elif isinstance(action, Unsupported):
        # Unsupported actions are intentionally not executable.
        return

    else:
        raise ValueError(
            f"Unsupported action type: {type(action).__name__}"
        )