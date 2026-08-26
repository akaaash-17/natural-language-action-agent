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

    This preserves the original single-action behavior.
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

    This is used by the multi-action pipeline because the LLM has
    already produced a typed action.
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
                    "action": resolved_action.model_dump(),
                    "result": result,
                }
            )

        except ValueError as exc:
            results.append(
                {
                    "success": False,
                    "action": action.model_dump(),
                    "error": str(exc),
                }
            )

        except Exception as exc:
            results.append(
                {
                    "success": False,
                    "action": action.model_dump(),
                    "error": (
                        "Unexpected error while processing "
                        "this action."
                    ),
                    "detail": str(exc),
                }
            )

    overall_success = all(
        item["success"]
        for item in results
    )

    return {
        "success": overall_success,
        "action_count": len(results),
        "actions": results,
    }


def process_command(text: str) -> dict:
    """
    Convert a natural-language command into validated action(s)
    and execute them against the mock backend.

    Single-action requests use the existing deterministic pipeline.

    Multi-action requests are decomposed into an ActionPlan and
    each action independently passes through:

        resolver -> validator -> executor

    This ensures that one invalid action does not prevent other
    independent actions from being evaluated.
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

    return {
        "action": action.model_dump(),
        "result": result,
    }