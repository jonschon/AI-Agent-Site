import Link from "next/link";

import { StoryCard as Story } from "@/types/news";

type Props = {
  story: Story;
  variant: "lead" | "major";
};

export function StoryCard({ story, variant }: Props) {
  const bullets = [...story.bullets].slice(0, 3);
  const normalizeExternalUrl = (raw: string): string | null => {
    const trimmed = raw.trim();
    if (!trimmed) return null;
    if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) return trimmed;
    if (trimmed.startsWith("//")) return `https:${trimmed}`;
    return `https://${trimmed}`;
  };

  return (
    <article className={`feed-card ${variant === "lead" ? "lead" : ""}`}>
      <div className="badges">
        {story.badges.map((badge) => (
          <span key={badge} className="badge">
            {badge}
          </span>
        ))}
      </div>
      <Link href={`/story/${story.slug}`} className="story-link-area">
        <div className="headline">{story.headline}</div>
        <ul className="bullets">
          {bullets.map((bullet, index) => (
            <li key={`${story.id}-${index}`}>{bullet}</li>
          ))}
        </ul>
      </Link>
      <div className="meta-line">
        <strong>Sources</strong>{" "}
        <span className="meta-list">
          {story.sources.map((source) => {
            const href = normalizeExternalUrl(source.url);
            if (!href) return <span key={`${source.source_name}-${source.url}`}>{source.source_name}</span>;
            return (
              <a key={source.url} href={href} target="_blank" rel="noreferrer noopener">
                {source.source_name}
              </a>
            );
          })}
        </span>
      </div>
      {story.discussions.length > 0 && (
        <div className="meta-line">
          <strong>Discussion</strong>{" "}
          <span className="meta-list">
            {story.discussions.map((discussion) => {
              const href = normalizeExternalUrl(discussion.url);
              if (!href) return <span key={`${discussion.platform}-${discussion.url}`}>{discussion.platform}</span>;
              return (
                <a key={discussion.url} href={href} target="_blank" rel="noreferrer noopener">
                  {discussion.platform}
                </a>
              );
            })}
          </span>
        </div>
      )}
      <div className="meta-line">
        <strong>Tags</strong>{" "}
        <span className="meta-list">
          {story.tags.map((tag) => (
            <span key={tag} className="tag">
              {tag}
            </span>
          ))}
        </span>
      </div>
    </article>
  );
}
