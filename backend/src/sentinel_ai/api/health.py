from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health() -> dict[str, str]:
    """Liveness check. Exposes no configuration or secrets."""
    return {"status": "ok"}
