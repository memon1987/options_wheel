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
# In Docker: frontend is at /app/static
# In development: frontend is at ../frontend/dist
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    static_dir = os.path.join(os.path.dirname(__file__), "../frontend/dist")

if os.path.exists(static_dir):
    # Mount assets directory
    assets_dir = os.path.join(static_dir, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    async def serve_root():
        """Serve the SPA root."""
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"error": "Frontend not built"}

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the SPA for all non-API routes."""
        # Don't serve index.html for API routes
        if full_path.startswith("api/"):
            return {"detail": "Not found"}
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"error": "Frontend not built"}
else:
    @app.get("/")
    async def no_frontend():
        """Fallback when frontend is not built."""
        return {"error": "Frontend not built", "static_dir_checked": static_dir}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
