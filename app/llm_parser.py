import json

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
- The device MUST be one of the valid devices listed above.
- Never invent a device name.
- Do not use a metric name or sensor type as the device.
- Extract the exact device ID mentioned by the user.
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

    return AlertFields.model_validate(result)


def extract_status_fields(text: str) -> StatusFields:
    """
    Extract device and metric from a status-query request.
    """

    registry = _registry_description()

    prompt = f"""
You extract device and metric information from smart-facility
monitoring requests.

{registry}

Important rules:
- The device MUST be one of the valid devices listed above.
- Never invent a device name.
- Do not use a metric name or sensor type as the device.
- Extract the exact device ID mentioned by the user.
- Extract the metric requested by the user.
- If no metric is specified, use null.
- Return JSON only.
- Do not add explanations.

Example:
User: "what is the humidity in cold-storage-1 right now?"

Output:
{{
    "device": "cold-storage-1",
    "metric": "humidity"
}}

User request:
{text}
"""

    result = _call_ollama(prompt)

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
- The device MUST be one of the valid devices listed above.
- Never invent a device name.
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