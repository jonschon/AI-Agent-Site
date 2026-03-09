import Link from "next/link";

import { normalizeExternalUrl } from "@/lib/urls";
import { StoryCard as Story } from "@/types/news";

export function QuickUpdateRow({ story }: { story: Story }) {
  const topBullets = story.bullets.slice(0, 3).filter(Boolean);
  const overview =
    topBullets.length > 0
      ? topBullets.join(" ").slice(0, 360) + (topBullets.join(" ").length > 360 ? "..." : "")
      : "Coverage is evolving.";

  return (
    <div className="quick-item">
      <Link href={`/story/${story.slug}`} className="quick-title">
        {story.headline}
      </Link>
      <div className="quick-overview">{overview}</div>
      <div className="meta-line">
        {story.sources.slice(0, 3).map((source, index, list) => {
          const href = normalizeExternalUrl(source.url);
          return (
            <span key={`${source.source_name}-${source.url}`}>
              {href ? (
                <a href={href} target="_blank" rel="noreferrer noopener">
                  {source.source_name}
                </a>
              ) : (
                <span>{source.source_name}</span>
              )}
              {index < list.length - 1 ? " | " : ""}
            </span>
          );
        })}
      </div>
    </div>
  );
}
