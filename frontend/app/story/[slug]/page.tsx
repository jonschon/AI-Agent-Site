import { Header } from "@/components/Header";
import { FeedState } from "@/components/FeedState";
import { StoryCard } from "@/components/StoryCard";
import { fetchStory } from "@/lib/api";

export default async function StoryPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;

  try {
    const story = await fetchStory(slug);
    return (
      <>
        <Header />
        <StoryCard story={story} variant={story.tier === "lead" ? "lead" : "major"} />
      </>
    );
  } catch {
    return (
      <>
        <Header />
        <FeedState title="Story unavailable" body="This story could not be loaded. It may have expired from active snapshots." />
      </>
    );
  }
}
