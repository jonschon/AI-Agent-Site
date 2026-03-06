from __future__ import annotations

from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.news import AgentMemory


def get_memory(db: Session, key: str) -> Optional[AgentMemory]:
    return db.execute(select(AgentMemory).where(AgentMemory.key == key)).scalar_one_or_none()


def set_memory(db: Session, key: str, value: dict) -> AgentMemory:
    row = get_memory(db, key)
    if not row:
        row = AgentMemory(key=key, value_json=value)
    else:
        row.value_json = value
    db.add(row)
    db.flush()
    return row


def get_float_control(db: Session, key: str, default: float) -> float:
    row = get_memory(db, key)
    if not row:
        return default
    value = (row.value_json or {}).get("value")
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_text_control(db: Session, key: str, default: str) -> str:
    row = get_memory(db, key)
    if not row:
        return default
    value = (row.value_json or {}).get("value")
    return value if isinstance(value, str) and value else default


def list_memory(db: Session, prefix: Optional[str] = None) -> list[AgentMemory]:
    stmt = select(AgentMemory).order_by(desc(AgentMemory.updated_at))
    if prefix:
        stmt = stmt.where(AgentMemory.key.ilike(f"{prefix}%"))
    return db.execute(stmt).scalars().all()
