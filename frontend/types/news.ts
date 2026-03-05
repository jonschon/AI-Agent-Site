export type SourceLink = {
  source_name: string;
  url: string;
};

export type DiscussionLink = {
  platform: string;
  url: string;
};

export type StoryCard = {
  id: number;
  slug: string;
  headline: string;
  bullets: string[];
  tags: string[];
  sources: SourceLink[];
  discussions: DiscussionLink[];
  importance_score: number;
  momentum_score: number;
  tier: "lead" | "major" | "quick" | "archived";
  badges: string[];
  updated_at: string;
};

export type FeedResponse = {
  published_at: string;
  lead_story: StoryCard | null;
  major_stories: StoryCard[];
  quick_updates: StoryCard[];
};

export type SignalWidget = {
  type: string;
  title: string;
  data: Record<string, unknown>;
  observed_at: string;
};

export type NewsroomStats = {
  articles_processed: number;
  stories_detected: number;
  last_update_time: string | null;
};
