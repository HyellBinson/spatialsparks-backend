from fastapi import APIRouter
from datetime import datetime, timezone

router = APIRouter()


@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "application": "SpatialSparks",
        "message": "SpatialSparks backend is operational",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }