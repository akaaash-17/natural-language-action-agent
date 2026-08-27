import json
import re

import httpx
from pydantic import BaseModel, ValidationError

from app.models import ActionPlan
from app.registry import DEVICE_REGISTRY


OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3.2"
OLLAMA_TIMEOUT = 120.0


class AlertFields(BaseModel):
    device: str
    metric: str
    condition: str
    threshold: float | None = None
    duration_minutes: float | None = None


class StatusFields(BaseModel):
    device: str
    metric: str | None = None


class ListRulesFields(BaseModel):
    device: str | None = None


class UnsupportedFields(BaseModel):
    reason: str


def _registry_description() -> str:
    """
    Create a text description of the valid devices and
    the metrics supported by each device.
    """

    lines = ["Valid devices and their supported metrics:"]

    for device_id, info in DEVICE_REGISTRY.items():
        metrics = ", ".join(info["metrics"])
        lines.append(f"- {device_id}: {metrics}")

    return "\n".join(lines)


def _call_ollama(prompt: str) -> dict:
    """
    Send a focused extraction request to the local Ollama model.

    Temperature is explicitly set to zero to make structured
    extraction more deterministic.
    """

    response = httpx.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0,
            },
        },
        timeout=OLLAMA_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    return json.loads(data["message"]["content"])


def _unsupported_plan() -> ActionPlan:
    """
    Return a safe fallback ActionPlan.
    """

    return ActionPlan(
        actions=[
            {
                "type": "UNSUPPORTED",
                "reason": (
                    "The request could not be converted into "
                    "a supported monitoring action."
                ),
            }
        ]
    )


def _find_assets_in_text(text: str) -> list[str]:
    """
    Return all known assets explicitly mentioned in the text.

    Assets are returned in the same order in which they appear.
    Duplicate mentions are removed.
    """

    normalized_text = text.lower()

    matches = []

    for asset_id in DEVICE_REGISTRY:
        if asset_id.lower() in normalized_text:
            matches.append(asset_id)

    matches.sort(
        key=lambda asset: normalized_text.find(asset.lower())
    )

    return list(dict.fromkeys(matches))


def _find_metrics_in_text(
    text: str,
    device: str | None = None,
) -> list[str]:
    """
    Return all known metrics explicitly mentioned in the text.

    If a device is supplied, only metrics belonging to that
    device are considered.
    """

    normalized_text = text.lower()

    metrics: set[str] = set()

    if device in DEVICE_REGISTRY:
        metrics.update(
            metric.lower()
            for metric in DEVICE_REGISTRY[device]["metrics"]
        )
    else:
        for info in DEVICE_REGISTRY.values():
            metrics.update(
                metric.lower()
                for metric in info["metrics"]
            )

    matches = [
        metric
        for metric in metrics
        if metric in normalized_text
    ]

    return sorted(
        matches,
        key=lambda metric: normalized_text.find(metric),
    )


def _recover_device_from_text(text: str) -> str | None:
    """
    Recover a device ID directly from the user's text when the
    LLM fails to extract one.

    This function is primarily useful for single-action requests.

    For multi-asset requests, extract_action_plan() uses the safer
    _find_assets_in_text() logic and will not guess between
    multiple assets.
    """

    normalized_text = text.lower()

    # Prefer exact known device IDs.
    for device_id in DEVICE_REGISTRY:
        if device_id.lower() in normalized_text:
            return device_id

    # Fall back to common natural-language constructions such as:
    # "pressure in reactor-core"
    # "temperature of warehouse-3"
    # "humidity for cold-storage-1"
    match = re.search(
        r"\b(?:in|of|for|from)\s+([a-zA-Z0-9][a-zA-Z0-9_-]*)",
        normalized_text,
    )

    if match:
        return match.group(1)

    return None


def _recover_metric_from_text(
    text: str,
    device: str | None = None,
) -> str | None:
    """
    Recover a metric directly from the user's text when the
    LLM fails to extract one.

    Known metrics from the registry are preferred.
    """

    metrics = _find_metrics_in_text(
        text=text,
        device=device,
    )

    if metrics:
        return metrics[0]

    return None


def _repair_action_plan(
    text: str,
    candidate: dict,
) -> dict:
    """
    Ask the LLM to reconstruct a malformed action plan.

    This is intentionally a second structured extraction pass
    rather than a hardcoded repair. The original user request is
    treated as the source of truth.
    """

    registry = _registry_description()

    prompt = f"""
You are repairing a malformed structured action plan.

Convert the user's request into a valid JSON ActionPlan.

{registry}

SUPPORTED ACTIONS

1. QUERY_STATUS

Required fields:
- type = "QUERY_STATUS"
- device_id
- metric

2. CREATE_ALERT_RULE

Required fields:
- type = "CREATE_ALERT_RULE"
- device_id
- metric
- condition
- threshold
- duration_minutes
- notify_via

condition MUST be exactly one of:
- "ABOVE"
- "BELOW"
- "EQUALS"

threshold MUST be a number.

duration_minutes MUST be a number.
If the user does not specify a duration, use 0.

notify_via MUST be a JSON array.
If the user does not specify notification delivery, use ["EMAIL"].

3. LIST_RULES

Required fields:
- type = "LIST_RULES"
- device_id

4. UNSUPPORTED

Required fields:
- type = "UNSUPPORTED"
- reason

CRITICAL RULES

- Return exactly one JSON object.
- The object must contain an "actions" array.
- Every independent user request becomes one action.
- Each action must have the correct action type.
- Never use fields from one action type on another action.
- Never use "N/A".
- Never use null as a replacement for a required field.
- Never invent a device.
- Never invent a metric.
- Do not resolve ambiguous parameters.
- Preserve broad concepts such as "temperature" exactly when appropriate.
- A QUERY_STATUS action must NEVER contain alert fields.
- A LIST_RULES action must NEVER contain metric, threshold,
  condition, duration_minutes, or notify_via.
- A CREATE_ALERT_RULE action must contain all required alert fields.
- Do not execute anything.
- Return JSON only.

The previous malformed candidate was:

{json.dumps(candidate, indent=2)}

Do NOT copy malformed values from that candidate.
Reconstruct the plan from the original user request.

USER REQUEST:

{text}

Return JSON only.
"""

    return _call_ollama(prompt)


def _validate_action_plan_result(result: dict) -> ActionPlan | None:
    """
    Validate an LLM-produced action plan.

    Returns the validated ActionPlan when valid.
    Returns None when the structure is invalid.
    """

    if not isinstance(result, dict):
        return None

    actions = result.get("actions")

    if not isinstance(actions, list) or not actions:
        return None

    try:
        return ActionPlan.model_validate(
            {
                "actions": actions,
            }
        )
    except ValidationError:
        return None


def _prepare_action_fallbacks(
    text: str,
    actions: list,
) -> list:
    """
    Apply deterministic fallback extraction to actions that are
    missing device or metric information.

    Fallbacks are deliberately conservative.

    With multiple assets, a missing device is not guessed.
    With a specific asset, a metric is recovered only when exactly
    one metric is explicitly identifiable for that asset.
    """

    mentioned_assets = _find_assets_in_text(text)

    for action in actions:

        if not isinstance(action, dict):
            continue

        action_type = action.get("type")

        if action_type not in {
            "QUERY_STATUS",
            "CREATE_ALERT_RULE",
            "LIST_RULES",
        }:
            continue

        # Recover device only when there is exactly one known
        # asset in the entire request.
        if not action.get("device_id"):
            if len(mentioned_assets) == 1:
                action["device_id"] = mentioned_assets[0]

        # Recover metric only for actions that require one.
        if action_type in {
            "QUERY_STATUS",
            "CREATE_ALERT_RULE",
        }:

            if not action.get("metric"):

                device_id = action.get("device_id")

                if device_id:
                    device_metrics = _find_metrics_in_text(
                        text=text,
                        device=device_id,
                    )

                    # Only recover when exactly one metric is
                    # identifiable for that specific asset.
                    if len(device_metrics) == 1:
                        action["metric"] = device_metrics[0]

    return actions


def extract_action_plan(text: str) -> ActionPlan:
    """
    Convert a natural-language request into one or more
    independent structured actions.

    The LLM performs decomposition and extraction.

    Deterministic fallback logic is used for missing device/metric
    fields.

    If the first LLM response is structurally malformed, a second
    repair pass is attempted before returning UNSUPPORTED.

    This function never executes actions.
    """

    registry = _registry_description()

    prompt = f"""
You convert a user's smart-facility monitoring request into JSON.

The user may request one or multiple independent actions.

{registry}

SUPPORTED ACTIONS

QUERY_STATUS

Fields:
- type
- device_id
- metric

CREATE_ALERT_RULE

Fields:
- type
- device_id
- metric
- condition
- threshold
- duration_minutes
- notify_via

LIST_RULES

Fields:
- type
- device_id

UNSUPPORTED

Fields:
- type
- reason

IMPORTANT

1. Return exactly one JSON object.
2. The JSON object MUST contain an "actions" array.
3. Put every independent user request into a separate action.
4. Every action must contain its own device_id when applicable.
5. Every action must contain its own metric when applicable.
6. Never mix the device or metric from one action with another action.
7. Do not invent devices or metrics.
8. Preserve broad metric concepts such as "temperature" exactly
   when the user uses them.
9. Do not resolve ambiguous parameters.
10. Do not validate devices or parameters.
11. Do not execute anything.
12. Do not add explanations outside JSON.
13. NEVER use "N/A".
14. NEVER use placeholder strings such as "unknown", "none",
    "not applicable", or "N/A" for structured fields.
15. Use only fields that belong to the selected action type.

ACTION MAPPING

- "what is", "what's", "show current", "check" a value
  → QUERY_STATUS

- "alert me", "notify me", "create an alert", "alert if"
  → CREATE_ALERT_RULE

- "show rules", "list rules", "alert rules", "existing rules"
  → LIST_RULES

- Anything outside these capabilities
  → UNSUPPORTED

CREATE_ALERT_RULE RULES

- "above" → ABOVE
- "below" → BELOW
- "equals" / "equal to" → EQUALS
- If no duration is specified, duration_minutes = 0.
- If no notification method is specified, notify_via = ["EMAIL"].
- threshold must always be a numeric value.
- condition must always be ABOVE, BELOW, or EQUALS.
- notify_via must always be a JSON array.

QUERY_STATUS RULES

- Only include:
  type
  device_id
  metric

LIST_RULES RULES

- Only include:
  type
  device_id

EXAMPLE 1

User:
"what is the temperature in warehouse-3 and the hydraulic
pressure in tipper-101"

Return:

{{
  "actions": [
    {{
      "type": "QUERY_STATUS",
      "device_id": "warehouse-3",
      "metric": "temperature"
    }},
    {{
      "type": "QUERY_STATUS",
      "device_id": "tipper-101",
      "metric": "hydraulic_pressure"
    }}
  ]
}}

EXAMPLE 2

User:
"alert me if warehouse-3 temperature goes above 400 and
what is the hydraulic temperature of tipper-101"

Return:

{{
  "actions": [
    {{
      "type": "CREATE_ALERT_RULE",
      "device_id": "warehouse-3",
      "metric": "temperature",
      "condition": "ABOVE",
      "threshold": 400,
      "duration_minutes": 0,
      "notify_via": ["EMAIL"]
    }},
    {{
      "type": "QUERY_STATUS",
      "device_id": "tipper-101",
      "metric": "hydraulic_temperature"
    }}
  ]
}}

EXAMPLE 3

User:
"alert me if warehouse-3 temperature goes above 400,
what is the hydraulic pressure of tipper-101, and show me
the alert rules for cold-storage-1"

Return:

{{
  "actions": [
    {{
      "type": "CREATE_ALERT_RULE",
      "device_id": "warehouse-3",
      "metric": "temperature",
      "condition": "ABOVE",
      "threshold": 400,
      "duration_minutes": 0,
      "notify_via": ["EMAIL"]
    }},
    {{
      "type": "QUERY_STATUS",
      "device_id": "tipper-101",
      "metric": "hydraulic_pressure"
    }},
    {{
      "type": "LIST_RULES",
      "device_id": "cold-storage-1"
    }}
  ]
}}

USER REQUEST:

{text}

Return JSON only.
"""

    result = _call_ollama(prompt)

    # ---------------------------------------------------------
    # FIRST VALIDATION
    # ---------------------------------------------------------

    plan = _validate_action_plan_result(result)

    if plan is not None:

        actions = plan.actions

        # Convert the validated model back into dictionaries so
        # deterministic fallback extraction can operate safely.
        action_dicts = [
            action.model_dump()
            for action in actions
        ]

        action_dicts = _prepare_action_fallbacks(
            text=text,
            actions=action_dicts,
        )

        try:
            return ActionPlan.model_validate(
                {
                    "actions": action_dicts,
                }
            )
        except ValidationError:
            pass

    # ---------------------------------------------------------
    # REPAIR PASS
    # ---------------------------------------------------------

    try:
        repaired_result = _repair_action_plan(
            text=text,
            candidate=result,
        )

        repaired_plan = _validate_action_plan_result(
            repaired_result
        )

        if repaired_plan is not None:

            repaired_actions = [
                action.model_dump()
                for action in repaired_plan.actions
            ]

            repaired_actions = _prepare_action_fallbacks(
                text=text,
                actions=repaired_actions,
            )

            try:
                return ActionPlan.model_validate(
                    {
                        "actions": repaired_actions,
                    }
                )
            except ValidationError:
                pass

    except Exception:
        # The repair pass is intentionally best-effort.
        # A parser failure must not expose an internal exception
        # to the rest of the application.
        pass

    # ---------------------------------------------------------
    # SAFE FINAL FALLBACK
    # ---------------------------------------------------------

    return _unsupported_plan()


def extract_alert_fields(text: str) -> AlertFields:
    """
    Extract alert-rule parameters from a natural-language request.

    Numeric threshold-based alerts return threshold and duration.

    Event/state-based requests such as camera offline may return
    null for threshold and duration and are handled by the service
    as unsupported capabilities.
    """

    registry = _registry_description()

    prompt = f"""
You extract alert-rule parameters from smart-facility monitoring
requests.

{registry}

Extract:

- device
- metric
- condition
- threshold
- duration_minutes

Rules:

- Extract the exact device ID mentioned by the user.
- Do not replace a device ID with a metric name or sensor type.
- Do not invent a device name.
- The device does NOT need to be present in the registry.
- Device validation is handled separately after extraction.
- ABOVE means the value stays above the threshold.
- BELOW means the value stays below the threshold.
- EQUALS means the value equals the threshold.
- "for more than 10 minutes" means duration_minutes = 10.
- For event/state conditions such as "camera goes offline",
  use the appropriate condition such as "OFFLINE".
- For event/state conditions that do not have a numeric threshold,
  set threshold to null.
- If no duration is specified, set duration_minutes to null.
- Return JSON only.
- Do not add explanations.

Example 1:

User:
"Alert me if warehouse-3 temperature stays above 40 degrees
for more than 10 minutes."

Output:

{{
    "device": "warehouse-3",
    "metric": "temperature",
    "condition": "ABOVE",
    "threshold": 40,
    "duration_minutes": 10
}}

Example 2:

User:
"Notify security if the front-gate camera goes offline."

Output:

{{
    "device": "front-gate",
    "metric": "camera_status",
    "condition": "OFFLINE",
    "threshold": null,
    "duration_minutes": null
}}

User request:

{text}
"""

    result = _call_ollama(prompt)

    if not result.get("device"):
        recovered_device = _recover_device_from_text(text)

        if recovered_device:
            result["device"] = recovered_device

    if not result.get("metric"):
        recovered_metric = _recover_metric_from_text(
            text,
            result.get("device"),
        )

        if recovered_metric:
            result["metric"] = recovered_metric

    return AlertFields.model_validate(result)


def extract_status_fields(text: str) -> StatusFields:
    """
    Extract device and metric from a status-query request.

    The LLM performs the primary extraction. If it returns null
    for a device or metric, deterministic extraction from the
    original text is used as a fallback.

    Unknown devices are intentionally preserved so that the
    validator can return a clean registry validation error.
    """

    registry = _registry_description()

    prompt = f"""
You extract device and metric information from smart-facility
monitoring requests.

{registry}

Important rules:

- Extract the exact device ID mentioned by the user.
- Do not use a metric name or sensor type as the device.
- Do not invent a device name.
- The device does NOT need to be present in the registry.
- If the user mentions an unknown device, still extract that exact
  device ID. Device validation happens separately.
- Extract the metric requested by the user.
- If no metric is specified, use null.
- Return JSON only.
- Do not add explanations.

Example 1:

User:
"what is the humidity in cold-storage-1 right now?"

Output:

{{
    "device": "cold-storage-1",
    "metric": "humidity"
}}

Example 2:

User:
"what is the pressure in reactor-core right now?"

Output:

{{
    "device": "reactor-core",
    "metric": "pressure"
}}

User request:

{text}
"""

    result = _call_ollama(prompt)

    if not result.get("device"):
        recovered_device = _recover_device_from_text(text)

        if recovered_device:
            result["device"] = recovered_device

    if not result.get("metric"):
        recovered_metric = _recover_metric_from_text(
            text,
            result.get("device"),
        )

        if recovered_metric:
            result["metric"] = recovered_metric

    return StatusFields.model_validate(result)


def extract_list_rules_fields(text: str) -> ListRulesFields:
    """
    Extract an optional device from a list-rules request.
    """

    registry = _registry_description()

    prompt = f"""
Determine whether the user is asking for monitoring or alert rules.

{registry}

Extract the device if one is mentioned.

Rules:

- Extract the exact device ID mentioned by the user.
- Do not invent a device name.
- The device does NOT need to be present in the registry.
- If no device is mentioned, use null.
- Return JSON only.
- Do not add explanations.

Output:

{{
    "device": "device-id-or-null"
}}

User request:

{text}
"""

    result = _call_ollama(prompt)

    if not result.get("device"):
        recovered_device = _recover_device_from_text(text)

        if recovered_device:
            result["device"] = recovered_device

    return ListRulesFields.model_validate(result)


def extract_unsupported_reason(text: str) -> UnsupportedFields:
    """
    Generate a short reason explaining why a request is unsupported.
    """

    prompt = f"""
Explain briefly why the following request is outside the supported
smart-facility monitoring system.

The system supports:

- Creating monitoring alert rules
- Querying device status
- Listing existing monitoring rules

It does NOT directly control physical devices or equipment.

Return JSON with:

- reason

Return JSON only.
Do not add explanations outside the JSON.

User request:

{text}
"""

    result = _call_ollama(prompt)

    return UnsupportedFields.model_validate(result)