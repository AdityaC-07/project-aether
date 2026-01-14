```md
# Project AETHER

Coordinator-driven **multi-agent AI system** for structured debate, opposition, and synthesis over a normalized reasoning context.

The system extracts debatable factors, argues for and against them using independent agents, and synthesizes a transparent final report — all orchestrated deterministically.

---

## Tech Stack

- **Python 3.10+**
- **FastAPI**
- **Pydantic v2**
- **Gemini API (google-genai SDK)**
- **Async / await**
- **Agent-orchestrated architecture**
- **Structured JSON logging**

---

## Architecture Overview

```

Request
↓
ReasoningContext (validated)
↓
FactorExtractorAgent
↓
SupportAgent
↓
OppositionAgent
↓
SynthesizerAgent
↓
Final Structured Report + Logs

````

- Agents **never call each other**
- The **orchestrator enforces sequence**
- No agent invents facts
- All outputs are **strict JSON**

---

## Setup

### 1) Create and activate a virtual environment (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
````

---

### 2) Install dependencies

```powershell
pip install -r requirements.txt
```

---

### 3) Configure environment variables

Create a `.env` file in the **project root**:

```env
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
AETHER_MODEL=gemini-1.5-flash
```

> ⚠️ `.env` is **git-ignored** and must not be committed.

Environment variables are loaded automatically using `python-dotenv`.

---

## Run the API

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API root:
👉 [http://localhost:8000/](http://localhost:8000/)

---

## Endpoint

### POST `/analyze`

#### Request Body (JSON)

```json
{
  "narrative": "Main report text",
  "extracted_facts": [
    "Customer engagement increased in metro cities during Q3",
    "Tier-2 cities experienced higher churn rates"
  ],
  "metrics": [
    {
      "name": "conversion_rate",
      "region": "metro",
      "value": 3.4
    }
  ],
  "assumptions": [
    "Higher engagement generally leads to higher revenue"
  ],
  "limitations": [
    "Customer demographics were not segmented"
  ]
}
```

---

#### Response Body (JSON)

```json
{
  "final_report": {
    "what_worked": "...",
    "what_failed": "...",
    "why_it_happened": "...",
    "how_to_improve": "..."
  },
  "factors": [
    {
      "factor_id": "F1",
      "description": "...",
      "domain": "sales"
    }
  ],
  "debate_logs": [
    {
      "factor_id": "F1",
      "factor": {
        "factor_id": "F1",
        "description": "...",
        "domain": "sales"
      },
      "support": {
        "support_arguments": [
          {
            "claim": "...",
            "evidence": "...",
            "assumption": "..."
          }
        ]
      },
      "opposition": {
        "counter_arguments": [
          {
            "target_claim": "...",
            "challenge": "...",
            "risk": "..."
          }
        ]
      }
    }
  ]
}
```

---

## Logging

* All reasoning sessions are logged as **structured JSON**
* Location:

  ```
  logs/reasoning_logs.json
  ```
* The `logs/` directory is **ignored by Git**

---

## Key Design Principles

* **No hallucination** — agents rely strictly on provided context
* **Debate-first reasoning** — every claim is challenged
* **Deterministic flow** — orchestrator controls execution
* **Schema-validated outputs** — every agent returns strict JSON
* **Prompt-safe design** — no `.format()` used with JSON templates

---

## Notes

* The system uses **Gemini via `google-genai`**
* Billing or available quota is required for sustained usage
* Free-tier quotas may be limited or zero depending on project settings
* Agents are isolated and stateless per request

```
```
