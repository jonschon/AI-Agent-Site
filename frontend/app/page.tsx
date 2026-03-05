import { Header } from "@/components/Header";
import { QuickUpdateRow } from "@/components/QuickUpdateRow";
import { SignalsRail } from "@/components/SignalsRail";
import { StoryCard } from "@/components/StoryCard";
import { fetchFeed, fetchNewsroomStats, fetchSignals } from "@/lib/api";

export default async function HomePage() {
  const [feed, signals, stats] = await Promise.all([fetchFeed(), fetchSignals(), fetchNewsroomStats()]);

  return (
    <>
      <Header />
      <main className="layout">
        <section>
          {feed.lead_story && <StoryCard story={feed.lead_story} variant="lead" />}
          {feed.major_stories.map((story) => (
            <StoryCard key={story.id} story={story} variant="major" />
          ))}
          <section className="feed-card">
            <h3>Quick Updates</h3>
            {feed.quick_updates.map((story) => (
              <QuickUpdateRow key={story.id} story={story} />
            ))}
          </section>
        </section>
        <SignalsRail signals={signals} stats={stats} />
      </main>
    </>
  );
}
