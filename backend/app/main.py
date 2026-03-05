from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import internal, public
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.services.bootstrap import ensure_seed_data


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_seed_data(db)
    finally:
        db.close()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(public.router, prefix=settings.api_prefix)
app.include_router(internal.router, prefix=settings.api_prefix)
