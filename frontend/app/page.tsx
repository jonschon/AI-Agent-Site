import { Header } from "@/components/Header";
import { FeedState } from "@/components/FeedState";
import { QuickUpdateRow } from "@/components/QuickUpdateRow";
import { SignalsRail } from "@/components/SignalsRail";
import { StoryCard } from "@/components/StoryCard";
import { fetchFeed, fetchNewsroomStats, fetchSignals } from "@/lib/api";

export default async function HomePage() {
  try {
    const [feed, signals, stats] = await Promise.all([fetchFeed(), fetchSignals(), fetchNewsroomStats()]);
    const hasStories =
      !!feed.lead_story || feed.major_stories.length > 0 || feed.quick_updates.length > 0;

    return (
      <>
        <Header />
        <main className="layout">
          <section>
            {!hasStories && (
              <FeedState
                title="No stories published yet"
                body="The agent pipeline has not published the first snapshot yet. Run an internal cycle and refresh."
              />
            )}
            {feed.lead_story && <StoryCard story={feed.lead_story} variant="lead" showTags={false} />}
            {feed.major_stories.map((story) => (
              <StoryCard key={story.id} story={story} variant="major" showTags={false} />
            ))}
            <section className="feed-card">
              <h3>Quick Updates</h3>
              {feed.quick_updates.length === 0 ? (
                <p className="meta-line">No quick updates in the latest publish cycle.</p>
              ) : (
                feed.quick_updates.map((story) => <QuickUpdateRow key={story.id} story={story} />)
              )}
            </section>
            <section className="feed-card sponsored-card">
              <h3>Sponsored Posts</h3>
              <p className="meta-line">Coming Soon</p>
            </section>
          </section>
          <SignalsRail signals={signals} stats={stats} />
        </main>
      </>
    );
  } catch {
    return (
      <>
        <Header />
        <FeedState
          title="Unable to load feed"
          body="The backend API is unavailable or misconfigured. Verify NEXT_PUBLIC_API_BASE and try again."
        />
      </>
    );
  }
}
