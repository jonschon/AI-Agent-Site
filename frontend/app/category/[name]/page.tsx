import { Header } from "@/components/Header";
import { StoryCard } from "@/components/StoryCard";
import { fetchStoriesByCategory } from "@/lib/api";

export default async function CategoryPage({ params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  const stories = await fetchStoriesByCategory(decodeURIComponent(name));

  return (
    <>
      <Header />
      <div className="feed-card">
        <h2>{decodeURIComponent(name)}</h2>
      </div>
      {stories.map((story) => (
        <StoryCard key={story.id} story={story} variant={story.tier === "lead" ? "lead" : "major"} />
      ))}
    </>
  );
}
