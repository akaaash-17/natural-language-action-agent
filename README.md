# Natural Language Action Agent

A local LLM-powered backend that converts natural-language smart-facility requests into **structured, validated, and executable actions**.

> **Core principle:** Use the LLM for language understanding, while keeping validation, business rules, safety, and execution deterministic.

---

## What Does It Do?

Users can interact with monitoring infrastructure using natural language.

Example:

```text
Alert me if warehouse-3 temperature goes above 400,
what is the hydraulic pressure of tipper-101,
and show me the alert rules for cold-storage-1.
```

The request is decomposed into independent actions:

```text
CREATE_ALERT_RULE
→ warehouse-3 → temperature → ABOVE 400

QUERY_STATUS
→ tipper-101 → hydraulic_pressure

LIST_RULES
→ cold-storage-1
```

---

## Architecture / Workflow

```text
                    User Query
                        │
                        ▼
                 ┌─────────────┐
                 │   FastAPI   │
                 └──────┬──────┘
                        ▼
                 ┌─────────────┐
                 │    Router   │
                 └──────┬──────┘
                        ▼
                 ┌─────────────┐
                 │     LLM     │
                 │   Planner   │
                 └──────┬──────┘
                        ▼
                 ┌─────────────┐
                 │ Typed Action│
                 │    Plan     │
                 └──────┬──────┘
                        ▼
                 ┌─────────────┐
                 │   Resolver  │
                 │ Asset/Param │
                 └──────┬──────┘
                        ▼
                 ┌─────────────┐
                 │  Validator  │
                 └──────┬──────┘
                        ▼
                 ┌─────────────┐
                 │   Executor  │
                 └──────┬──────┘
                        ▼
                  Structured JSON
```

### Pipeline

```text
Natural Language
      ↓
Deterministic Intent Routing
      ↓
LLM Extraction / Decomposition
      ↓
Typed ActionPlan
      ↓
Asset + Parameter Resolution
      ↓
Deterministic Validation
      ↓
Execution
      ↓
User-facing JSON
```

**LLM = understands the request**

**Backend = decides what is allowed and executes it**

---

## Supported Actions

| Action | Purpose |
|---|---|
| `CREATE_ALERT_RULE` | Create a numeric threshold-based alert |
| `QUERY_STATUS` | Retrieve a current sensor value |
| `LIST_RULES` | Retrieve stored alert rules |
| `UNSUPPORTED` | Safely reject unsupported operations |

---

# Major Upgrade: Multi-Asset + Multi-Intent

The original implementation primarily handled requests involving a single asset.

The major upgrade now supports:

- Multiple assets in one request
- Multiple intents in one request
- Multiple parameters
- Mixed action types
- Asset-aware parameter resolution
- Independent validation
- Partial failure handling

Example:

```text
Alert me if warehouse-3 temperature goes above 400,
what is the hydraulic pressure of tipper-101,
and show me the alert rules for cold-storage-1.
```

becomes:

```text
Action 1 → CREATE_ALERT_RULE
Asset    → warehouse-3
Parameter→ temperature

Action 2 → QUERY_STATUS
Asset    → tipper-101
Parameter→ hydraulic_pressure

Action 3 → LIST_RULES
Asset    → cold-storage-1
```

Instead of treating the request as one operation, the system treats it as an **ActionPlan containing independent actions**.

### Partial Failure

```text
Action 1 → SUCCESS
Action 2 → FAILURE
Action 3 → SUCCESS
```

One invalid asset or parameter does not automatically prevent unrelated valid actions from being evaluated.

---

# Asset-Aware Parameter Resolution

The registry is hierarchical.

Example:

```text
tipper-101
├── hydraulic
│   ├── hydraulic_temperature
│   └── hydraulic_pressure
│
└── engine
    ├── engine_temperature
    ├── oil_temperature
    └── engine_pressure
```

Therefore:

```text
What is the hydraulic temperature of tipper-101?
```

resolves to:

```text
hydraulic_temperature
```

But:

```text
What is the temperature of tipper-101?
```

is ambiguous because multiple parameters match:

```text
hydraulic_temperature
engine_temperature
oil_temperature
```

The system rejects the request instead of guessing.

### Resolution States

```text
EXACT
  → one parameter matches

AMBIGUOUS
  → multiple parameters match

UNKNOWN
  → no parameter matches
```

This keeps parameter resolution deterministic and asset-aware.

---

# Why Use a Hybrid LLM Architecture?

The LLM handles:

- Natural-language understanding
- Intent extraction
- Multi-action decomposition
- Asset identification
- Parameter identification
- Threshold and condition extraction

The backend handles:

- Asset existence
- Parameter compatibility
- Ambiguity detection
- Business rules
- Pydantic validation
- Unsupported operations
- Execution

```text
LLM
 ↓
Candidate Structured Action
 ↓
Resolver
 ↓
Validator
 ↓
Executor
```

This separates probabilistic language understanding from deterministic system behavior.

---

# Safety & Validation

Unsupported operations are rejected safely.

Example:

```text
Turn off all the lights in building 7.
```

→ `UNSUPPORTED`

Event/state-based alerts such as:

```text
Notify security if the front-gate camera goes offline.
```

are currently unsupported because the alert model requires a numeric threshold.

> **When the system is uncertain or the operation is outside scope, fail safely rather than guess.**

---

# Optimizations

### Deterministic Routing

The router identifies high-level paths:

```text
CREATE_ALERT_RULE
QUERY_STATUS
LIST_RULES
MULTI_ACTION
UNSUPPORTED
```

This avoids unnecessary LLM calls and reduces latency and inference cost.

### Typed Actions

Pydantic models provide strict schemas between the LLM and backend.

Malformed structured data is rejected before execution.

### Asset-Aware Resolution

Only parameters belonging to the selected asset are considered, preventing incorrect cross-asset mappings.

### Independent Action Processing

Every multi-action operation follows:

```text
Resolve → Validate → Execute
```

independently, enabling partial success.

### Local LLM

The project uses:

```text
Ollama + Llama 3.2
```

for local structured extraction, keeping the assessment self-contained.

---

# API

## POST `/command`

Example request:

```json
{
  "text": "What's the temperature in warehouse-3?"
}
```

Example response:

```json
{
  "success": true,
  "results": [
    {
      "success": true,
      "message": "Current value retrieved successfully.",
      "device_id": "warehouse-3",
      "metric": "temperature",
      "current_value": 36.5
    }
  ]
}
```

A multi-action request returns one structured response containing the result of each action.

## GET `/rules`

Returns stored alert rules.

Optional filter:

```text
/rules?device_id=warehouse-3
```

---

# Testing

Current test suite:

```text
19 tests
19 passed
0 failed
```

Run:

```powershell
pytest -v
```

Coverage includes:

- API endpoints
- Alert creation
- Status queries
- Unsupported commands
- Validation errors
- Rule storage and filtering
- Multiple actions
- Multiple assets
- Mixed intents
- Ambiguous parameters
- Unknown parameters
- Partial failures

The LLM layer is mocked where appropriate so API tests remain deterministic and do not depend on Ollama.

---

# Project Structure

```text
natural-language-action-agent/
│
├── app/
│   ├── executor.py
│   ├── llm_parser.py
│   ├── main.py
│   ├── models.py
│   ├── registry.py
│   ├── resolver.py
│   ├── router.py
│   ├── service.py
│   ├── store.py
│   └── validator.py
│
├── tests/
│   └── test_api.py
│
├── README.md
└── requirements.txt
```

---

# Running Locally

### 1. Create environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Start Ollama

```powershell
ollama pull llama3.2
```

### 4. Start FastAPI

```powershell
uvicorn app.main:app --reload
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

---

# Interview Perspective

### Why use an LLM?

Natural-language requests are flexible and difficult to handle reliably with only regex or hardcoded rules. The LLM converts natural language into structured actions.

### Why not let the LLM execute actions directly?

LLMs are probabilistic. Asset existence, parameter compatibility, validation, business rules, and execution require deterministic guarantees.

```text
LLM → Interpretation
Backend → Validation + Execution
```

### How is ambiguity handled?

The resolver checks parameters registered for the selected asset.

```text
EXACT      → one match
AMBIGUOUS  → multiple matches
UNKNOWN    → no match
```

Ambiguous and unknown parameters are rejected.

### How does multi-asset processing work?

The LLM creates an `ActionPlan`. Every action carries its own intent, asset, parameter, and arguments. The service resolves, validates, and executes each action independently.

### What happens if one action fails?

Other independent actions can still succeed.

```text
warehouse-3     → SUCCESS
tipper-101      → FAILURE
cold-storage-1  → SUCCESS
```

The final response reports each action outcome.

### How would this scale?

The current registry is intentionally small for the assessment.

For production, asset metadata should move to a database or asset-management service. The system should retrieve only relevant metadata instead of sending the complete registry to the LLM.

```text
User Query
    ↓
Identify Relevant Assets
    ↓
Retrieve Relevant Metadata
    ↓
LLM Extraction
    ↓
Deterministic Resolution
    ↓
Validation
    ↓
Execution
```

This reduces prompt size, latency, and unnecessary context.

---

# Real-Time Production Evolution

The current project uses mock telemetry and in-memory rule storage.

A production system can separate the natural-language control plane from real-time telemetry processing:

```text
                  User / Operator
                        │
                        ▼
              Natural Language API
                        │
                        ▼
                 Action Planner
                        │
                        ▼
              Rule / Command Service
                        │
                        ▼
                 Persistent Store


IoT Sensors
     │
     ▼
 MQTT / Kafka
     │
     ▼
Telemetry Ingestion
     │
     ▼
Time-Series Database
     │
     ▼
Real-Time Rule Engine
     │
     ├── Alert
     ├── Notification
     └── Monitoring
```

The LLM configures or queries the system, while the real-time rule engine continuously evaluates incoming telemetry.

This keeps the LLM out of the critical path for high-frequency sensor evaluation.

---

# Current Limitations

- Mock sensor data
- In-memory alert-rule storage
- Numeric threshold alerts only
- Physical device control is unsupported
- Event/state-based alerts are currently unsupported
- Local Ollama inference is required

These limitations are intentional for the assessment scope.

---

# Future Improvements

Potential production upgrades:

- PostgreSQL / TimescaleDB
- MQTT / Kafka telemetry ingestion
- Redis caching
- Authentication and authorization
- Rate limiting
- Audit logging
- Structured logging
- Persistent alert rules
- Real-time rule evaluation
- Notification services
- Observability and tracing
- Async/background execution

---

# Key Engineering Takeaway

The architecture separates **language flexibility from system reliability**:

```text
Human Language
      ↓
      LLM
      ↓
Typed Actions
      ↓
Asset-Aware Resolution
      ↓
Deterministic Validation
      ↓
Safe Execution
```

The major upgrade from single-asset handling to **multi-asset + multi-intent action planning** makes the system more realistic for operational environments while preserving deterministic validation and safe execution.

> **The LLM provides flexibility at the language boundary; deterministic application code provides reliability at the action boundary.**
