import Link from "next/link";

import { normalizeExternalUrl } from "@/lib/urls";
import { StoryCard as Story } from "@/types/news";

type Props = {
  story: Story;
  variant: "lead" | "major";
};

export function StoryCard({ story, variant }: Props) {
  const storyBullets = [...story.bullets].filter(Boolean);
  const bullets = storyBullets.slice(0, variant === "lead" ? 5 : 4);
  const deckSource = storyBullets.slice(0, variant === "lead" ? 3 : 2).join(" ");
  const deckLimit = variant === "lead" ? 460 : 320;
  const deck =
    deckSource.length > 0
      ? deckSource.slice(0, deckLimit) + (deckSource.length > deckLimit ? "..." : "")
      : null;
  const imageHref = normalizeExternalUrl(story.image_url || "");
  const showTopImage = (variant === "lead" || variant === "major") && !!imageHref;
  return (
    <article className={`feed-card ${variant === "lead" ? "lead" : "major"}`}>
      <div className="badges">
        {story.badges.map((badge) => (
          <span key={badge} className="badge">
            {badge}
          </span>
        ))}
      </div>
      <div className={`story-main ${showTopImage ? "with-image" : ""}`}>
        <Link href={`/story/${story.slug}`} className="story-link-area">
          <div className="headline">{story.headline}</div>
          {deck && <p className="story-deck">{deck}</p>}
          <ul className="bullets">
            {bullets.map((bullet, index) => (
              <li key={`${story.id}-${index}`}>{bullet}</li>
            ))}
          </ul>
        </Link>
        {showTopImage && imageHref && (
          <Link href={`/story/${story.slug}`} className="story-image-wrap" aria-label={`${story.headline} image`}>
            <img src={imageHref} alt={story.headline} className="story-image" loading="lazy" />
          </Link>
        )}
      </div>
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
