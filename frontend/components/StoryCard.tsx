import Link from "next/link";

import { normalizeExternalUrl } from "@/lib/urls";
import { StoryCard as Story } from "@/types/news";

type Props = {
  story: Story;
  variant: "lead" | "major";
};

function normalizeForCompare(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9\s]/g, " ").replace(/\s+/g, " ").trim();
}

function nearDuplicate(a: string, b: string): boolean {
  const na = normalizeForCompare(a);
  const nb = normalizeForCompare(b);
  if (!na || !nb) return false;
  if (na.includes(nb) || nb.includes(na)) return true;
  const aWords = new Set(na.split(" "));
  const bWords = new Set(nb.split(" "));
  const intersection = [...aWords].filter((word) => bWords.has(word)).length;
  const overlap = intersection / Math.max(aWords.size, bWords.size, 1);
  return overlap >= 0.8;
}

export function StoryCard({ story, variant }: Props) {
  const filteredBullets = [...story.bullets].filter((bullet) => {
    const cleaned = bullet.trim();
    if (!cleaned) return false;
    return !nearDuplicate(cleaned, story.headline);
  });
  const storyBullets = filteredBullets.length > 0 ? filteredBullets : [...story.bullets].filter(Boolean);
  const deckBulletCount = storyBullets.length > 1 ? 1 : 0;
  const deckSource = deckBulletCount > 0 ? storyBullets.slice(0, deckBulletCount).join(" ") : "";
  const bulletCandidates =
    deckBulletCount > 0 ? storyBullets.slice(deckBulletCount) : [...storyBullets];
  const bullets = bulletCandidates.slice(0, variant === "lead" ? 5 : 4);
  const deckLimit = variant === "lead" ? 460 : 320;
  const deck =
    deckSource.length > 0
      ? deckSource.slice(0, deckLimit) + (deckSource.length > deckLimit ? "..." : "")
      : null;
  const imageHref = normalizeExternalUrl(story.image_url || "");
  const imageSourceHref = normalizeExternalUrl(story.image_source?.url || "");
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
          <div className="story-image-wrap">
            <Link href={`/story/${story.slug}`} className="story-image-link" aria-label={`${story.headline} image`}>
              <img src={imageHref} alt={story.headline} className="story-image" loading="lazy" />
            </Link>
            {story.image_source && (
              <div className="story-image-credit">
                Image source:{" "}
                {imageSourceHref ? (
                  <a href={imageSourceHref} target="_blank" rel="noreferrer noopener">
                    {story.image_source.source_name}
                  </a>
                ) : (
                  story.image_source.source_name
                )}
              </div>
            )}
          </div>
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
