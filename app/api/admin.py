import json
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app.deps import get_db, require_admin
from app.models.db import Job, QueryHistory, UsageLog, User

router = APIRouter()


@router.get("/usage")
def admin_usage(
    days: int = Query(default=7),
    user_id: Optional[uuid.UUID] = Query(default=None),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(days=days)
    stmt = select(UsageLog).where(UsageLog.created_at >= since)
    if user_id:
        stmt = stmt.where(UsageLog.user_id == user_id)
    logs = db.exec(stmt).all()

    total_tokens = sum(l.total_tokens for l in logs)
    total_cost_estimate = round(total_tokens * 0.001 / 1000, 6)

    by_day_map: dict = {}
    for l in logs:
        d = l.created_at.date().isoformat()
        e = by_day_map.setdefault(d, {"date": d, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "latency_sum": 0, "count": 0})
        e["prompt_tokens"] += l.prompt_tokens
        e["completion_tokens"] += l.completion_tokens
        e["total_tokens"] += l.total_tokens
        e["latency_sum"] += l.latency_ms
        e["count"] += 1
    by_day = [
        {"date": v["date"], "prompt_tokens": v["prompt_tokens"], "completion_tokens": v["completion_tokens"],
         "total_tokens": v["total_tokens"], "avg_latency_ms": int(v["latency_sum"] / v["count"]) if v["count"] else 0}
        for v in sorted(by_day_map.values(), key=lambda x: x["date"])
    ]

    by_ep_map: dict = {}
    for l in logs:
        e = by_ep_map.setdefault(l.endpoint, {"endpoint": l.endpoint, "calls": 0, "total_tokens": 0, "latency_sum": 0})
        e["calls"] += 1
        e["total_tokens"] += l.total_tokens
        e["latency_sum"] += l.latency_ms
    by_endpoint = [
        {"endpoint": v["endpoint"], "calls": v["calls"], "total_tokens": v["total_tokens"],
         "avg_latency_ms": int(v["latency_sum"] / v["calls"]) if v["calls"] else 0}
        for v in by_ep_map.values()
    ]

    by_user_map: dict = {}
    for l in logs:
        if not l.user_id:
            continue
        uid = str(l.user_id)
        e = by_user_map.setdefault(uid, {"user_id": uid, "email": None, "calls": 0, "total_tokens": 0})
        e["calls"] += 1
        e["total_tokens"] += l.total_tokens
    for uid, entry in by_user_map.items():
        u = db.get(User, uuid.UUID(uid))
        if u:
            entry["email"] = u.email

    # today summary for dashboard cards
    today_str = datetime.utcnow().date().isoformat()
    today_logs = [l for l in logs if l.created_at.date().isoformat() == today_str]
    today_tokens = sum(l.total_tokens for l in today_logs)
    avg_latency_ms = round(sum(l.latency_ms for l in logs) / len(logs), 1) if logs else 0

    return {
        "total_tokens": total_tokens,
        "today_tokens": today_tokens,
        "total_calls": len(logs),
        "avg_latency_ms": avg_latency_ms,
        "total_cost_estimate": total_cost_estimate,
        "daily": by_day,
        "by_day": by_day,
        "by_endpoint": by_endpoint,
        "by_user": list(by_user_map.values()),
    }


@router.get("/ragas")
def admin_ragas(
    days: int = Query(default=7),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(days=days)
    queries = db.exec(
        select(QueryHistory).where(
            QueryHistory.created_at >= since,
            QueryHistory.ragas_scores.is_not(None),
        )
    ).all()

    metric_keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall", "answer_correctness"]
    sums: dict = {k: 0.0 for k in metric_keys}
    counts: dict = {k: 0 for k in metric_keys}
    low_scoring = []
    by_day_map: dict = {}

    for q in queries:
        try:
            scores = json.loads(q.ragas_scores)
        except Exception:
            continue
        for k in metric_keys:
            if k in scores and isinstance(scores[k], (int, float)):
                sums[k] += scores[k]
                counts[k] += 1
        d = q.created_at.date().isoformat()
        day_entry = by_day_map.setdefault(d, {"date": d, **{k: [] for k in metric_keys[:4]}})
        for k in metric_keys[:4]:
            if k in scores and isinstance(scores[k], (int, float)):
                day_entry[k].append(scores[k])
        faith = scores.get("faithfulness", 1.0)
        rel = scores.get("answer_relevancy", 1.0)
        if faith < 0.8 or rel < 0.7:
            low_scoring.append({
                "query_id": str(q.id),
                "question": q.question,
                "answer": q.answer[:200],
                "faithfulness": faith,
                "answer_relevancy": rel,
                "created_at": q.created_at.isoformat(),
            })

    avg_scores = {k: round(sums[k] / counts[k], 4) if counts[k] else None for k in metric_keys}
    by_day = [
        {"date": v["date"], **{k: round(sum(v[k]) / len(v[k]), 4) if v[k] else None for k in metric_keys[:4]}}
        for v in sorted(by_day_map.values(), key=lambda x: x["date"])
    ]

    return {"averages": avg_scores, "avg_scores": avg_scores, "by_day": by_day, "low_scoring": low_scoring}


@router.get("/users")
def admin_users(
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = db.exec(select(User)).all()
    result = []
    for u in users:
        total_queries = db.exec(select(func.count(QueryHistory.id)).where(QueryHistory.user_id == u.id)).one()
        total_tokens_val = db.exec(select(func.sum(UsageLog.total_tokens)).where(UsageLog.user_id == u.id)).one()
        total_jobs = db.exec(select(func.count(Job.id)).where(Job.user_id == u.id)).one()
        result.append({
            "id": str(u.id),
            "email": u.email,
            "role": u.role.value,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat(),
            "last_active_at": u.last_active_at.isoformat() if u.last_active_at else None,
            "total_queries": total_queries or 0,
            "total_tokens": total_tokens_val or 0,
            "total_jobs": total_jobs or 0,
        })
    return result


@router.get("/logs")
def admin_logs(
    job_id: Optional[uuid.UUID] = Query(default=None),
    user_id: Optional[uuid.UUID] = Query(default=None),
    error_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(UsageLog).order_by(UsageLog.created_at.desc()).offset(offset).limit(limit)
    if job_id:
        stmt = stmt.where(UsageLog.job_id == job_id)
    if user_id:
        stmt = stmt.where(UsageLog.user_id == user_id)
    logs = db.exec(stmt).all()
    return [
        {
            "id": str(l.id),
            "user_id": str(l.user_id) if l.user_id else None,
            "job_id": str(l.job_id) if l.job_id else None,
            "endpoint": l.endpoint,
            "model": l.model,
            "total_tokens": l.total_tokens,
            "latency_ms": l.latency_ms,
            "created_at": l.created_at.isoformat(),
        }
        for l in logs
    ]


class PatchUserRequest(BaseModel):
    is_active: bool


@router.patch("/users/{user_id}")
def patch_user(
    user_id: uuid.UUID,
    req: PatchUserRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Admin cannot deactivate their own account")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = req.is_active
    db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role.value,
        "is_active": user.is_active,
    }
