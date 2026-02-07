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
from app.utils.pdf_parser import extract_metadata_and_text

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
        
        file_bytes = await file.read()
        pdf_data = extract_metadata_and_text(file_bytes)
        
        context = ReasoningContext(
            narrative=pdf_data["text"],
            extracted_facts=[],
            metrics=pdf_data.get("metrics", []),
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


@app.get("/status")
async def status():
    return orchestrator.status


@app.post("/analyze-report")
async def analyze_report(context: ReasoningContext):
    """Analyze text context and return PDF report."""
    try:
        result = await orchestrator.analyze(context)
        pdf_bytes = pdf_generator.generate_report(result, context.narrative)
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=Analysis_Report.pdf"}
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
        
        file_bytes = await file.read()
        pdf_data = extract_metadata_and_text(file_bytes)
        
        context = ReasoningContext(
            narrative=pdf_data["text"],
            extracted_facts=[],
            metrics=pdf_data.get("metrics", []),
            assumptions=[],
            limitations=[]
        )
        result = await orchestrator.analyze(context)
        pdf_bytes = pdf_generator.generate_report(result, pdf_data["text"])
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=PDF_Analysis_Report.pdf"}
        )
    except HTTPException:
        raise
    except Exception as e:
        print("\nEXCEPTION IN /analyze-pdf-report")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download-report")
async def download_report():
    """Return PDF report for the most recent analysis without re-running."""
    try:
        if not orchestrator.last_result or not orchestrator.last_narrative:
            raise HTTPException(status_code=400, detail="No analysis available for report download")

        pdf_bytes = pdf_generator.generate_report(
            orchestrator.last_result,
            orchestrator.last_narrative,
        )

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=Analysis_Report.pdf"},
        )
    except HTTPException:
        raise
    except Exception as e:
        print("\nEXCEPTION IN /download-report")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))