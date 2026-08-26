import json
import re

import httpx
from pydantic import BaseModel

from app.models import ActionPlan
from app.registry import DEVICE_REGISTRY


OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3.2"


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
        },
        timeout=120.0,
    )

    response.raise_for_status()

    data = response.json()

    return json.loads(data["message"]["content"])


def _recover_device_from_text(text: str) -> str | None:
    """
    Recover a device ID directly from the user's text when the
    LLM fails to extract one.

    Known registry devices are preferred. If the device is unknown,
    a simple natural-language pattern is used so that the validator
    can later produce the correct 'device does not exist' error.
    """

    normalized_text = text.lower()

    # First prefer exact known device IDs.
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
    Recover a metric directly from the user's text when the LLM
    fails to extract one.

    Known metrics from the registry are preferred.
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

    # Prefer longer metric names first in case one metric name
    # contains another metric name.
    for metric in sorted(metrics, key=len, reverse=True):
        if metric in normalized_text:
            return metric

    return None


def extract_action_plan(text: str) -> ActionPlan:
    """
    Decompose a natural-language request into one or more
    structured actions.

    The LLM performs action decomposition only. The resulting
    actions are still treated as untrusted input and must pass
    deterministic resolution and validation before execution.
    """

    registry = _registry_description()

    prompt = f"""
You are an action-planning parser for a smart-facility monitoring
system.

Your task is to convert ONE natural-language user request into
ONE OR MORE structured actions.

{registry}

SUPPORTED ACTION TYPES:

1. QUERY_STATUS

Required fields:
- type = "QUERY_STATUS"
- device_id
- metric

Example:
"what is the temperature in warehouse-3?"

Output:
{{
    "type": "QUERY_STATUS",
    "device_id": "warehouse-3",
    "metric": "temperature"
}}

2. CREATE_ALERT_RULE

Required fields:
- type = "CREATE_ALERT_RULE"
- device_id
- metric
- condition
- threshold
- duration_minutes
- notify_via

Allowed conditions:
- ABOVE
- BELOW
- EQUALS

Allowed notification methods:
- EMAIL
- SMS
- PUSH

Example:
"alert me if warehouse-3 temperature goes above 40"

Output:
{{
    "type": "CREATE_ALERT_RULE",
    "device_id": "warehouse-3",
    "metric": "temperature",
    "condition": "ABOVE",
    "threshold": 40,
    "duration_minutes": 0,
    "notify_via": ["EMAIL"]
}}

3. LIST_RULES

Required fields:
- type = "LIST_RULES"
- device_id

Example:
"show me the alert rules for warehouse-3"

Output:
{{
    "type": "LIST_RULES",
    "device_id": "warehouse-3"
}}

4. UNSUPPORTED

Required fields:
- type = "UNSUPPORTED"
- reason

Use this when the request does not represent a supported
monitoring operation.

CRITICAL EXTRACTION RULES:

- Return an "actions" array.
- Every explicitly requested independent operation must become
  a separate action.
- A single user request may contain multiple actions.
- Do not combine independent status queries into one action.
- Do not combine independent alert rules into one action.

ONLY EXTRACT EXPLICITLY REQUESTED ACTIONS:

- Only create an action when the user explicitly requests it.
- Do NOT infer an additional metric from context.
- Do NOT infer an additional sensor from context.
- Do NOT infer an additional status query.
- Do NOT infer an additional alert rule.
- Do NOT infer that "its" refers to another metric.
- Do NOT create actions for information that the user did not ask for.
- If the user asks for temperature only, create only a temperature
  action.
- If the user explicitly asks for temperature AND humidity, create
  both actions.
- If the user asks for temperature AND alert rules, create exactly
  those two actions.
- Do not assume that an asset having multiple metrics means that
  all metrics should be queried.

DEVICE AND METRIC RULES:

- Preserve the exact device ID mentioned by the user.
- Do not invent device IDs.
- Preserve the metric or parameter concept explicitly expressed
  by the user.
- Do not invent a metric.
- Device and metric validation happens separately after extraction.

ACTION SEMANTICS:

- QUERY_STATUS means the user explicitly asks for the current
  value or status of a metric.
- LIST_RULES means the user explicitly asks to see, list, or show
  monitoring or alert rules.
- CREATE_ALERT_RULE means the user explicitly asks to create,
  configure, or receive an alert when a condition occurs.
- UNSUPPORTED means the request does not represent a supported
  monitoring operation.

IMPORTANT:

- Do not execute anything.
- Do not validate whether a device exists.
- Do not validate whether a metric exists.
- Do not choose between ambiguous parameters.
- Do not add explanations outside the JSON.
- Return JSON only.

MULTI-ACTION EXAMPLE 1:

User:
"What is the temperature and humidity in warehouse-3?"

Output:
{{
    "actions": [
        {{
            "type": "QUERY_STATUS",
            "device_id": "warehouse-3",
            "metric": "temperature"
        }},
        {{
            "type": "QUERY_STATUS",
            "device_id": "warehouse-3",
            "metric": "humidity"
        }}
    ]
}}

MULTI-ACTION EXAMPLE 2:

User:
"Check the temperature of warehouse-3 and show me its alert rules."

Output:
{{
    "actions": [
        {{
            "type": "QUERY_STATUS",
            "device_id": "warehouse-3",
            "metric": "temperature"
        }},
        {{
            "type": "LIST_RULES",
            "device_id": "warehouse-3"
        }}
    ]
}}

IMPORTANT:
Do NOT create a humidity QUERY_STATUS action because humidity
was not explicitly requested.

MULTI-ACTION EXAMPLE 3:

User:
"Create a temperature alert for warehouse-3 above 40 and
a humidity alert for warehouse-3 below 30."

Output:
{{
    "actions": [
        {{
            "type": "CREATE_ALERT_RULE",
            "device_id": "warehouse-3",
            "metric": "temperature",
            "condition": "ABOVE",
            "threshold": 40,
            "duration_minutes": 0,
            "notify_via": ["EMAIL"]
        }},
        {{
            "type": "CREATE_ALERT_RULE",
            "device_id": "warehouse-3",
            "metric": "humidity",
            "condition": "BELOW",
            "threshold": 30,
            "duration_minutes": 0,
            "notify_via": ["EMAIL"]
        }}
    ]
}}

If the request contains only one supported operation, return
one action in the actions array.

User request:
{text}
"""

    result = _call_ollama(prompt)

    # Protect against an unexpected null/missing actions field.
    if not result.get("actions"):
        result["actions"] = [
            {
                "type": "UNSUPPORTED",
                "reason": (
                    "The request could not be converted into a "
                    "supported monitoring action."
                ),
            }
        ]

    # Recover missing device IDs and metrics for individual actions.
    #
    # These deterministic fallbacks are only used when the LLM
    # fails to extract a value. They do not override a value that
    # the LLM has already extracted.
    for action in result["actions"]:
        if not isinstance(action, dict):
            continue

        action_type = action.get("type")

        if action_type in {
            "QUERY_STATUS",
            "CREATE_ALERT_RULE",
            "LIST_RULES",
        }:
            if not action.get("device_id"):
                recovered_device = _recover_device_from_text(text)

                if recovered_device:
                    action["device_id"] = recovered_device

            if action_type in {
                "QUERY_STATUS",
                "CREATE_ALERT_RULE",
            }:
                if not action.get("metric"):
                    recovered_metric = _recover_metric_from_text(
                        text,
                        action.get("device_id"),
                    )

                    if recovered_metric:
                        action["metric"] = recovered_metric

    return ActionPlan.model_validate(result)


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
You extract alert-rule parameters from smart-facility monitoring requests.

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
User: "Alert me if warehouse-3 temperature stays above 40 degrees
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
User: "Notify security if the front-gate camera goes offline."

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

    # If the LLM fails to identify the device, recover it from
    # the original user text before Pydantic validation.
    if not result.get("device"):
        recovered_device = _recover_device_from_text(text)

        if recovered_device:
            result["device"] = recovered_device

    # Recover the metric if the LLM omitted it.
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
User: "what is the humidity in cold-storage-1 right now?"

Output:
{{
    "device": "cold-storage-1",
    "metric": "humidity"
}}

Example 2:
User: "what is the pressure in reactor-core right now?"

Output:
{{
    "device": "reactor-core",
    "metric": "pressure"
}}

User request:
{text}
"""

    result = _call_ollama(prompt)

    # Primary fallback: recover the device directly from the
    # original user request.
    if not result.get("device"):
        recovered_device = _recover_device_from_text(text)

        if recovered_device:
            result["device"] = recovered_device

    # Secondary fallback: recover the metric directly from the
    # original user request.
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