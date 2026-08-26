from app.models import (
    CreateAlertRule,
    ListRules,
    QueryStatus,
    Unsupported,
)
from app.store import add_rule, get_rules


# Deterministic mock sensor values.
# These are intentionally fixed so that tests are reproducible.
MOCK_SENSOR_DATA = {
    "warehouse-3": {
        "temperature": 36.5,
        "humidity": 58.0,
    },
    "cold-storage-1": {
        "temperature": 4.2,
        "humidity": 71.0,
    },
    "front-gate": {
        "camera_status": "ONLINE",
        "occupancy": 3,
    },
    "server-room-1": {
        "temperature": 22.5,
        "humidity": 45.0,
    },
    "production-floor-1": {
        "temperature": 24.0,
        "humidity": 50.0,
        "occupancy": 18,
    },
    "loading-bay-1": {
        "temperature": 28.0,
        "occupancy": 7,
    },

    # Real-world style asset mock data for the upgraded
    # Asset -> Sensor -> Parameter model.
    "tipper-101": {
        "hydraulic_temperature": 72.5,
        "hydraulic_pressure": 185.0,
        "engine_temperature": 91.0,
        "oil_temperature": 87.5,
        "engine_pressure": 42.0,
    },
    "concrete-mixer-101": {
        "engine_temperature": 88.0,
        "oil_temperature": 82.5,
        "hydraulic_temperature": 69.0,
        "hydraulic_pressure": 172.0,
    },
}


def execute_action(action):
    """
    Execute a validated Action.

    This function never performs validation itself.
    Validation must happen before execution.
    """

    if isinstance(action, CreateAlertRule):
        return _execute_create_alert_rule(action)

    if isinstance(action, QueryStatus):
        return _execute_query_status(action)

    if isinstance(action, ListRules):
        return _execute_list_rules(action)

    if isinstance(action, Unsupported):
        return _execute_unsupported(action)

    raise ValueError(f"Unsupported action type: {type(action).__name__}")


def _execute_create_alert_rule(action: CreateAlertRule) -> dict:
    """
    Store a new alert rule in memory.
    """

    rule = action.model_dump()

    add_rule(rule)

    return {
        "success": True,
        "message": "Alert rule created successfully.",
        "rule": rule,
    }


def _execute_query_status(action: QueryStatus) -> dict:
    """
    Return a deterministic mock sensor value.
    """

    device_data = MOCK_SENSOR_DATA.get(action.device_id)

    if device_data is None:
        raise ValueError(
            f"No mock sensor data exists for device '{action.device_id}'."
        )

    if action.metric is None:
        return {
            "success": True,
            "device_id": action.device_id,
            "data": device_data,
        }

    if action.metric not in device_data:
        raise ValueError(
            f"No mock data exists for metric '{action.metric}' "
            f"on device '{action.device_id}'."
        )

    return {
        "success": True,
        "device_id": action.device_id,
        "metric": action.metric,
        "value": device_data[action.metric],
    }


def _execute_list_rules(action: ListRules) -> dict:
    """
    Return stored alert rules.
    """

    rules = get_rules(action.device_id)

    return {
        "success": True,
        "rules": rules,
        "count": len(rules),
    }


def _execute_unsupported(action: Unsupported) -> dict:
    """
    Return a safe rejection for unsupported requests.
    """

    return {
        "success": False,
        "message": "Unsupported request.",
        "reason": action.reason,
    }