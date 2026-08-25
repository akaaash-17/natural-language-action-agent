# Natural Language Action Agent

A small, local LLM-powered backend that converts natural-language smart-facility requests into **typed, validated, executable actions**.

The core design principle is simple:

> **Use the LLM for language understanding, but do not trust the LLM with validation, safety, or execution.**

The service accepts plain-English requests such as:

> "Alert me if warehouse-3 temperature stays above 40 degrees for more than 10 minutes."

It turns the request into a structured action, validates that the device and metric actually exist in the mock facility registry, and then executes supported actions against deterministic mock data.

The project uses **FastAPI + Ollama + Llama 3.2 + Pydantic**, with an in-memory rule store.

---

## 1. What problem does this solve?

Smart-facility systems normally expose structured operations such as:

- create an alert rule
- query the current status of a device
- list existing alert rules

Those operations are easy for software to represent but less convenient for humans to express.

Instead of forcing an operator to provide JSON such as:

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

the user can simply say:

> "Alert me if warehouse-3 temperature stays above 40 degrees for more than 10 minutes."

The agent handles the translation from natural language to a structured action.

The important part is that the generated action is **not executed blindly**. The application validates it against its own rules first.

---

## 2. What the system supports

### Supported actions

| Action | Example | Behavior |
|---|---|---|
| `CREATE_ALERT_RULE` | "Alert me if warehouse-3 temperature goes above 40" | Creates an in-memory alert rule |
| `QUERY_STATUS` | "What's the temperature in warehouse-3?" | Reads deterministic mock sensor data |
| `LIST_RULES` | "Show existing alert rules" | Returns stored rules |
| `UNSUPPORTED` | "Turn off the cooling system" | Safely rejects the request |

### Mock device registry

The current registry contains:

- `warehouse-3` → temperature, humidity
- `cold-storage-1` → temperature, humidity
- `front-gate` → camera_status, occupancy
- `server-room-1` → temperature, humidity
- `production-floor-1` → temperature, humidity, occupancy
- `loading-bay-1` → temperature, occupancy

The registry is deliberately small and deterministic because this is a take-home exercise rather than a real facility integration.

---

## 3. Architecture

```text
                         User
                          |
                          v
                 +----------------+
                 |    FastAPI     |
                 |    /command    |
                 |     /rules     |
                 +-------+--------+
                         |
                         v
                 +----------------+
                 | Intent Router  |
                 | deterministic  |
                 +-------+--------+
                         |
             +-----------+-----------+
             |                       |
             v                       v
       Known intent            Unsupported/
             |                  ambiguous
             v                       |
     +----------------+              |
     | Ollama /       |              |
     | Llama 3.2      |              |
     | field extraction|             |
     +-------+--------+              |
             |                       |
             v                       |
     +----------------+              |
     | Pydantic       |              |
     | typed models   |              |
     +-------+--------+              |
             |                       |
             v                       |
     +----------------+              |
     | Validator      |              |
     | device/metric  |              |
     | checks         |              |
     +-------+--------+              |
             |
       +-----+------+
       |            |
       v            v
     Valid        Invalid
       |            |
       v            v
   Executor      HTTP 422
       |
       v
+----------------------+
| In-memory Store /    |
| Deterministic Mock   |
| Sensors              |
+----------------------+
```

### Request lifecycle

For a supported request:

```text
Natural language
      ↓
Intent classification
      ↓
LLM parameter extraction
      ↓
Pydantic validation
      ↓
Device/metric validation
      ↓
Mock execution
      ↓
Structured JSON response
```

For an invalid or unsupported request:

```text
Natural language
      ↓
Intent classification
      ↓
Unsupported OR invalid structured action
      ↓
Safe rejection
      ↓
Clear error/reason
```

---

## 4. Why is this a hybrid design?

This is intentionally **not an end-to-end LLM agent**.

The system uses two different mechanisms for two different jobs.

### Deterministic code handles

- high-level intent routing
- allowed action types
- Pydantic schema validation
- device existence
- metric/device compatibility
- execution
- storage
- HTTP error handling

### The LLM handles

- understanding natural language
- extracting device IDs
- extracting metrics
- interpreting conditions such as "above", "below", and "exceeds"
- extracting numeric thresholds
- extracting durations from phrases such as "for ten minutes"

This separation is important because language understanding is probabilistic, while safety and business constraints should be deterministic.

If the model says:

```json
{
  "device": "reactor-core",
  "metric": "pressure"
}
```

the application does **not** assume that the device exists.

The validator checks the registry and rejects it:

```text
Device 'reactor-core' does not exist in the device registry.
```

This is the main reliability boundary in the project.

---

## 5. Why Ollama?

I chose Ollama because the assignment explicitly allows a local LLM and the problem does not require a cloud model.

Using Ollama provides several practical advantages for this project:

### 1. Completely local

No paid API key or external LLM service is required.

The entire language-understanding step runs locally.

### 2. Easier evaluation

An evaluator can reproduce the same architecture without needing:

- OpenAI credentials
- Anthropic credentials
- API billing
- cloud configuration

They only need Ollama and the selected model.

### 3. Privacy

Facility commands can potentially contain operational information. Keeping inference local avoids sending those requests to a third-party API.

### 4. Simple integration

Ollama exposes a straightforward local HTTP API. The parser sends a prompt requesting JSON and validates the returned object with Pydantic.

### 5. Good fit for the assignment

The assignment explicitly says a local model via Ollama is acceptable. For a small structured-extraction task, a local model is a reasonable engineering trade-off.

---

## 6. Why Llama 3.2?

The project uses:

```text
llama3.2
```

through Ollama.

The task does not require a large reasoning model. The model mainly needs to perform constrained information extraction:

- identify a device
- identify a metric
- identify a condition
- extract numbers
- extract duration
- return JSON

Llama 3.2 provides a practical balance for this use case:

- small enough to run locally
- capable enough for natural-language extraction
- available directly through Ollama
- avoids unnecessary cloud/API dependency

I intentionally did not optimize this project around using the newest or largest model. The objective is a **dependable action pipeline**, not maximizing model capability.

The model can be replaced later without changing the validation or execution layers.

---

## 7. Why not let the LLM validate everything?

Because that would create an unnecessary safety dependency on probabilistic output.

For example, the model could understand:

> "Alert me if reactor-core pressure exceeds 9000."

and produce a perfectly valid-looking JSON object.

But `reactor-core` does not exist in the registry.

The correct behavior is therefore:

```text
LLM → understands request
       ↓
structured action
       ↓
application validator → device does not exist
       ↓
HTTP 422
```

The LLM is therefore treated as a **translator**, not as the source of truth.

The registry and Pydantic models remain the source of truth.

---

## 8. Prompt design

The extraction prompts are intentionally constrained.

The prompts provide the model with:

1. the valid device registry
2. the expected fields
3. explicit extraction rules
4. examples
5. an instruction to return JSON only

For example, the alert extraction prompt tells the model:

- never invent a device
- use an exact device ID from the registry
- do not confuse a metric/sensor with a device
- map "above" to `ABOVE`
- map "below" to `BELOW`
- convert durations such as "more than 10 minutes"
- return `null` when an event condition has no numeric threshold
- return JSON only

The returned JSON is then parsed and validated with Pydantic.

This gives us a second validation boundary after the model itself.

---

## 9. Handling ambiguity: the camera-offline case

One of the required assignment cases is:

> "notify security if the front-gate camera goes offline"

This is intentionally different from a normal numeric alert.

A normal supported alert looks like:

```text
temperature > 40 for 10 minutes
```

The current action schema is based on numeric threshold conditions:

```text
ABOVE
BELOW
EQUALS
```

A camera going offline is an **event/state condition**, not a numeric threshold.

The LLM can understand the request:

```json
{
  "device": "front-gate",
  "metric": "camera_status",
  "condition": "OFFLINE",
  "threshold": null,
  "duration_minutes": null
}
```

but the service deliberately does not execute that action.

Instead it returns:

```json
{
  "type": "UNSUPPORTED"
}
```

with a reason explaining that the current alert implementation requires a numeric threshold.

### Why this decision?

I preferred a safe rejection over inventing semantics for an action that the current backend does not support.

With more time, the action model could be extended with explicit event-based rules such as:

```text
condition: OFFLINE
```

but that is outside the current implementation scope.

---

## 10. Validation and safety

Validation happens after LLM extraction.

### Device validation

The device must exist in `DEVICE_REGISTRY`.

Unknown device:

```text
reactor-core
```

results in:

```text
422 VALIDATION_ERROR
Device 'reactor-core' does not exist in the device registry.
```

### Metric validation

The metric must be supported by the specific device.

For example:

```text
warehouse-3 → temperature ✓
warehouse-3 → humidity ✓
warehouse-3 → pressure ✗
```

An unsupported metric is rejected rather than silently executed.

### Physical control

The system does not directly control physical equipment.

Requests such as:

> "Turn off the cooling system in warehouse-3."

are returned as:

```json
{
  "type": "UNSUPPORTED"
}
```

No physical action is attempted.

---

## 11. Mock execution model

There is deliberately no real database or physical hardware integration.

The assignment asks for a mock backend, so the implementation uses:

- deterministic mock sensor values
- an in-memory rule store
- no external database

For example, a status query can return:

```json
{
  "success": true,
  "device_id": "warehouse-3",
  "metric": "temperature",
  "value": 36.5
}
```

Creating an alert appends the validated rule to the in-memory store.

The rules can then be queried through:

```text
GET /rules
```

The store lasts for the lifetime of the application process.

---

## 12. API

### `GET /`

Health check.

Example response:

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

Example response:

```json
{
  "success": true,
  "input": "Alert me if warehouse-3 temperature stays above 40 degrees for more than 10 minutes.",
  "action": {
    "type": "CREATE_ALERT_RULE",
    "device_id": "warehouse-3",
    "metric": "temperature",
    "condition": "ABOVE",
    "threshold": 40,
    "duration_minutes": 10,
    "notify_via": ["EMAIL"]
  },
  "result": {
    "success": true,
    "message": "Alert rule created successfully."
  }
}
```

### `GET /rules`

Returns all stored alert rules.

Optional filter:

```text
GET /rules?device_id=warehouse-3
```

---

## 13. Setup

### Prerequisites

- Python 3.10+
- Ollama
- Llama 3.2
- Git

### 1. Clone the repository

```bash
git clone https://github.com/akaaash-17/natural-language-action-agent.git
cd natural-language-action-agent
```

### 2. Create a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Install/start Ollama

Verify:

```powershell
ollama --version
```

Pull the model if necessary:

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

The API will be available at:

```text
http://127.0.0.1:8000
```

Interactive API documentation:

```text
http://127.0.0.1:8000/docs
```

---

## 14. Running tests

Run:

```powershell
pytest -v
```

The project currently contains automated coverage for:

1. root/health endpoint
2. empty commands
3. malformed request bodies
4. valid alert creation
5. status queries
6. unsupported commands
7. validation errors
8. empty rules endpoint
9. stored rules
10. rules filtering
11. front-gate camera-offline handling

Latest local verification:

```text
11 passed
```

The required assignment cases are therefore covered by automated tests, not only manual Swagger/cURL checks.

---

## 15. Example scenarios

### Create an alert

Input:

```text
Alert me if warehouse-3 temperature stays above 40 degrees for more than 10 minutes.
```

Expected:

```text
CREATE_ALERT_RULE
```

### Query status

Input:

```text
Could you please tell me the temperature at warehouse-3 right now?
```

Expected:

```text
QUERY_STATUS
```

### Query another metric

Input:

```text
What is the humidity in cold-storage-1 right now?
```

Expected:

```text
QUERY_STATUS
```

### Invalid device

Input:

```text
Alert me if reactor-core pressure exceeds 9000.
```

Expected:

```text
HTTP 422
Device 'reactor-core' does not exist in the device registry.
```

### Unsupported physical control

Input:

```text
Turn off the cooling system in warehouse-3.
```

Expected:

```text
UNSUPPORTED
```

### Event-based alert

Input:

```text
Notify security if the front-gate camera goes offline.
```

Expected:

```text
UNSUPPORTED
```

because event-based camera state alerts are outside the current numeric-threshold alert model.

---

## 16. Project structure

```text
natural-language-action-agent/
│
├── app/
│   ├── executor.py       # Executes validated actions
│   ├── llm_parser.py     # Ollama/Llama 3.2 extraction
│   ├── main.py           # FastAPI application and endpoints
│   ├── models.py         # Pydantic action models
│   ├── registry.py       # Mock device/metric registry
│   ├── router.py         # Deterministic intent routing
│   ├── service.py        # Orchestration layer
│   ├── store.py          # In-memory alert-rule store
│   └── validator.py      # Device/metric/action validation
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

## 17. Design decisions

### LLM as translator, not controller

The LLM's job ends after producing structured information.

It does not:

- decide whether a device exists
- bypass validation
- access the store directly
- control hardware
- decide whether an action is safe to execute

### Deterministic validation

The application owns the actual constraints.

This makes behavior easier to test and reason about.

### In-memory backend

A real database would add infrastructure without adding meaningful value for this assignment.

The in-memory store demonstrates the required create-and-query workflow while keeping the implementation small.

### Local inference

Ollama removes external API dependencies and makes the project easy to reproduce locally.

### Conservative unsupported behavior

When the system cannot map a request into a supported action safely, it rejects the request rather than guessing.

---

## 18. Known limitations

This is intentionally a small assessment project rather than a production monitoring platform.

Current limitations include:

1. **Only a small mock device registry is available.**
2. **Alert rules currently use numeric threshold conditions.**
3. **Event/state alerts such as camera-offline are not executed.**
4. **Physical device control is explicitly unsupported.**
5. **Alert notification output currently defaults to `EMAIL`.** The action schema supports `EMAIL`, `SMS`, and `PUSH`, but the current service path uses email as the default.
6. **Rules are stored only in memory**, so they disappear when the process stops.
7. **The system depends on a locally running Ollama model.**
8. **Natural-language coverage is intentionally limited to a reasonable subset rather than every possible phrasing.**
9. **The intent router is deterministic rather than LLM-based, which improves predictability but means completely novel intent wording may fall back to `UNSUPPORTED`.**

These are deliberate scope decisions rather than attempts to simulate a production IoT platform.

---

## 19. What I would improve with more time

If this were moved toward production, I would prioritize:

1. Add explicit event-based alert models such as `OFFLINE`.
2. Extract and honor `notify_via` values such as SMS/PUSH instead of defaulting to EMAIL.
3. Add stronger malformed-LLM-output recovery and retry/fallback behavior.
4. Add structured logging and request IDs.
5. Add more comprehensive parser tests and fuzz/edge-case tests.
6. Replace the in-memory store with a persistent database.
7. Add authentication and authorization.
8. Add prompt-injection defenses.
9. Add model/configuration through environment variables.
10. Add CI to run tests automatically.

The core architecture would remain the same: **LLM for language understanding, application code for validation and execution.**

---

## 20. Evaluator Q&A

### Why did you choose Ollama instead of OpenAI?

The assignment allows a local model, and this task does not require a large cloud model. Ollama keeps the complete system local, removes API-key and billing dependencies, improves reproducibility for evaluation, and avoids sending facility commands to an external service.

### Why use a hybrid approach?

Because the responsibilities are fundamentally different.

Natural-language interpretation benefits from an LLM. Device existence, metric compatibility, schema validation, safety decisions, and execution should be deterministic.

This makes the system more predictable and prevents a plausible-looking LLM response from becoming an unchecked backend action.

### Why Llama 3.2?

The extraction task is relatively narrow. It does not require complex multi-step reasoning or a large frontier model.

Llama 3.2 is small enough for local inference while being capable of extracting the structured fields required by this application. It is also directly available through Ollama.

### Why not use the LLM for intent routing too?

The intent space is small and stable:

```text
CREATE_ALERT_RULE
QUERY_STATUS
LIST_RULES
UNSUPPORTED
```

A deterministic router is easier to test and makes obvious safety boundaries predictable. The LLM is then used where it provides the most value: interpreting the parameters inside a known intent.

### What happens if the LLM hallucinates a device?

The action does not get trusted automatically.

The validator checks the device against `DEVICE_REGISTRY`. An unknown device produces an HTTP 422 validation error.

### What happens if the LLM returns an unsupported metric?

The validator checks the metric against the selected device's supported metrics and rejects the action.

### Why not execute camera-offline alerts?

The current alert schema is numeric-threshold based. A camera going offline is a state/event condition rather than `ABOVE`, `BELOW`, or `EQUALS` with a numeric threshold.

The system therefore safely returns `UNSUPPORTED` rather than pretending the backend can execute an action it does not model.

### Why use Pydantic?

Pydantic gives the application explicit typed boundaries between untrusted model output and application logic. It makes malformed or incomplete structured output fail early instead of flowing into execution.

### Why an in-memory store?

The assignment explicitly says that no real database is required. An in-memory list demonstrates the required create-and-query behavior without introducing unnecessary infrastructure.

### What is the most important architectural decision?

The most important decision is **not allowing the LLM to be the final authority**.

The LLM translates language into a candidate action. The application decides whether that action is valid and executable.

That distinction is what makes the system an action service rather than simply an LLM that generates JSON.

---

## 21. Summary

This project demonstrates a compact but safety-conscious natural-language action pipeline:

```text
Human language
      ↓
Deterministic intent routing
      ↓
Local LLM extraction
      ↓
Pydantic structured action
      ↓
Registry validation
      ↓
Deterministic execution
      ↓
Mock backend / clear rejection
```

The key engineering trade-off is intentional:

> **The LLM provides flexibility at the language boundary; deterministic application code provides reliability at the action boundary.**
