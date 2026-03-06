from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SourceLink(BaseModel):
    source_name: str
    url: str


class DiscussionLinkOut(BaseModel):
    platform: str
    url: str


class StoryCard(BaseModel):
    id: int
    slug: str
    headline: str
    bullets: list[str] = Field(min_length=3, max_length=3)
    tags: list[str]
    sources: list[SourceLink]
    discussions: list[DiscussionLinkOut]
    importance_score: float
    momentum_score: float
    tier: str
    badges: list[str]
    updated_at: datetime


class FeedResponse(BaseModel):
    published_at: datetime
    lead_story: Optional[StoryCard]
    major_stories: list[StoryCard]
    quick_updates: list[StoryCard]


class SectionBlock(BaseModel):
    name: str
    stories: list[StoryCard]


class SectionsResponse(BaseModel):
    sections: list[SectionBlock]


class StoryDetail(StoryCard):
    related_sources_count: int


class SignalWidget(BaseModel):
    type: str
    title: str
    data: dict
    observed_at: datetime


class NewsroomStats(BaseModel):
    articles_processed: int
    stories_detected: int
    last_update_time: Optional[datetime]


class AgentRunOut(BaseModel):
    id: int
    agent_name: str
    started_at: datetime
    ended_at: Optional[datetime]
    status: str
    metrics: dict
    error_text: Optional[str]


class ExceptionOut(BaseModel):
    id: int
    agent_name: str
    object_type: str
    object_id: str
    reason: str
    severity: str
    status: str
    created_at: datetime
    resolved_at: Optional[datetime]


class OpsQualityMetrics(BaseModel):
    generated_at: datetime
    publish_staleness_minutes: Optional[float]
    open_exceptions_total: int
    open_exceptions_high: int
    bullet_compliance_rate: float
    cluster_confidence_avg: float
    cluster_confidence_low_count: int
    merged_story_count_24h: int
    failed_agent_runs_24h: int
    active_story_count: int
    agent_last_run: dict


class OpsPolicyEvaluation(BaseModel):
    status: str
    blocking_reasons: list[str]
    metrics: OpsQualityMetrics


class AutonomousCycleResult(BaseModel):
    status: str
    action: str
    blocking_reasons: list[str]
    prepublish_metrics: OpsQualityMetrics
    pipeline_results: dict
