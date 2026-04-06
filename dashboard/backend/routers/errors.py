"""
Frontend error logging endpoint.

Receives JavaScript error reports from the dashboard frontend
and logs them via structlog so they flow into BigQuery through
the existing log sink.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()


class FrontendErrorReport(BaseModel):
    """Schema for frontend error reports."""
    error: str = Field(..., description="Error message")
    stack: str = Field(..., description="Stack trace")
    url: str = Field(..., description="Page URL where the error occurred")
    timestamp: str = Field(..., description="ISO 8601 timestamp of the error")
    userAgent: str = Field(..., description="Browser user-agent string")
    component: Optional[str] = Field(None, description="React component name")


@router.post("")
async def report_frontend_error(body: FrontendErrorReport):
    """
    Log a frontend error report.

    The structured log entry flows to BigQuery via the existing
    Cloud Logging sink, tagged with event_category="frontend"
    so it can be queried separately from backend errors.
    """
    logger.error(
        "Frontend error reported",
        event_category="frontend",
        event_type="frontend_error",
        error=body.error,
        stack=body.stack[:500],
        url=body.url,
        component=body.component,
    )

    return {"status": "logged"}
