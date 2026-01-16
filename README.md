# Project AETHER 🚀

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18+-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://reactjs.org/)
[![Vite](https://img.shields.io/badge/Vite-646CFF?style=for-the-badge&logo=vite&logoColor=white)](https://vitejs.dev/)
[![Google Gemini](https://img.shields.io/badge/Google_Gemini-8E75B2?style=for-the-badge&logo=google&logoColor=white)](https://ai.google.dev/)
[![Vertex AI](https://img.shields.io/badge/Vertex_AI-4285F4?style=for-the-badge&logo=google-cloud&logoColor=white)](https://cloud.google.com/vertex-ai)

> **Coordinator-driven multi-agent AI system for structured debate, opposition, and synthesis over a normalized reasoning context.**

Project AETHER eliminates bias in decision-making by enforcing a **"debate-first"** approach, where independent AI agents systematically argue for and against key claims extracted from complex documents. The system synthesizes balanced, transparent final reports—perfect for analyzing business reports, policy documents, sales data, and organizational insights.



## 🎯 Problem Statement

Traditional AI summarization tools provide one-sided insights without challenging assumptions. Business Intelligence tools visualize data but lack critical reasoning. Manual document analysis is time-consuming and prone to confirmation bias.

**Project AETHER solves this by:**
- ✅ Automating adversarial debate on every claim
- ✅ Ensuring comprehensive evaluation through multi-agent architecture
- ✅ Generating actionable insights with transparency and auditability
- ✅ Reducing decision errors by an estimated 20-50%

---

## ✨ Key Features

### 🎭 Multi-Agent Debate System
- **FactorExtractor Agent**: Identifies debatable factors from input documents
- **Support Agent**: Generates pro arguments with evidence and assumptions
- **Opposition Agent**: Creates counter-arguments challenging each claim
- **Synthesizer Agent**: Combines findings into balanced final reports

### 📄 Flexible Input Processing
- **PDF Upload**: Automatic text and table extraction from documents
- **JSON Input**: Manual entry of narratives, facts, metrics, assumptions, and limitations
- **Table Parsing**: Converts numeric table data into structured metrics

### 📊 Intelligent Analysis
- Structured debate logs for every identified factor
- Domain categorization (Sales, Organization, Policy, Statistics)
- Confidence scoring (0-100) based on debate balance and depth
- Evidence-based reasoning with assumption tracking

### 📋 Comprehensive Reporting
- **What worked**: Successful factors and their impact
- **What failed**: Problematic areas requiring attention
- **Why it happened**: Root cause analysis
- **How to improve**: Actionable recommendations
- **Synthesis**: Executive summary with confidence score

### 🔒 Enterprise-Ready
- Schema-validated outputs (Pydantic v2)
- Structured JSON logging for audit trails
- Async architecture for scalability
- Git-ignored sensitive data and logs
- API-key protected endpoints

---

## 🏗️ Architecture

```
Request (PDF/JSON)
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
Final Report + Debate Logs + Optional PDF
```

**Key Principles:**
- 🚫 No agent-to-agent communication (deterministic orchestration)
- 📜 No hallucination (strict context adherence)
- ✅ Schema-validated outputs
- 🛡️ Graceful degradation (optional features never crash)

---

## 🛠️ Tech Stack

### Backend
- **Framework**: FastAPI
- **Language**: Python 3.10+
- **LLM**: Google Gemini (gemini-1.5-flash)
- **AI Platform**: Vertex AI
- **Validation**: Pydantic v2
- **PDF Processing**: PyPDF2, Camelot, OpenCV
- **Report Generation**: ReportLab
- **Async**: asyncio/await

### Frontend
- **Framework**: React 18+
- **Build Tool**: Vite
- **Styling**: CSS
- **HTTP Client**: Fetch API

### DevOps
- **Environment**: python-dotenv
- **Logging**: Structured JSON
- **Version Control**: Git (with .gitignore for secrets)

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10 or higher
- Node.js 16+ and npm
- Google Gemini API key
- (Optional) Graphviz for advanced table extraction

### Backend Setup

```bash
# Clone the repository
git clone https://github.com/AdityaC-07/project-aether.git
cd project-aether/backend

# Create virtual environment (Windows PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# For Unix/macOS
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
# Create .env file in backend directory
echo "GEMINI_API_KEY=your_api_key_here" > .env
echo "AETHER_MODEL=gemini-1.5-flash" >> .env

# Run the server
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Backend API: http://localhost:8000

### Frontend Setup

```bash
cd ../aether-frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

Frontend UI: http://localhost:5173

---

## 📡 API Endpoints

### POST `/analyze`
Analyze structured reasoning context with debate and synthesis.

**Request Body:**
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
  "assumptions": ["Higher engagement leads to higher revenue"],
  "limitations": ["Customer demographics were not segmented"]
}
```

**Response:**
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
  "factors": [...],
  "debate_logs": [...]
}
```

### POST `/analyze-pdf`
Upload and analyze a PDF document (returns JSON).

### POST `/analyze-report`
Analyze structured context and return formatted PDF report.

### POST `/analyze-pdf-report`
Upload PDF, analyze it, and return formatted PDF report in one request.

---

## 📁 Project Structure

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
    ├── .env (git-ignored)
    ├── app/
    │   ├── main.py
    │   ├── orchestrator.py
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
        └── reasoning_logs.json (git-ignored)
```

---

## 📊 Data Models

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
- **Sales**: Revenue, conversion, customer metrics
- **Organization**: Structure, processes, workflows
- **Policy**: Regulations, compliance, guidelines
- **Statistics**: Data analysis, trends, patterns







## 🔮 Future Enhancements

- [ ] OCR support for scanned PDFs
- [ ] Chart extraction and analysis
- [ ] Multi-language support
- [ ] Custom domain definitions
- [ ] Result caching and history
- [ ] Advanced report formatting options
- [ ] Real-time collaborative analysis
- [ ] Integration with more LLM providers

---

## 🏆 Hackathon Details

**Team**: Autizhacks  
**Team Leader**: Aditya Choudhuri  
**Problem Statement**: Project Aether - AI/ML  
**Technologies**: Vertex AI, Google Gemini LLMs

---

## ⚠️ Important Notes

- Requires active Google Gemini API key with billing enabled
- Free-tier quotas may be limited depending on project settings
- `.env` file must never be committed (git-ignored by default)
- Table parsing works best with standard PDFs (scanned PDFs require OCR)
- All timestamps are in UTC
- Logs are stored locally and not version controlled

---

## 📝 License

This project is part of a hackathon submission. Please contact the team for licensing information.

---

## 👥 Team

**Autizhacks**
- Aditya Choudhuri (Team Leader)

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📧 Contact

For questions or feedback, please open an issue on GitHub or contact the team through the repository.

---

<div align="center">

**Made with ❤️ by Team Autizhacks**

⭐ Star this repository if you find it useful!

</div>
