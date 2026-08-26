from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    ActionPlan,
    CreateAlertRule,
    ListRules,
    QueryStatus,
    Unsupported,
)
from app.service import process_command
from app.store import RULE_STORE, clear_rules


client = TestClient(app)


def setup_function():
    """
    Reset the in-memory rule store before every test.
    """
    clear_rules()


def teardown_function():
    """
    Reset the in-memory rule store after every test.
    """
    clear_rules()


# ---------------------------------------------------------------------------
# Existing API tests
# ---------------------------------------------------------------------------


def test_root_endpoint():
    response = client.get("/")

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True
    assert "Natural Language Action Agent is running." in data["message"]


def test_empty_command():
    response = client.post(
        "/command",
        json={"text": ""},
    )

    assert response.status_code == 400

    data = response.json()

    assert data["success"] is False
    assert data["error"] == "EMPTY_COMMAND"


def test_invalid_request_format():
    response = client.post(
        "/command",
        json={},
    )

    assert response.status_code == 422

    data = response.json()

    assert data["success"] is False
    assert data["error"] == "REQUEST_VALIDATION_ERROR"


def test_create_alert_command(monkeypatch):
    """
    Test the API response for a successfully created alert.

    The LLM layer is mocked so this test does not require Ollama.
    """

    def fake_process_command(text: str):
        action = CreateAlertRule(
            device_id="warehouse-3",
            metric="temperature",
            condition="ABOVE",
            threshold=40,
            duration_minutes=10,
            notify_via=["EMAIL"],
        )

        return {
            "action": action.model_dump(),
            "result": {
                "success": True,
                "message": "Alert rule created successfully.",
                "rule": action.model_dump(),
            },
        }

    monkeypatch.setattr(
        "app.main.process_command",
        fake_process_command,
    )

    response = client.post(
        "/command",
        json={
            "text": (
                "Alert me if warehouse-3 temperature stays "
                "above 40 degrees for more than 10 minutes"
            )
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True
    assert data["action"]["type"] == "CREATE_ALERT_RULE"
    assert data["action"]["device_id"] == "warehouse-3"
    assert data["action"]["metric"] == "temperature"
    assert data["action"]["condition"] == "ABOVE"
    assert data["action"]["threshold"] == 40
    assert data["action"]["duration_minutes"] == 10


def test_query_status_command(monkeypatch):
    """
    Test the API response for a device-status query.
    """

    def fake_process_command(text: str):
        action = QueryStatus(
            device_id="cold-storage-1",
            metric="humidity",
        )

        return {
            "action": action.model_dump(),
            "result": {
                "success": True,
                "device_id": "cold-storage-1",
                "metric": "humidity",
                "value": 71.0,
            },
        }

    monkeypatch.setattr(
        "app.main.process_command",
        fake_process_command,
    )

    response = client.post(
        "/command",
        json={
            "text": "what is the humidity in cold-storage-1 right now"
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True
    assert data["action"]["type"] == "QUERY_STATUS"
    assert data["action"]["device_id"] == "cold-storage-1"
    assert data["action"]["metric"] == "humidity"
    assert data["result"]["value"] == 71.0


def test_unsupported_command(monkeypatch):
    """
    Unsupported operations should be handled safely without
    attempting physical device control.
    """

    def fake_process_command(text: str):
        action = Unsupported(
            reason=(
                "System does not directly control physical devices "
                "or equipment."
            )
        )

        return {
            "action": action.model_dump(),
            "result": {
                "success": False,
                "message": "Unsupported request.",
                "reason": action.reason,
            },
        }

    monkeypatch.setattr(
        "app.main.process_command",
        fake_process_command,
    )

    response = client.post(
        "/command",
        json={
            "text": "turn off all the lights in building 7"
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True
    assert data["action"]["type"] == "UNSUPPORTED"
    assert data["result"]["success"] is False


def test_validation_error():
    """
    ValueError raised by the validation layer should become
    a clean HTTP 422 response.
    """

    def fake_process_command(text: str):
        raise ValueError(
            "Device 'reactor-core' does not exist in the device registry."
        )

    import app.main

    original_process_command = app.main.process_command
    app.main.process_command = fake_process_command

    try:
        response = client.post(
            "/command",
            json={
                "text": (
                    "alert me if the reactor-core "
                    "pressure exceeds 9000"
                )
            },
        )
    finally:
        app.main.process_command = original_process_command

    assert response.status_code == 422

    data = response.json()

    assert data["success"] is False
    assert data["error"] == "VALIDATION_ERROR"
    assert "reactor-core" in data["message"]


def test_rules_endpoint_empty():
    response = client.get("/rules")

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True
    assert data["count"] == 0
    assert data["rules"] == []


def test_rules_endpoint_returns_stored_rules():
    rule = {
        "type": "CREATE_ALERT_RULE",
        "device_id": "warehouse-3",
        "metric": "temperature",
        "condition": "ABOVE",
        "threshold": 40.0,
        "duration_minutes": 10.0,
        "notify_via": ["EMAIL"],
    }

    RULE_STORE.append(rule)

    response = client.get("/rules")

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True
    assert data["count"] == 1
    assert len(data["rules"]) == 1

    returned_rule = data["rules"][0]

    assert returned_rule["device_id"] == "warehouse-3"
    assert returned_rule["metric"] == "temperature"
    assert returned_rule["threshold"] == 40.0


def test_rules_endpoint_filters_by_device():
    RULE_STORE.extend(
        [
            {
                "type": "CREATE_ALERT_RULE",
                "device_id": "warehouse-3",
                "metric": "temperature",
                "condition": "ABOVE",
                "threshold": 40.0,
                "duration_minutes": 10.0,
                "notify_via": ["EMAIL"],
            },
            {
                "type": "CREATE_ALERT_RULE",
                "device_id": "cold-storage-1",
                "metric": "humidity",
                "condition": "BELOW",
                "threshold": 30.0,
                "duration_minutes": 5.0,
                "notify_via": ["EMAIL"],
            },
        ]
    )

    response = client.get(
        "/rules",
        params={"device_id": "warehouse-3"},
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True
    assert data["count"] == 1
    assert data["rules"][0]["device_id"] == "warehouse-3"


def test_front_gate_camera_is_unsupported(monkeypatch):
    """
    Event/state-based camera alerts are intentionally unsupported.
    """

    def fake_process_command(text: str):
        action = Unsupported(
            reason=(
                "Event-based alert conditions such as camera "
                "offline are not currently supported. "
                "Alert rules require a numeric threshold."
            )
        )

        return {
            "action": action.model_dump(),
            "result": {
                "success": False,
                "message": "Unsupported request.",
                "reason": action.reason,
            },
        }

    monkeypatch.setattr(
        "app.main.process_command",
        fake_process_command,
    )

    response = client.post(
        "/command",
        json={
            "text": (
                "notify security if the front-gate "
                "camera goes offline"
            )
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True
    assert data["action"]["type"] == "UNSUPPORTED"
    assert data["result"]["success"] is False


# ---------------------------------------------------------------------------
# Multi-action tests
# ---------------------------------------------------------------------------


def test_multi_action_multiple_status_queries(monkeypatch):
    """
    Multiple explicitly requested metrics should become separate
    QUERY_STATUS actions and execute independently.
    """

    plan = ActionPlan(
        actions=[
            QueryStatus(
                device_id="warehouse-3",
                metric="temperature",
            ),
            QueryStatus(
                device_id="warehouse-3",
                metric="humidity",
            ),
        ]
    )

    monkeypatch.setattr(
        "app.service.extract_action_plan",
        lambda text: plan,
    )

    result = process_command(
        "what is the temperature and humidity in warehouse-3"
    )

    assert result["success"] is True
    assert result["action_count"] == 2
    assert len(result["actions"]) == 2

    first = result["actions"][0]
    second = result["actions"][1]

    assert first["success"] is True
    assert first["action"]["type"] == "QUERY_STATUS"
    assert first["action"]["device_id"] == "warehouse-3"
    assert first["action"]["metric"] == "temperature"
    assert first["result"]["value"] == 36.5

    assert second["success"] is True
    assert second["action"]["type"] == "QUERY_STATUS"
    assert second["action"]["device_id"] == "warehouse-3"
    assert second["action"]["metric"] == "humidity"
    assert second["result"]["value"] == 58.0


def test_multi_action_mixed_intents(monkeypatch):
    """
    A single request may contain different supported operation types.
    """

    plan = ActionPlan(
        actions=[
            QueryStatus(
                device_id="warehouse-3",
                metric="temperature",
            ),
            ListRules(
                device_id="warehouse-3",
            ),
        ]
    )

    monkeypatch.setattr(
        "app.service.extract_action_plan",
        lambda text: plan,
    )

    result = process_command(
        "check the temperature of warehouse-3 "
        "and show me its alert rules"
    )

    assert result["success"] is True
    assert result["action_count"] == 2
    assert len(result["actions"]) == 2

    first = result["actions"][0]
    second = result["actions"][1]

    assert first["success"] is True
    assert first["action"]["type"] == "QUERY_STATUS"
    assert first["action"]["metric"] == "temperature"
    assert first["result"]["value"] == 36.5

    assert second["success"] is True
    assert second["action"]["type"] == "LIST_RULES"
    assert second["action"]["device_id"] == "warehouse-3"
    assert second["result"]["count"] == 0


def test_multi_action_multiple_alert_rules(monkeypatch):
    """
    Multiple explicitly requested alert rules should be created
    independently.
    """

    plan = ActionPlan(
        actions=[
            CreateAlertRule(
                device_id="warehouse-3",
                metric="temperature",
                condition="ABOVE",
                threshold=40,
                duration_minutes=0,
                notify_via=["EMAIL"],
            ),
            CreateAlertRule(
                device_id="warehouse-3",
                metric="humidity",
                condition="BELOW",
                threshold=30,
                duration_minutes=0,
                notify_via=["EMAIL"],
            ),
        ]
    )

    monkeypatch.setattr(
        "app.service.extract_action_plan",
        lambda text: plan,
    )

    result = process_command(
        "create a temperature alert for warehouse-3 above 40 "
        "and a humidity alert for warehouse-3 below 30"
    )

    assert result["success"] is True
    assert result["action_count"] == 2
    assert len(result["actions"]) == 2

    assert len(RULE_STORE) == 2

    first = result["actions"][0]
    second = result["actions"][1]

    assert first["success"] is True
    assert first["action"]["type"] == "CREATE_ALERT_RULE"
    assert first["action"]["device_id"] == "warehouse-3"
    assert first["action"]["metric"] == "temperature"
    assert first["action"]["condition"] == "ABOVE"
    assert first["action"]["threshold"] == 40.0

    assert second["success"] is True
    assert second["action"]["type"] == "CREATE_ALERT_RULE"
    assert second["action"]["device_id"] == "warehouse-3"
    assert second["action"]["metric"] == "humidity"
    assert second["action"]["condition"] == "BELOW"
    assert second["action"]["threshold"] == 30.0


def test_multi_action_ambiguous_parameter_is_rejected(monkeypatch):
    """
    An ambiguous parameter in one action should fail that action
    without preventing another valid action from executing.
    """

    plan = ActionPlan(
        actions=[
            QueryStatus(
                device_id="warehouse-3",
                metric="temperature",
            ),
            QueryStatus(
                device_id="tipper-101",
                metric="temperature",
            ),
        ]
    )

    monkeypatch.setattr(
        "app.service.extract_action_plan",
        lambda text: plan,
    )

    result = process_command(
        "what is the temperature in warehouse-3 "
        "and the temperature in tipper-101"
    )

    assert result["success"] is False
    assert result["action_count"] == 2
    assert len(result["actions"]) == 2

    valid_action = result["actions"][0]
    invalid_action = result["actions"][1]

    assert valid_action["success"] is True
    assert valid_action["action"]["device_id"] == "warehouse-3"
    assert valid_action["action"]["metric"] == "temperature"
    assert valid_action["result"]["value"] == 36.5

    assert invalid_action["success"] is False
    assert invalid_action["action"]["device_id"] == "tipper-101"
    assert invalid_action["action"]["metric"] == "temperature"
    assert "Multiple parameters match" in invalid_action["error"]
    assert "hydraulic_temperature" in invalid_action["error"]
    assert "engine_temperature" in invalid_action["error"]
    assert "oil_temperature" in invalid_action["error"]


def test_multi_action_unknown_parameter_is_rejected(monkeypatch):
    """
    An unknown parameter in one action should fail that action
    without preventing another valid action from executing.
    """

    plan = ActionPlan(
        actions=[
            QueryStatus(
                device_id="warehouse-3",
                metric="temperature",
            ),
            QueryStatus(
                device_id="tipper-101",
                metric="battery_voltage",
            ),
        ]
    )

    monkeypatch.setattr(
        "app.service.extract_action_plan",
        lambda text: plan,
    )

    result = process_command(
        "what is the temperature in warehouse-3 "
        "and the battery voltage in tipper-101"
    )

    assert result["success"] is False
    assert result["action_count"] == 2
    assert len(result["actions"]) == 2

    valid_action = result["actions"][0]
    invalid_action = result["actions"][1]

    assert valid_action["success"] is True
    assert valid_action["action"]["device_id"] == "warehouse-3"
    assert valid_action["action"]["metric"] == "temperature"
    assert valid_action["result"]["value"] == 36.5

    assert invalid_action["success"] is False
    assert invalid_action["action"]["device_id"] == "tipper-101"
    assert invalid_action["action"]["metric"] == "battery_voltage"
    assert "battery_voltage" in invalid_action["error"]
    assert "not registered" in invalid_action["error"]