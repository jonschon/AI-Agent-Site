from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.news import FeedResponse, NewsroomStats, SectionsResponse, SignalWidget, StoryCard, StoryDetail
from app.services.feed_service import (
    get_feed,
    get_sections,
    get_signals,
    get_story_detail,
    newsroom_stats,
    search_stories,
    list_stories,
)

router = APIRouter()


@router.get("/feed", response_model=FeedResponse)
def read_feed(db: Session = Depends(get_db)) -> FeedResponse:
    return get_feed(db)


@router.get("/feed/sections", response_model=SectionsResponse)
def read_sections(db: Session = Depends(get_db)) -> SectionsResponse:
    return get_sections(db)


@router.get("/stories/{slug}", response_model=StoryDetail)
def read_story(slug: str, db: Session = Depends(get_db)) -> StoryDetail:
    story = get_story_detail(db, slug)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    return story


@router.get("/stories", response_model=list[StoryCard])
def read_stories(
    category: Optional[str] = None,
    tag: Optional[str] = None,
    tier: Optional[str] = None,
    since: Optional[str] = None,
    cursor: Optional[str] = None,
    db: Session = Depends(get_db),
) -> list[StoryCard]:
    del since, cursor
    return list_stories(db, category=category, tag=tag, tier=tier)


@router.get("/signals", response_model=list[SignalWidget])
def read_signals(db: Session = Depends(get_db)) -> list[SignalWidget]:
    return get_signals(db)


@router.get("/search", response_model=list[StoryCard])
def search(q: str = Query(min_length=2), db: Session = Depends(get_db)) -> list[StoryCard]:
    return search_stories(db, q)


@router.get("/stats/newsroom", response_model=NewsroomStats)
def read_newsroom_stats(db: Session = Depends(get_db)) -> NewsroomStats:
    return newsroom_stats(db)


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}
