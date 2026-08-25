import json
import re

import httpx
from pydantic import BaseModel

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


def _recover_metric_from_text(text: str, device: str | None = None) -> str | None:
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