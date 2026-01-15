# Gemini API Integration Guide

## Setup Steps

### 1. **Update Environment Variables**

Edit the `.env` file at the root of your project and replace `your_gemini_api_key_here` with your actual Gemini API key:

```
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_actual_gemini_api_key_here
AETHER_MODEL=gemini-2.0-flash
```

### 2. **Install Dependencies**

Dependencies have been installed via pip:
- `google-generativeai==0.7.1` - Google's Gemini API client library
- `python-dotenv==1.0.1` - For loading environment variables from .env file

### 3. **Code Changes Made**

#### Modified Files:
1. **[requirements.txt](requirements.txt)** - Added Gemini and python-dotenv packages
2. **[app/utils/llm_client.py](app/utils/llm_client.py)** - Added Gemini support with provider switching
3. **[app/orchestrator.py](app/orchestrator.py)** - Added .env file loading via `load_dotenv()`
4. **[.env](.env)** - Created environment configuration file (new)

#### Key Features:
- **Provider Switching**: Set `LLM_PROVIDER` in `.env` to switch between "openai" or "gemini"
- **API Key Management**: Use environment variables for secure API key storage
- **Model Configuration**: Customize the model via `AETHER_MODEL` env variable
- **Backward Compatible**: Still supports OpenAI if you switch back

## Running the Application

### Option 1: Using FastAPI (Development)
```bash
cd c:\Users\Agniv Dutta\project-aether
python -m uvicorn app.main:app --reload
```

### Option 2: Using Python Module Run
```bash
cd c:\Users\Agniv Dutta\project-aether
python -m app.main
```

## Testing Your Setup

You can test the Gemini integration with a simple test:

```bash
cd c:\Users\Agniv Dutta\project-aether
python -c "from app.utils.llm_client import LLMClient; client = LLMClient(); print(f'Using {client.provider} provider')"
```

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_PROVIDER` | No | `openai` | Choose between `openai` or `gemini` |
| `GEMINI_API_KEY` | Yes (if gemini) | - | Your Google Gemini API key |
| `OPENAI_API_KEY` | Yes (if openai) | - | Your OpenAI API key |
| `AETHER_MODEL` | No | `gemini-2.0-flash` (gemini) or `gpt-4o-mini` (openai) | Model to use |

## Available Gemini Models

- `gemini-2.0-flash` (recommended - faster, more efficient)
- `gemini-1.5-pro` (more capable, slower)
- `gemini-1.5-flash` (fast, good quality)

## Troubleshooting

1. **ModuleNotFoundError**: Make sure you run the app from the project root directory using `python -m app.main`
2. **GEMINI_API_KEY not found**: Ensure your `.env` file is in the project root and properly formatted
3. **Authentication errors**: Verify your API key is correct and has proper permissions
