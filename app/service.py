from app.executor import execute_action
from app.llm_parser import (
    extract_action_plan,
    extract_alert_fields,
    extract_list_rules_fields,
    extract_status_fields,
    extract_unsupported_reason,
)
from app.models import (
    ActionPlan,
    CreateAlertRule,
    ListRules,
    QueryStatus,
    Unsupported,
)
from app.resolver import find_parameters_by_concept, resolve_parameter
from app.router import route_intent
from app.validator import validate_action


def _resolve_metric(
    device_id: str,
    metric: str | None,
) -> str:
    """
    Resolve an LLM-extracted metric against the asset registry.

    The resolver distinguishes between:
    - EXACT: one parameter matches
    - AMBIGUOUS: multiple parameters match
    - UNKNOWN: no parameter matches

    A ValueError is raised for ambiguous or unknown parameters.
    """

    if metric is None:
        raise ValueError(
            f"No metric or parameter was identified for device "
            f"'{device_id}'."
        )

    # First try an exact registered parameter.
    resolution = resolve_parameter(
        asset_id=device_id,
        parameter=metric,
    )

    if resolution.status == "EXACT":
        return resolution.matches[0]["parameter"]

    # If the LLM extracted a broad concept such as "temperature",
    # search for all parameters belonging to that concept.
    concept_resolution = find_parameters_by_concept(
        asset_id=device_id,
        concept=metric,
    )

    if concept_resolution.status == "EXACT":
        return concept_resolution.matches[0]["parameter"]

    if concept_resolution.status == "AMBIGUOUS":
        options = ", ".join(
            match["parameter"]
            for match in concept_resolution.matches
        )

        raise ValueError(
            f"Multiple parameters match '{metric}' on "
            f"'{device_id}': {options}. "
            "Please specify which parameter you want."
        )

    raise ValueError(
        f"Parameter '{metric}' is not registered for "
        f"device '{device_id}'."
    )


def _build_action_from_single_intent(
    text: str,
    intent: str,
):
    """
    Build one action from the existing single-intent extraction
    pipeline.
    """

    if intent == "CREATE_ALERT_RULE":
        fields = extract_alert_fields(text)

        # Event/state-based alerts such as camera OFFLINE remain
        # intentionally unsupported because the current action
        # model requires a numeric threshold.
        if (
            fields.metric == "camera_status"
            or fields.threshold is None
        ):
            return Unsupported(
                reason=(
                    "Event-based alert conditions such as camera "
                    "offline are not currently supported. "
                    "Alert rules require a numeric threshold."
                )
            )

        resolved_metric = _resolve_metric(
            device_id=fields.device,
            metric=fields.metric,
        )

        return CreateAlertRule(
            device_id=fields.device,
            metric=resolved_metric,
            condition=fields.condition.upper(),
            threshold=fields.threshold,
            duration_minutes=(
                fields.duration_minutes
                if fields.duration_minutes is not None
                else 0
            ),
            notify_via=["EMAIL"],
        )

    if intent == "QUERY_STATUS":
        fields = extract_status_fields(text)

        resolved_metric = _resolve_metric(
            device_id=fields.device,
            metric=fields.metric,
        )

        return QueryStatus(
            device_id=fields.device,
            metric=resolved_metric,
        )

    if intent == "LIST_RULES":
        fields = extract_list_rules_fields(text)

        return ListRules(
            device_id=fields.device,
        )

    fields = extract_unsupported_reason(text)

    return Unsupported(
        reason=fields.reason,
    )


def _resolve_action(action):
    """
    Resolve an already parsed action against the asset/parameter
    registry.

    Used by the multi-action pipeline.
    """

    if isinstance(action, CreateAlertRule):
        resolved_metric = _resolve_metric(
            device_id=action.device_id,
            metric=action.metric,
        )

        return action.model_copy(
            update={
                "metric": resolved_metric,
            }
        )

    if isinstance(action, QueryStatus):
        resolved_metric = _resolve_metric(
            device_id=action.device_id,
            metric=action.metric,
        )

        return action.model_copy(
            update={
                "metric": resolved_metric,
            }
        )

    # LIST_RULES and UNSUPPORTED do not contain a metric that
    # requires parameter resolution.
    return action


def _format_single_result(
    action,
    result: dict,
) -> dict:
    """
    Convert an internal action/executor result into a clean,
    user-facing response.

    Internal action types are intentionally hidden from the
    API response.
    """

    if isinstance(action, CreateAlertRule):
        current_value = None

        # Retrieve the current sensor value so the user gets
        # immediate context after creating the alert.
        try:
            current_status = execute_action(
                QueryStatus(
                    device_id=action.device_id,
                    metric=action.metric,
                )
            )

            current_value = current_status.get("value")

        except Exception:
            # Alert creation itself succeeded, so failure to
            # retrieve current status should not invalidate it.
            current_value = None

        response = {
            "success": True,
            "message": "Alert rule created successfully.",
            "device_id": action.device_id,
            "metric": action.metric,
            "condition": action.condition,
            "threshold": action.threshold,
            "duration_minutes": action.duration_minutes,
            "current_value": current_value,
        }

        return response

    if isinstance(action, QueryStatus):
        return {
            "success": True,
            "message": "Current value retrieved successfully.",
            "device_id": action.device_id,
            "metric": action.metric,
            "current_value": result.get("value"),
        }

    if isinstance(action, ListRules):
        return {
            "success": True,
            "message": "Alert rules retrieved successfully.",
            "device_id": action.device_id,
            "count": result.get("count", 0),
            "rules": result.get("rules", []),
        }

    if isinstance(action, Unsupported):
        return {
            "success": False,
            "message": result.get(
                "reason",
                action.reason,
            ),
        }

    return {
        "success": False,
        "message": "Unable to format the action result.",
    }


def _format_multi_result(results: list) -> dict:
    """
    Convert internal multi-action results into a clean,
    user-facing response.
    """

    formatted_results = []

    for item in results:
        action = item.get("_action")

        if item["success"]:
            formatted = _format_single_result(
                action=action,
                result=item["result"],
            )

        else:
            formatted = {
                "success": False,
                "message": item["error"],
            }

            # Include asset context when available.
            if hasattr(action, "device_id"):
                formatted["device_id"] = action.device_id

            if hasattr(action, "metric"):
                formatted["metric"] = action.metric

        formatted_results.append(formatted)

    return {
        "success": all(
            item["success"]
            for item in formatted_results
        ),
        "results": formatted_results,
    }


def _process_multi_action(text: str) -> dict:
    """
    Parse, resolve, validate, and execute every action contained
    in a multi-action request.

    Each action is processed independently so one invalid action
    does not prevent other valid actions from being evaluated.
    """

    plan: ActionPlan = extract_action_plan(text)

    results = []

    for action in plan.actions:
        try:
            # Resolve asset/parameter references before validation.
            resolved_action = _resolve_action(action)

            # Every action must independently pass backend validation.
            validate_action(resolved_action)

            # Only validated actions reach the executor.
            result = execute_action(resolved_action)

            results.append(
                {
                    "success": True,
                    "_action": resolved_action,
                    "result": result,
                }
            )

        except ValueError as exc:
            results.append(
                {
                    "success": False,
                    "_action": action,
                    "error": str(exc),
                }
            )

        except Exception:
            results.append(
                {
                    "success": False,
                    "_action": action,
                    "error": (
                        "Unexpected error while processing "
                        "this action."
                    ),
                }
            )

    return _format_multi_result(results)


def process_command(text: str) -> dict:
    """
    Convert a natural-language command into validated action(s),
    execute them, and return a clean user-facing response.

    Internal action representations are intentionally kept out
    of the API response.
    """

    intent = route_intent(text)

    # Multi-action requests use the ActionPlan pipeline.
    if intent == "MULTI_ACTION":
        return _process_multi_action(text)

    # Existing single-action pipeline.
    action = _build_action_from_single_intent(
        text=text,
        intent=intent,
    )

    # The backend validates the action before execution.
    validate_action(action)

    # Only validated actions reach the executor.
    result = execute_action(action)

    return _format_single_result(
        action=action,
        result=result,
    )