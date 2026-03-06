import { Header } from "@/components/Header";
import { FeedState } from "@/components/FeedState";
import { StoryCard } from "@/components/StoryCard";
import { searchStories } from "@/lib/api";

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const params = await searchParams;
  const q = params.q ?? "agent";

  try {
    const results = await searchStories(q);
    return (
      <>
        <Header />
        <div className="feed-card">
          <h2>Search: {q}</h2>
        </div>
        {results.length === 0 ? (
          <FeedState title="No matching stories" body="Try broader keywords or check back after the next cycle." compact />
        ) : (
          results.map((story) => <StoryCard key={story.id} story={story} variant="major" />)
        )}
      </>
    );
  } catch {
    return (
      <>
        <Header />
        <FeedState title="Search unavailable" body="Search endpoint is currently unreachable." />
      </>
    );
  }
}
