# Project AETHER

Coordinator-driven **multi-agent AI system** for structured debate, opposition, and synthesis over a normalized reasoning context.

The system extracts debatable factors, argues for and against them using independent agents, and synthesizes a transparent final report — all orchestrated deterministically.

---

## Features

### Backend (Python/FastAPI)

- **Multi-Agent Orchestration**: FactorExtractor, Support, Opposition, and Synthesizer agents working in sequence
- **PDF Processing**:
  - Text extraction from PDFs
  - Table extraction and parsing (numeric values → metrics)
  - Metadata extraction
- **Structured Debate System**: Automatic pro/con analysis for each identified factor
- **Reasoning Context Management**: Unified data model for facts, metrics, assumptions, and limitations
- **JSON Logging**: All analysis sessions logged with full reasoning trace
- **PDF Report Generation**: Beautiful formatted PDF reports with embedded analysis

### Frontend (React/Vite)

- **Interactive UI**: Components for uploading PDFs, entering factors, and viewing results
- **Real-time Analysis**: Direct integration with backend API
- **Responsive Design**: Mobile-friendly interface
- **Factor Management**: Input custom factors with domain tagging
- **Results Display**: Visualized debate logs and synthesis

---

## Tech Stack

- **Backend**: Python 3.10+, FastAPI, Pydantic v2, Gemini API
- **Frontend**: React 18+, Vite, CSS
- **Data Processing**: PyPDF2, Camelot (table extraction), OpenCV
- **Async**: async/await architecture
- **Logging**: Structured JSON logging
- **PDF Generation**: ReportLab

---

## Architecture Overview

```
Request (via API or PDF Upload)
↓
ReasoningContext (validated)
↓
FactorExtractorAgent → Extract debatable factors + domain
↓
SupportAgent → Generate pro arguments for each factor
↓
OppositionAgent → Generate counter arguments
↓
SynthesizerAgent → Combine and synthesize findings
↓
Final Structured Report + Debate Logs
↓
Optional: Generate PDF Report
```

**Key Properties:**

- Agents **never call each other** directly
- **Orchestrator enforces sequence** deterministically
- No agent invents facts beyond the provided context
- All outputs are **strict JSON schemas**
- Table parsing is **optional** and never crashes the pipeline

---

## Setup

### 1) Create and activate a virtual environment (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

---

### 2) Install dependencies

```powershell
pip install -r requirements.txt
```

**Note**: Camelot table extraction requires optional system libraries:

- On Windows, it should work out of the box with opencv-python
- On macOS/Linux, you may need `graphviz` installed for best compatibility

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

## Run the Backend API

```powershell
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API root: 👉 [http://localhost:8000/](http://localhost:8000/)

---

## Run the Frontend

```powershell
cd aether-frontend
npm install
npm run dev
```

Frontend: 👉 [http://localhost:5173/](http://localhost:5173/)

---

## API Endpoints

### POST `/analyze`

Analyze structured reasoning context with debate and synthesis.

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
  "assumptions": ["Higher engagement generally leads to higher revenue"],
  "limitations": ["Customer demographics were not segmented"]
}
```

#### Response Body (JSON)

```json
{
  "final_report": {
    "what_worked": "...",
    "what_failed": "...",
    "why_it_happened": "...",
    "how_to_improve": "...",
    "synthesis": "...",
    "recommendation": "...",
    "confidence_score": 85
  },
  "factors": [
    {
      "description": "...",
      "domain": "sales"
    }
  ],
  "debate_logs": [
    {
      "factor": {
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

### POST `/analyze-pdf`

Upload and analyze a PDF document.

- Extracts text from all pages
- Extracts tables (converts numeric values to metrics)
- Returns analysis results in same format as `/analyze`

---

### POST `/analyze-report`

Analyze structured context and return PDF report.

Returns a beautifully formatted PDF with:

- Executive summary from synthesis
- Extracted factors with domain labels
- Full debate logs with support/opposition arguments
- Timestamps and confidence scores

---

### POST `/analyze-pdf-report`

Upload PDF, analyze it, and return formatted PDF report.

Combines PDF extraction and report generation in one request.

---

## Data Models

### ReasoningContext

```python
class Metric(BaseModel):
    name: str
    region: Optional[str] = None
    value: float

class ReasoningContext(BaseModel):
    narrative: str
    extracted_facts: List[str] = []
    metrics: List[Metric] = []
    assumptions: List[str] = []
    limitations: List[str] = []
```

### Domain Labels

Supported domains for factors:

- Sales
- Organization
- Policy
- Statistics

---

## PDF Processing

### Table Extraction

- Uses **Camelot** library to extract tables from PDFs
- Processes all pages automatically
- **First row** assumed to be headers
- **First column** (if present) becomes region label
- **Numeric cells** converted to metrics
- Non-numeric cells skipped
- Errors logged but never crash the pipeline

### If No Tables Found

- Processing continues normally with text extraction only
- Returns empty metrics list

---

## Logging

- All reasoning sessions are logged as **structured JSON**
- Location: `logs/reasoning_logs.json`
- The `logs/` directory is **ignored by Git**
- Includes full trace of all agent outputs and decisions

---

## Key Design Principles

- **No hallucination** — agents rely strictly on provided context
- **Debate-first reasoning** — every claim is challenged
- **Deterministic flow** — orchestrator controls execution
- **Schema-validated outputs** — every agent returns strict JSON
- **Graceful degradation** — optional features (table parsing) never crash
- **Transparent reasoning** — all intermediate steps logged
- **Domain-aware** — factors categorized by domain for better analysis

---

## Directory Structure

```
project-aether/
├── README.md
├── aether-frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       ├── App.css
│       ├── index.css
│       ├── components/
│       │   ├── PdfUpload.jsx
│       │   ├── FactorsList.jsx
│       │   ├── JsonInput.jsx
│       │   └── ResultsDisplay.jsx
│       ├── pages/
│       │   ├── Home.jsx
│       │   └── Results.jsx
│       └── services/
│           └── api.js
└── backend/
    ├── requirements.txt
    ├── app/
    │   ├── main.py
    │   ├── orchestrator.py
    │   ├── llm_client.py
    │   ├── agents/
    │   │   ├── base_agent.py
    │   │   ├── factor_extractor.py
    │   │   ├── support_agent.py
    │   │   ├── opposition_agent.py
    │   │   └── synthesizer_agent.py
    │   ├── schemas/
    │   │   ├── context.py
    │   │   ├── factor.py
    │   │   ├── debate.py
    │   │   └── final_report.py
    │   ├── utils/
    │   │   ├── pdf_parser.py
    │   │   ├── pdf_generator.py
    │   │   ├── logger.py
    │   │   └── llm_client.py
    │   └── prompts/
    │       ├── factor_prompt.txt
    │       ├── support_prompt.txt
    │       ├── opposition_prompt.txt
    │       └── synthesis_prompt.txt
    └── logs/
        └── reasoning_logs.json
```

---

## Notes

- The system uses **Gemini via `google-genai` SDK**
- Billing or available quota is required for sustained usage
- Free-tier quotas may be limited depending on project settings
- Agents are isolated and stateless per request
- Table parsing works with standard PDFs; complex/scanned PDFs may require OCR (not currently supported)
- All timestamps are UTC

---

## Future Enhancements

- OCR support for scanned PDFs
- Chart extraction and analysis
- Multi-language support
- Custom domain definitions
- Result caching and history
- Advanced report formatting options
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

````

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
````

---

## Logging

- All reasoning sessions are logged as **structured JSON**
- Location:

  ```
  logs/reasoning_logs.json
  ```

- The `logs/` directory is **ignored by Git**

---

## Key Design Principles

- **No hallucination** — agents rely strictly on provided context
- **Debate-first reasoning** — every claim is challenged
- **Deterministic flow** — orchestrator controls execution
- **Schema-validated outputs** — every agent returns strict JSON
- **Prompt-safe design** — no `.format()` used with JSON templates

---

## Notes

- The system uses **Gemini via `google-genai`**
- Billing or available quota is required for sustained usage
- Free-tier quotas may be limited or zero depending on project settings
- Agents are isolated and stateless per request

```

```
