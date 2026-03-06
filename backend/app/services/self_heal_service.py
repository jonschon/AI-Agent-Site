from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.news import ExceptionItem, ExceptionStatus


def auto_resolve_stale_low_exceptions(db: Session) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.self_heal_exception_stale_minutes)
    rows = db.execute(
        select(ExceptionItem).where(
            ExceptionItem.status == ExceptionStatus.open,
            ExceptionItem.severity != "high",
            ExceptionItem.created_at <= cutoff,
        )
    ).scalars().all()

    resolved = 0
    for exc in rows:
        payload = exc.payload_json or {}
        payload["auto_resolved"] = True
        payload["auto_resolved_reason"] = "stale_low_severity"
        payload["auto_resolved_at"] = datetime.now(timezone.utc).isoformat()
        exc.payload_json = payload
        exc.status = ExceptionStatus.resolved
        exc.resolved_at = datetime.now(timezone.utc)
        db.add(exc)
        resolved += 1

    if resolved > 0:
        db.commit()
    return resolved
