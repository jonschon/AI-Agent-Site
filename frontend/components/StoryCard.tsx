import Link from "next/link";

import { StoryCard as Story } from "@/types/news";

type Props = {
  story: Story;
  variant: "lead" | "major";
};

export function StoryCard({ story, variant }: Props) {
  const bullets = [...story.bullets].slice(0, 3);

  return (
    <article className={`feed-card ${variant === "lead" ? "lead" : ""}`}>
      <div className="badges">
        {story.badges.map((badge) => (
          <span key={badge} className="badge">
            {badge}
          </span>
        ))}
      </div>
      <Link href={`/story/${story.slug}`} className="headline">
        {story.headline}
      </Link>
      <ul className="bullets">
        {bullets.map((bullet, index) => (
          <li key={`${story.id}-${index}`}>{bullet}</li>
        ))}
      </ul>
      <div className="meta-line">
        <strong>Sources</strong>{" "}
        <span className="meta-list">
          {story.sources.map((source) => (
            <a key={source.url} href={source.url} target="_blank" rel="noreferrer">
              {source.source_name}
            </a>
          ))}
        </span>
      </div>
      {story.discussions.length > 0 && (
        <div className="meta-line">
          <strong>Discussion</strong>{" "}
          <span className="meta-list">
            {story.discussions.map((discussion) => (
              <a key={discussion.url} href={discussion.url} target="_blank" rel="noreferrer">
                {discussion.platform}
              </a>
            ))}
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
