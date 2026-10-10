from fastapi import APIRouter

from app.core.constants import DISCLAIMER

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "disclaimer": DISCLAIMER}
