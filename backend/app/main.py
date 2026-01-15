from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
import pdfplumber
from io import BytesIO
from app.schemas.context import ReasoningContext
from app.orchestrator import AetherOrchestrator
from app.utils.pdf_generator import AETHERPDFGenerator

app = FastAPI(title="Project AETHER", version="1.0.0")

# Basic CORS setup (adjust as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = AetherOrchestrator()
pdf_generator = AETHERPDFGenerator()

import traceback
@app.post("/analyze")
async def analyze(context: ReasoningContext):
    try:
        result = await orchestrator.analyze(context)
        return result
    except HTTPException:
        raise
    except Exception as e:
        print("\nEXCEPTION IN /analyze")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    

@app.post("/analyze-pdf")
async def analyze_pdf(file: UploadFile = File(...)):
    try:
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")
        with pdfplumber.open(file.file) as pdf:
            text = ""
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        if not text.strip():
            raise HTTPException(status_code=400, detail="No text could be extracted from the PDF")
        context = ReasoningContext(
            narrative=text.strip(),
            extracted_facts=[],
            metrics=[],
            assumptions=[],
            limitations=[]
        )
        result = await orchestrator.analyze(context)
        return result
    except HTTPException:
        raise
    except Exception as e:
        print("\nEXCEPTION IN /analyze-pdf")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    

@app.get("/")
async def root():
    return {"service": "Project AETHER", "status": "ok"}


@app.post("/analyze-report")
async def analyze_report(context: ReasoningContext):
    """Analyze text context and return PDF report."""
    try:
        result = await orchestrator.analyze(context)
        pdf_bytes = pdf_generator.generate_report(result, context.narrative)
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=AETHER_Analysis_Report.pdf"}
        )
    except HTTPException:
        raise
    except Exception as e:
        print("\nEXCEPTION IN /analyze-report")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze-pdf-report")
async def analyze_pdf_report(file: UploadFile = File(...)):
    """Upload PDF, analyze it, and return PDF report."""
    try:
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")
        
        with pdfplumber.open(file.file) as pdf:
            text = ""
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        
        if not text.strip():
            raise HTTPException(status_code=400, detail="No text could be extracted from the PDF")
        
        context = ReasoningContext(
            narrative=text.strip(),
            extracted_facts=[],
            metrics=[],
            assumptions=[],
            limitations=[]
        )
        result = await orchestrator.analyze(context)
        pdf_bytes = pdf_generator.generate_report(result, text.strip())
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=AETHER_PDF_Analysis_Report.pdf"}
        )
    except HTTPException:
        raise
    except Exception as e:
        print("\nEXCEPTION IN /analyze-pdf-report")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))