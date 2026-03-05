import { Header } from "@/components/Header";
import { StoryCard } from "@/components/StoryCard";
import { searchStories } from "@/lib/api";

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const params = await searchParams;
  const q = params.q ?? "agent";
  const results = await searchStories(q);

  return (
    <>
      <Header />
      <div className="feed-card">
        <h2>Search: {q}</h2>
      </div>
      {results.map((story) => (
        <StoryCard key={story.id} story={story} variant="major" />
      ))}
    </>
  );
}
