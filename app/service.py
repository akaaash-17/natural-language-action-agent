from app.executor import execute_action
from app.llm_parser import (
    extract_alert_fields,
    extract_list_rules_fields,
    extract_status_fields,
    extract_unsupported_reason,
)
from app.models import (
    CreateAlertRule,
    ListRules,
    QueryStatus,
    Unsupported,
)
from app.router import route_intent
from app.validator import validate_action


def process_command(text: str) -> dict:
    """
    Convert a natural-language command into a validated Action
    and execute it against the mock backend.
    """

    intent = route_intent(text)

    if intent == "CREATE_ALERT_RULE":
        fields = extract_alert_fields(text)

        # Current alert rules support numeric threshold-based
        # conditions. Event/state-based alerts such as
        # camera OFFLINE are intentionally unsupported.
        if (
            fields.metric == "camera_status"
            or fields.threshold is None
        ):
            action = Unsupported(
                reason=(
                    "Event-based alert conditions such as camera "
                    "offline are not currently supported. "
                    "Alert rules require a numeric threshold."
                )
            )

        else:
            action = CreateAlertRule(
                device_id=fields.device,
                metric=fields.metric,
                condition=fields.condition.upper(),
                threshold=fields.threshold,
                duration_minutes=(
                    fields.duration_minutes
                    if fields.duration_minutes is not None
                    else 0
                ),
                notify_via=["EMAIL"],
            )

    elif intent == "QUERY_STATUS":
        fields = extract_status_fields(text)

        action = QueryStatus(
            device_id=fields.device,
            metric=fields.metric,
        )

    elif intent == "LIST_RULES":
        fields = extract_list_rules_fields(text)

        action = ListRules(
            device_id=fields.device,
        )

    else:
        fields = extract_unsupported_reason(text)

        action = Unsupported(
            reason=fields.reason,
        )

    # The backend validates the action before execution.
    validate_action(action)

    # Only validated actions reach the executor.
    result = execute_action(action)

    return {
        "action": action.model_dump(),
        "result": result,
    }