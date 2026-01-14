from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.schemas.context import ReasoningContext
from app.orchestrator import AetherOrchestrator

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
    

@app.get("/")
async def root():
    return {"service": "Project AETHER", "status": "ok"}
