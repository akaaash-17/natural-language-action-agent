from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    ActionPlan,
    CreateAlertRule,
    ListRules,
    QueryStatus,
)
from app.store import RULE_STORE, clear_rules
from app.service import process_command as app_service_process


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
        return {
            "success": True,
            "message": "Alert rule created successfully.",
            "device_id": "warehouse-3",
            "metric": "temperature",
            "condition": "ABOVE",
            "threshold": 40,
            "duration_minutes": 10,
            "current_value": 36.5,
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
    assert data["message"] == "Alert rule created successfully."
    assert data["device_id"] == "warehouse-3"
    assert data["metric"] == "temperature"
    assert data["condition"] == "ABOVE"
    assert data["threshold"] == 40
    assert data["duration_minutes"] == 10
    assert data["current_value"] == 36.5


def test_query_status_command(monkeypatch):
    """
    Test the API response for a device-status query.
    """

    def fake_process_command(text: str):
        return {
            "success": True,
            "message": "Current value retrieved successfully.",
            "device_id": "cold-storage-1",
            "metric": "humidity",
            "current_value": 71.0,
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
    assert data["message"] == "Current value retrieved successfully."
    assert data["device_id"] == "cold-storage-1"
    assert data["metric"] == "humidity"
    assert data["current_value"] == 71.0


def test_unsupported_command(monkeypatch):
    """
    Unsupported operations should be reported as unsuccessful
    user requests while still returning HTTP 200.
    """

    def fake_process_command(text: str):
        return {
            "success": False,
            "message": (
                "System does not directly control physical devices "
                "or equipment."
            ),
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

    assert data["success"] is False
    assert data["message"] == (
        "System does not directly control physical devices "
        "or equipment."
    )


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
        return {
            "success": False,
            "message": (
                "Event-based alert conditions such as camera "
                "offline are not currently supported. "
                "Alert rules require a numeric threshold."
            ),
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

    assert data["success"] is False
    assert data["message"] == (
        "Event-based alert conditions such as camera "
        "offline are not currently supported. "
        "Alert rules require a numeric threshold."
    )


def test_multi_action_multiple_status_queries(monkeypatch):
    """
    Multiple explicitly requested metrics should become separate
    QUERY_STATUS actions and return clean user-facing results.
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

    result = app_service_process(
        "what is the temperature and humidity in warehouse-3"
    )

    assert result["success"] is True
    assert len(result["results"]) == 2

    first = result["results"][0]
    second = result["results"][1]

    assert first["success"] is True
    assert first["device_id"] == "warehouse-3"
    assert first["metric"] == "temperature"
    assert first["current_value"] == 36.5

    assert second["success"] is True
    assert second["device_id"] == "warehouse-3"
    assert second["metric"] == "humidity"
    assert second["current_value"] == 58.0


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

    result = app_service_process(
        "check the temperature of warehouse-3 "
        "and show me its alert rules"
    )

    assert result["success"] is True
    assert len(result["results"]) == 2

    status_result = result["results"][0]
    rules_result = result["results"][1]

    assert status_result["success"] is True
    assert status_result["device_id"] == "warehouse-3"
    assert status_result["metric"] == "temperature"
    assert status_result["current_value"] == 36.5

    assert rules_result["success"] is True
    assert rules_result["device_id"] == "warehouse-3"
    assert rules_result["count"] == 0
    assert rules_result["rules"] == []


def test_multi_action_multiple_alert_rules(monkeypatch):
    """
    Multiple explicitly requested alert rules should be created
    independently and return clean results.
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

    result = app_service_process(
        "create a temperature alert for warehouse-3 above 40 "
        "and a humidity alert for warehouse-3 below 30"
    )

    assert result["success"] is True
    assert len(result["results"]) == 2

    temperature_result = result["results"][0]
    humidity_result = result["results"][1]

    assert temperature_result["success"] is True
    assert temperature_result["device_id"] == "warehouse-3"
    assert temperature_result["metric"] == "temperature"
    assert temperature_result["condition"] == "ABOVE"
    assert temperature_result["threshold"] == 40
    assert temperature_result["current_value"] == 36.5

    assert humidity_result["success"] is True
    assert humidity_result["device_id"] == "warehouse-3"
    assert humidity_result["metric"] == "humidity"
    assert humidity_result["condition"] == "BELOW"
    assert humidity_result["threshold"] == 30
    assert humidity_result["current_value"] == 58.0


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

    result = app_service_process(
        "what is the temperature in warehouse-3 "
        "and the temperature in tipper-101"
    )

    assert result["success"] is False
    assert len(result["results"]) == 2

    valid_result = result["results"][0]
    failed_result = result["results"][1]

    assert valid_result["success"] is True
    assert valid_result["device_id"] == "warehouse-3"
    assert valid_result["metric"] == "temperature"
    assert valid_result["current_value"] == 36.5

    assert failed_result["success"] is False
    assert failed_result["device_id"] == "tipper-101"
    assert failed_result["metric"] == "temperature"
    assert "Multiple parameters match" in failed_result["message"]


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

    result = app_service_process(
        "what is the temperature in warehouse-3 "
        "and the battery voltage in tipper-101"
    )

    assert result["success"] is False
    assert len(result["results"]) == 2

    valid_result = result["results"][0]
    failed_result = result["results"][1]

    assert valid_result["success"] is True
    assert valid_result["device_id"] == "warehouse-3"
    assert valid_result["metric"] == "temperature"
    assert valid_result["current_value"] == 36.5

    assert failed_result["success"] is False
    assert failed_result["device_id"] == "tipper-101"
    assert failed_result["metric"] == "battery_voltage"
    assert "not registered" in failed_result["message"]


def test_multi_asset_same_intent(monkeypatch):
    """
    The same intent can target different assets.
    """

    plan = ActionPlan(
        actions=[
            QueryStatus(
                device_id="warehouse-3",
                metric="temperature",
            ),
            QueryStatus(
                device_id="tipper-101",
                metric="hydraulic_temperature",
            ),
        ]
    )

    monkeypatch.setattr(
        "app.service.extract_action_plan",
        lambda text: plan,
    )

    result = app_service_process(
        "what is the temperature in warehouse-3 and "
        "the hydraulic temperature in tipper-101"
    )

    assert result["success"] is True
    assert len(result["results"]) == 2

    assert result["results"][0]["device_id"] == "warehouse-3"
    assert result["results"][0]["current_value"] == 36.5

    assert result["results"][1]["device_id"] == "tipper-101"
    assert result["results"][1]["metric"] == "hydraulic_temperature"
    assert result["results"][1]["current_value"] == 72.5


def test_multi_asset_mixed_intents(monkeypatch):
    """
    Different intents can target different assets.
    """

    plan = ActionPlan(
        actions=[
            CreateAlertRule(
                device_id="warehouse-3",
                metric="temperature",
                condition="ABOVE",
                threshold=400,
                duration_minutes=0,
                notify_via=["EMAIL"],
            ),
            QueryStatus(
                device_id="tipper-101",
                metric="hydraulic_pressure",
            ),
            ListRules(
                device_id="cold-storage-1",
            ),
        ]
    )

    monkeypatch.setattr(
        "app.service.extract_action_plan",
        lambda text: plan,
    )

    result = app_service_process(
        "alert warehouse-3 if temperature goes above 400, "
        "check hydraulic pressure of tipper-101, "
        "and show alert rules for cold-storage-1"
    )

    assert result["success"] is True
    assert len(result["results"]) == 3

    alert_result = result["results"][0]
    pressure_result = result["results"][1]
    rules_result = result["results"][2]

    assert alert_result["success"] is True
    assert alert_result["device_id"] == "warehouse-3"
    assert alert_result["metric"] == "temperature"
    assert alert_result["threshold"] == 400
    assert alert_result["current_value"] == 36.5

    assert pressure_result["success"] is True
    assert pressure_result["device_id"] == "tipper-101"
    assert pressure_result["metric"] == "hydraulic_pressure"
    assert pressure_result["current_value"] == 185.0

    assert rules_result["success"] is True
    assert rules_result["device_id"] == "cold-storage-1"
    assert rules_result["count"] == 0


def test_multi_asset_partial_failure(monkeypatch):
    """
    One invalid action should not prevent valid actions on other
    assets from executing.
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

    result = app_service_process(
        "what is the temperature of warehouse-3 "
        "and the temperature of tipper-101"
    )

    assert result["success"] is False
    assert len(result["results"]) == 2

    assert result["results"][0]["success"] is True
    assert result["results"][0]["device_id"] == "warehouse-3"
    assert result["results"][0]["current_value"] == 36.5

    assert result["results"][1]["success"] is False
    assert result["results"][1]["device_id"] == "tipper-101"
    assert "Multiple parameters match" in (
        result["results"][1]["message"]
    )