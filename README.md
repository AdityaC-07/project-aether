# Project AETHER

Coordinator-driven multi-agent AI system for structured debate and synthesis.

## Tech Stack
- Python 3.10+
- FastAPI
- Pydantic
- OpenAI-compatible LLM client
- Async/await
- JSON file logging

## Setup

1) Create and activate a virtual environment (Windows PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2) Install dependencies:
```powershell
pip install -r requirements.txt
```

3) Configure environment for LLM access:
- Set `OPENAI_API_KEY` (required)
- Optionally set `OPENAI_BASE_URL` for OpenAI-compatible providers
- Optionally set `AETHER_MODEL` (default: `gpt-4o-mini`)

Example (PowerShell):
```powershell
$env:OPENAI_API_KEY = "YOUR_KEY"
# $env:OPENAI_BASE_URL = "https://api.openai.com/v1"  # optional
# $env:AETHER_MODEL = "gpt-4o-mini"                   # optional
```

## Run the API
```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

API root: http://localhost:8000/

## Endpoint
- POST `/analyze`
  - Body (JSON):
```json
{
  "narrative": "Main report text",
  "extracted_facts": ["fact1", "fact2"],
  "metrics": [{"name": "conversion_rate", "region": "metro", "value": 3.4}],
  "assumptions": ["assumption1"],
  "limitations": ["limitation1"]
}
```

- Response (JSON):
```json
{
  "final_report": {"what_worked": "...", "what_failed": "...", "why_it_happened": "...", "how_to_improve": "..."},
  "factors": [{"factor_id": "F1", "description": "...", "domain": "sales"}],
  "debate_logs": [
    {
      "factor_id": "F1",
      "factor": {"factor_id": "F1", "description": "...", "domain": "sales"},
      "support": {"support_arguments": [{"claim": "...", "evidence": "...", "assumption": "..."}]},
      "opposition": {"counter_arguments": [{"target_claim": "...", "challenge": "...", "risk": "..."}]}
    }
  ]
}
```

## Logging
- All structured reasoning is saved to `logs/reasoning_logs.json` as an array of session entries.

## Notes
- Agents never call each other; the orchestrator controls the sequence.
- The system uses only the normalized input context; no raw files are accessed.