"""
Options Wheel Dashboard - FastAPI Backend

Provides API endpoints for the monitoring dashboard:
- Real-time data from trading bot Cloud Run service
- Historical data from BigQuery
- Aggregated metrics and analytics
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from routers import live, history, metrics

app = FastAPI(
    title="Options Wheel Dashboard API",
    description="Monitoring dashboard for options wheel trading bot",
    version="1.0.0"
)

# CORS configuration for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",
        "https://*.run.app",  # Cloud Run
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(live.router, prefix="/api/live", tags=["live"])
app.include_router(history.router, prefix="/api/history", tags=["history"])
app.include_router(metrics.router, prefix="/api/metrics", tags=["metrics"])


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "options-wheel-dashboard"}


# Serve static files in production
static_dir = os.path.join(os.path.dirname(__file__), "../frontend/dist")
if os.path.exists(static_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(static_dir, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the SPA for all non-API routes."""
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"error": "Frontend not built"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
