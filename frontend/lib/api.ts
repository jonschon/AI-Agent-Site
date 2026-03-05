import { FeedResponse, NewsroomStats, SignalWidget, StoryCard } from "@/types/news";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/v1";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { next: { revalidate: 60 } });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchFeed(): Promise<FeedResponse> {
  return getJson<FeedResponse>("/feed");
}

export function fetchSignals(): Promise<SignalWidget[]> {
  return getJson<SignalWidget[]>("/signals");
}

export function fetchNewsroomStats(): Promise<NewsroomStats> {
  return getJson<NewsroomStats>("/stats/newsroom");
}

export function fetchStory(slug: string): Promise<StoryCard & { related_sources_count: number }> {
  return getJson<StoryCard & { related_sources_count: number }>(`/stories/${slug}`);
}

export function fetchStoriesByCategory(category: string): Promise<StoryCard[]> {
  return getJson<StoryCard[]>(`/stories?category=${encodeURIComponent(category)}`);
}

export function searchStories(q: string): Promise<StoryCard[]> {
  return getJson<StoryCard[]>(`/search?q=${encodeURIComponent(q)}`);
}
