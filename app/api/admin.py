from fastapi import APIRouter, Depends

from app.deps import require_admin

router = APIRouter()


@router.get("/usage")
def admin_usage(admin=Depends(require_admin)):
    # Full implementation in Day 6
    return {"usage": []}


@router.get("/users")
def admin_users(admin=Depends(require_admin)):
    # Full implementation in Day 6
    return {"users": []}
