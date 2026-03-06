import { Header } from "@/components/Header";
import { FeedState } from "@/components/FeedState";
import { StoryCard } from "@/components/StoryCard";
import { fetchStoriesByCategory } from "@/lib/api";

export default async function CategoryPage({ params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  const category = decodeURIComponent(name);

  try {
    const stories = await fetchStoriesByCategory(category);
    return (
      <>
        <Header />
        <div className="feed-card">
          <h2>{category}</h2>
        </div>
        {stories.length === 0 ? (
          <FeedState title="No stories in this category" body="Category pages fill as tags are extracted from published stories." compact />
        ) : (
          stories.map((story) => (
            <StoryCard key={story.id} story={story} variant={story.tier === "lead" ? "lead" : "major"} />
          ))
        )}
      </>
    );
  } catch {
    return (
      <>
        <Header />
        <FeedState title="Category unavailable" body="Could not load category stories from the API." />
      </>
    );
  }
}
