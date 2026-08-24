from fastapi import APIRouter
from pydantic import BaseModel

from ..core.settings import settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    version: str
    # Reported so a deployment can be checked against the estate it landed in.
    # The worst deployment failure is the one that put the right code in the
    # wrong environment, and that failure is invisible to a check that only
    # asks whether something answers.
    environment: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok", version="0.1.0", environment=settings.environment
    )
