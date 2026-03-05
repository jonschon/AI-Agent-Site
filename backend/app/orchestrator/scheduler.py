from __future__ import annotations

import time

from app.agents.pipeline import run_pipeline
from app.core.config import settings
from app.db.session import SessionLocal


def run_once() -> dict:
    db = SessionLocal()
    try:
        return run_pipeline(db)
    finally:
        db.close()


def run_forever() -> None:
    interval = settings.publish_interval_minutes * 60
    while True:
        run_once()
        time.sleep(interval)


if __name__ == "__main__":
    run_forever()
