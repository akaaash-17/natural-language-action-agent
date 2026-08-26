# Natural Language Action Agent

A local LLM-powered backend that converts natural-language smart-facility requests into **typed, validated, executable actions**.

> **Core principle:** Use the LLM for language understanding, but keep validation, business rules, safety, and execution deterministic.

The system accepts requests such as:

> "Create a temperature alert for warehouse-3 above 40 and a humidity alert for warehouse-3 below 30."

It can decompose that request into multiple typed actions, resolve asset-specific parameters, validate each action independently, and execute only valid actions against deterministic mock data.

---

## 1. What problem does this solve?

Smart-facility systems normally expose structured operations such as:

- Create an alert rule
- Query the current status of a device
- List existing alert rules

Those operations are easy for software to represent but less convenient for humans to express.

Instead of requiring JSON like:

```json
{
  "type": "CREATE_ALERT_RULE",
  "device_id": "warehouse-3",
  "metric": "temperature",
  "condition": "ABOVE",
  "threshold": 40,
  "duration_minutes": 10,
  "notify_via": ["EMAIL"]
}
```

the user can simply write:

> "Alert me if warehouse-3 temperature stays above 40 degrees for more than 10 minutes."

The application translates the natural-language request into structured actions and then validates those actions before execution.

---

## 2. What the system supports

### Supported actions

| Action | Example | Behavior |
|---|---|---|
| `CREATE_ALERT_RULE` | "Alert me if warehouse-3 temperature goes above 40" | Creates an in-memory alert rule |
| `QUERY_STATUS` | "What's the temperature in warehouse-3?" | Reads deterministic mock sensor data |
| `LIST_RULES` | "Show existing alert rules" | Returns stored rules |
| `UNSUPPORTED` | "Turn off the cooling system" | Safely rejects the request |

### Multi-action requests

The system also supports multiple operations in a single natural-language request.

For example:

```text
What is the temperature and humidity in warehouse-3?
```

becomes:

```text
QUERY_STATUS → temperature
QUERY_STATUS → humidity
```

Another example:

```text
Check the temperature of warehouse-3 and show me its alert rules.
```

becomes:

```text
QUERY_STATUS → temperature
LIST_RULES → warehouse-3
```

A mixed alert request can also be decomposed:

```text
Create a temperature alert for warehouse-3 above 40
and a humidity alert for warehouse-3 below 30.
```

becomes two independent `CREATE_ALERT_RULE` actions.

Each action is resolved, validated, and executed independently. Therefore, one invalid action does not prevent other actions from being evaluated.

---

## 3. Asset → Sensor → Parameter resolution

One of the important extensions in the project is support for assets that contain multiple sensors and parameters.

For example:

```text
tipper-101
├── hydraulic sensor
│   ├── hydraulic_temperature
│   └── hydraulic_pressure
│
└── engine sensor
    ├── engine_temperature
    └── oil_temperature
```

The user does not always provide the exact backend parameter name.

### Exact parameter

```text
What is the hydraulic temperature in tipper-101 right now?
```

resolves to:

```text
hydraulic_temperature
```

### Ambiguous concept

```text
What is the temperature in tipper-101 right now?
```

can match:

```text
hydraulic_temperature
engine_temperature
oil_temperature
```

The system therefore rejects the request as ambiguous and asks the user to specify the parameter instead of guessing.

### Unknown parameter

```text
What is the battery voltage in tipper-101?
```

returns a clean validation error because `battery_voltage` is not registered for that asset.

This resolution layer is deterministic and sits between LLM extraction and execution.

---

## 4. Current mock registry

The original facility registry contains:

```text
warehouse-3        → temperature, humidity
cold-storage-1    → temperature, humidity
front-gate        → camera_status, occupancy
server-room-1     → temperature, humidity
production-floor-1 → temperature, humidity, occupancy
loading-bay-1     → temperature, occupancy
```

The asset/parameter resolver additionally demonstrates the more realistic multi-sensor structure using `tipper-101`.

The registry is intentionally small and deterministic because this is an assessment project rather than a real IoT integration.

---

## 5. Architecture

```text
                         User
                          |
                          v
                  +----------------+
                  |    FastAPI     |
                  | /command       |
                  | /rules         |
                  +-------+--------+
                          |
                          v
                  +----------------+
                  | Intent Router  |
                  | deterministic  |
                  +-------+--------+
                          |
                +---------+---------+
                |                   |
         Single Intent        MULTI_ACTION
                |                   |
                +---------+---------+
                          |
                          v
                  +----------------+
                  | Ollama         |
                  | Llama 3.2      |
                  | JSON extraction|
                  +-------+--------+
                          |
                          v
                  +----------------+
                  | Typed Pydantic |
                  | Action / Plan  |
                  +-------+--------+
                          |
                          v
                  +----------------+
                  | Parameter      |
                  | Resolver       |
                  +-------+--------+
                          |
                          v
                  +----------------+
                  | Validator      |
                  | Registry checks|
                  +-------+--------+
                          |
                    +-----+-----+
                    |           |
                  Valid       Invalid
                    |           |
                    v           v
                Executor    Safe error
                    |
                    v
          +----------------------+
          | Mock sensor data /   |
          | in-memory rule store |
          +----------------------+
```

### Request lifecycle

For a supported request:

```text
Natural language
      ↓
Deterministic intent routing
      ↓
LLM action/field extraction
      ↓
Pydantic typed models
      ↓
Asset/parameter resolution
      ↓
Registry + business validation
      ↓
Execution
      ↓
Structured JSON response
```

For an invalid request:

```text
Natural language
      ↓
Intent routing / LLM extraction
      ↓
Parameter or action resolution
      ↓
Validation failure
      ↓
Clear error / safe rejection
```

---

## 6. Why is this a hybrid design?

This is intentionally **not an end-to-end LLM agent**.

Different responsibilities are handled by different components.

### Deterministic code handles

- High-level intent routing
- Action types
- Pydantic schema validation
- Asset/device validation
- Sensor/parameter compatibility
- Ambiguity detection
- Unsupported operations
- Execution
- Storage
- HTTP error handling

### The LLM handles

- Understanding natural language
- Extracting asset/device IDs
- Extracting metrics or parameter concepts
- Interpreting conditions such as "above", "below", and "exceeds"
- Extracting numeric thresholds
- Extracting durations
- Decomposing multi-action requests

The LLM therefore acts as a **translator**, not the source of truth.

---

## 7. Why Ollama?

Ollama was selected because the assignment supports local LLM inference and this task does not require a cloud model.

### Advantages

**Local inference**

No external API key or cloud dependency is required.

**Privacy**

Facility-related commands can remain on the local machine instead of being sent to a third-party inference provider.

**Reproducibility**

An evaluator can reproduce the architecture with Ollama and the selected model without requiring cloud credentials or billing.

**Simple integration**

Ollama exposes a local HTTP API. The application sends a constrained prompt and requests JSON output.

**Good fit for the task**

The model is mainly performing structured extraction rather than complex reasoning, so local inference is a practical trade-off.

---

## 8. Why Llama 3.2?

The project uses:

```text
llama3.2
```

through Ollama.

The task mainly requires:

- Device/asset extraction
- Metric/parameter extraction
- Condition extraction
- Threshold extraction
- Duration extraction
- Multi-action decomposition
- JSON output

A large frontier model is unnecessary for this scope.

Llama 3.2 provides a practical balance between local resource requirements and extraction capability.

The model can also be replaced later without changing the validation or execution layers.

---

## 9. Why deterministic intent routing?

The intent router is deliberately lightweight and does not call the LLM.

The current high-level routes are:

```text
CREATE_ALERT_RULE
QUERY_STATUS
LIST_RULES
MULTI_ACTION
UNSUPPORTED
```

For example:

```text
"What is the battery voltage in tipper-101?"
```

→ `QUERY_STATUS`

while:

```text
"What is the temperature in warehouse-3 and
the battery voltage in tipper-101?"
```

→ `MULTI_ACTION`

This saves an unnecessary LLM call for high-level classification and makes the safety boundaries predictable.

The LLM is used after routing, where language understanding provides the most value: extracting the structured details.

---

## 10. Multi-action processing

For a multi-action request, the flow is:

```text
User request
     ↓
MULTI_ACTION router
     ↓
ActionPlan extraction
     ↓
Individual typed actions
     ↓
Resolve each action
     ↓
Validate each action
     ↓
Execute valid actions
     ↓
Return per-action results
```

Example:

```text
What is the temperature and battery voltage in tipper-101?
```

can produce:

```text
Action 1:
QUERY_STATUS
temperature
→ AMBIGUOUS

Action 2:
QUERY_STATUS
battery_voltage
→ UNKNOWN
```

The response reports both failures independently rather than crashing the entire request.

This is important because multi-action requests should have **partial failure isolation**.

---

## 11. Validation and safety

Validation happens after LLM extraction.

### Device validation

An unknown asset/device is rejected.

Example:

```text
Alert me if reactor-core pressure exceeds 9000.
```

results in a validation error because `reactor-core` is not registered.

### Parameter validation

A parameter must belong to the requested asset.

For example:

```text
warehouse-3 → temperature ✓
warehouse-3 → humidity ✓
warehouse-3 → pressure ✗
```

### Ambiguity validation

If a broad concept maps to multiple parameters, the system refuses to guess.

Example:

```text
temperature
```

on `tipper-101` maps to:

```text
hydraulic_temperature
engine_temperature
oil_temperature
```

Therefore:

```text
Multiple parameters match 'temperature'...
Please specify which parameter you want.
```

### Physical control

The current system does not directly control physical equipment.

Requests such as:

```text
Turn off the cooling system in warehouse-3.
```

are rejected as:

```text
UNSUPPORTED
```

No physical action is attempted.

---

## 12. Camera-offline handling

A required edge case is:

> "Notify security if the front-gate camera goes offline."

This differs from the current numeric threshold model.

Supported numeric conditions are:

```text
ABOVE
BELOW
EQUALS
```

A camera going offline is an event/state condition rather than a numeric threshold.

The LLM can understand the request, but the service intentionally does not execute it.

Instead it returns:

```text
UNSUPPORTED
```

with a reason explaining that the current alert implementation requires a numeric threshold.

This is a deliberate safety decision: **reject unsupported semantics instead of inventing backend behavior.**

---

## 13. Mock execution model

The project intentionally uses:

- Deterministic mock sensor values
- An in-memory alert-rule store
- No external database
- No physical hardware

Example status response:

```json
{
  "success": true,
  "device_id": "warehouse-3",
  "metric": "temperature",
  "value": 36.5
}
```

Creating an alert stores the validated rule in memory.

The rules can then be retrieved through:

```text
GET /rules
```

The store lasts only for the lifetime of the application process.

---

## 14. API

### `GET /`

Health check.

Example:

```json
{
  "success": true,
  "message": "Natural Language Action Agent is running."
}
```

### `POST /command`

Request:

```json
{
  "text": "Alert me if warehouse-3 temperature stays above 40 degrees for more than 10 minutes."
}
```

### `GET /rules`

Returns stored alert rules.

Optional filter:

```text
GET /rules?device_id=warehouse-3
```

### Swagger UI

When the server is running:

```text
http://127.0.0.1:8000/docs
```

This provides interactive API testing.

---

## 15. Setup

### Prerequisites

- Python 3.10+
- Ollama
- Llama 3.2
- Git

### 1. Clone

```bash
git clone https://github.com/akaaash-17/natural-language-action-agent.git
cd natural-language-action-agent
```

### 2. Create virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Verify Ollama

```powershell
ollama --version
```

Pull the model if required:

```powershell
ollama pull llama3.2
```

Verify:

```powershell
ollama list
```

### 5. Start the API

```powershell
uvicorn app.main:app --reload
```

Then open:

```text
http://127.0.0.1:8000/docs
```

---

## 16. Testing

Run:

```powershell
pytest -v
```

Current automated suite:

```text
16 passed
```

The tests cover:

1. Root/health endpoint
2. Empty command
3. Invalid request format
4. Alert creation
5. Status queries
6. Unsupported commands
7. Validation errors
8. Empty rules endpoint
9. Stored rules
10. Rules filtering
11. Front-gate camera-offline handling
12. Multiple status queries in one request
13. Mixed multi-intent requests
14. Multiple alert rules in one request
15. Ambiguous parameter rejection
16. Unknown parameter rejection

The LLM layer is mocked where appropriate in API tests so the test suite remains deterministic and does not require Ollama for every test.

---

## 17. Example scenarios

### Single action

```text
Alert me if warehouse-3 temperature stays above 40 degrees for more than 10 minutes.
```

→ `CREATE_ALERT_RULE`

### Multiple metrics

```text
What is the temperature and humidity in warehouse-3?
```

→

```text
QUERY_STATUS → temperature
QUERY_STATUS → humidity
```

### Mixed intents

```text
Check the temperature of warehouse-3 and show me its alert rules.
```

→

```text
QUERY_STATUS
LIST_RULES
```

### Multiple alert rules

```text
Create a temperature alert for warehouse-3 above 40
and a humidity alert for warehouse-3 below 30.
```

→

```text
CREATE_ALERT_RULE → temperature > 40
CREATE_ALERT_RULE → humidity < 30
```

### Ambiguous parameter

```text
What is the temperature in tipper-101?
```

→ Rejected because multiple registered parameters match:

```text
hydraulic_temperature
engine_temperature
oil_temperature
```

### Unknown parameter

```text
What is the battery voltage in tipper-101?
```

→ Rejected because the parameter is not registered.

### Unsupported physical control

```text
Turn off the cooling system in warehouse-3.
```

→ `UNSUPPORTED`

### Event-based alert

```text
Notify security if the front-gate camera goes offline.
```

→ `UNSUPPORTED`

---

## 18. Project structure

```text
natural-language-action-agent/
│
├── app/
│   ├── executor.py       # Executes validated actions
│   ├── llm_parser.py     # Ollama/Llama 3.2 extraction + action planning
│   ├── main.py            # FastAPI application and endpoints
│   ├── models.py          # Pydantic action models
│   ├── registry.py        # Mock device/metric registry
│   ├── resolver.py        # Asset/parameter resolution
│   ├── router.py          # Deterministic intent routing
│   ├── service.py         # Orchestration layer
│   ├── store.py           # In-memory alert-rule store
│   └── validator.py       # Device/metric/action validation
│
├── tests/
│   ├── __init__.py
│   └── test_api.py
│
├── .gitignore
├── README.md
└── requirements.txt
```

---

## 19. Important design decisions

### LLM as translator, not controller

The LLM's responsibility ends after producing structured information.

It does not:

- Decide whether a device exists
- Bypass validation
- Access the store directly
- Control hardware
- Decide whether an unsupported operation should be executed

### Deterministic validation

The application owns the actual constraints.

This makes behavior easier to test, reason about, and secure.

### Multi-action isolation

Each action in an `ActionPlan` is independently resolved, validated, and executed.

One bad action does not automatically invalidate unrelated actions.

### Asset-aware parameter resolution

Broad concepts such as "temperature" are resolved against the selected asset's registered parameters.

The system does not silently choose one when several parameters match.

### In-memory backend

A real database would add infrastructure without adding meaningful value for this assessment.

### Conservative unsupported behavior

When the backend does not model an operation safely, the system rejects it instead of guessing.

---

## 20. Known limitations

This is an assessment project rather than a production monitoring platform.

Current limitations include:

1. The mock registry is intentionally small.
2. Alert rules currently use numeric threshold conditions.
3. Event/state alerts such as camera-offline are not executed.
4. Physical device control is explicitly unsupported.
5. Notification output currently defaults to `EMAIL`.
6. Rules are stored only in memory and disappear when the process stops.
7. The application depends on a locally running Ollama model.
8. Natural-language coverage is intentionally limited to a practical subset.
9. The deterministic router may classify completely novel phrasing as `UNSUPPORTED`.
10. The mock sensor backend is not connected to real-time telemetry.

These are deliberate scope decisions for the current implementation.

---

## 21. Production / real-time evolution

The current architecture can be extended into a real-time application without replacing the core design.

### Real-time data layer

Replace deterministic mock sensor values with:

```text
IoT sensors
   ↓
MQTT / Kafka / event stream
   ↓
Telemetry ingestion service
   ↓
Time-series database
```

Examples of production storage could include PostgreSQL/TimescaleDB, InfluxDB, or another telemetry store.

### Alert evaluation

Instead of simply storing alert rules, introduce a rule engine:

```text
Incoming sensor reading
        ↓
Find rules for asset + parameter
        ↓
Evaluate condition
        ↓
Check duration/window
        ↓
Trigger notification
```

### Persistent storage

Replace the in-memory rule store with a database so rules survive application restarts.

### Notifications

Connect the notification layer to real:

```text
EMAIL
SMS
PUSH
```

providers.

### API and security

Add:

- Authentication
- Authorization
- Tenant isolation
- Rate limiting
- Structured logging
- Request IDs
- Audit logs

### LLM layer

The LLM should remain at the language boundary.

The production principle should still be:

```text
LLM
 ↓
Candidate action
 ↓
Deterministic resolver
 ↓
Deterministic validator
 ↓
Rule engine / execution
```

The LLM should never directly control a physical device.

---

## 22. Optimization opportunities

The next optimization areas would be:

### 1. Improve extraction accuracy

Use:

- tighter structured prompts
- few-shot examples for difficult phrasing
- schema-constrained generation
- deterministic fallback extraction
- confidence/ambiguity handling

### 2. Reduce token usage

Avoid repeatedly sending unnecessarily large registry descriptions.

A production design could retrieve only the relevant asset's schema:

```text
User mentions tipper-101
        ↓
Retrieve tipper-101 schema
        ↓
Send only relevant parameters to LLM
```

This reduces prompt size and improves scalability.

### 3. Reduce LLM calls

The deterministic router already prevents unnecessary high-level classification calls.

Further optimization could combine extraction operations where practical and use deterministic parsing for highly predictable fields.

---

## 23. Evaluator Q&A

### Why did you choose Ollama?

The assignment allows local inference, and this task does not require a cloud model. Ollama keeps inference local, removes API-key and billing dependencies, improves reproducibility, and avoids sending facility commands to an external service.

### Why Llama 3.2?

The task is primarily structured extraction rather than deep reasoning. Llama 3.2 is lightweight enough for local inference while being capable of extracting the fields needed by the application.

### Why a hybrid architecture?

Language understanding is probabilistic, while device existence, parameter compatibility, safety, and execution should be deterministic.

The LLM translates the request. The application decides whether the resulting action is valid.

### Why not use the LLM for intent routing?

The intent space is small and stable. A deterministic router is cheaper, faster, easier to test, and more predictable.

### What happens if the LLM hallucinates a device?

The extracted action is checked against the registry. If the device does not exist, validation fails and the action is not executed.

### What happens if a parameter is ambiguous?

The resolver returns all matching parameters. The system rejects the action and asks the user to specify the intended parameter.

### What happens if the parameter is unknown?

The resolver returns `UNKNOWN`, and the action is rejected before execution.

### Why not execute camera-offline alerts?

The current alert schema models numeric thresholds. `OFFLINE` is an event/state condition, so the system safely returns `UNSUPPORTED` rather than pretending the backend supports it.

### Why use Pydantic?

Pydantic provides typed boundaries between model output and application logic. It makes malformed or incomplete structured output fail early.

### Why use an in-memory store?

The assignment does not require a real database. An in-memory store demonstrates the create-and-query workflow without unnecessary infrastructure.

### What is the most important architectural decision?

The most important decision is **not allowing the LLM to be the final authority**.

The LLM produces a candidate action. The application owns validation and execution.

---

## 24. Summary

This project demonstrates a compact, safety-conscious natural-language action pipeline:

```text
Human language
      ↓
Deterministic intent routing
      ↓
Local LLM extraction
      ↓
Typed Action / ActionPlan
      ↓
Asset + parameter resolution
      ↓
Deterministic validation
      ↓
Execution
      ↓
Mock backend / safe rejection
```

The key engineering trade-off is intentional:

> **The LLM provides flexibility at the language boundary; deterministic application code provides reliability at the action boundary.**
