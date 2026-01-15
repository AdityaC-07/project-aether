# Vite Migration Guide

## Frontend Setup (Vite)

The frontend has been migrated from Create React App to **Vite** for better performance and faster development experience.

### Installation & Setup

```bash
cd aether-frontend
npm install
```

### Development

```bash
npm run dev
```

The frontend will start on `http://localhost:3000` with HMR (Hot Module Replacement) enabled.

### Production Build

```bash
npm run build
```

Built files will be in the `dist/` directory.

### Preview Production Build

```bash
npm run preview
```

## Key Changes

1. **Entry Point**: Changed from `src/index.js` to `src/main.jsx`
2. **HTML**: Root HTML file moved to project root as `index.html`
3. **React**: Updated to use `.jsx` extension for JSX files
4. **API Proxy**: Configured in `vite.config.js` to proxy `/api` requests to `http://localhost:8000`

## Backend Setup (FastAPI)

Make sure the backend is running on port 8000:

```bash
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

## CORS

Frontend (http://localhost:3000) and Backend (http://localhost:8000) communicate with proper CORS headers configured in FastAPI.
