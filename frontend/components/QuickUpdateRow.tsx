import Link from "next/link";

import { StoryCard as Story } from "@/types/news";

export function QuickUpdateRow({ story }: { story: Story }) {
  return (
    <div className="quick-item">
      <Link href={`/story/${story.slug}`}>{story.headline}</Link>
      <div className="meta-line">
        {story.sources.slice(0, 3).map((source) => source.source_name).join(" | ")}
      </div>
    </div>
  );
}
