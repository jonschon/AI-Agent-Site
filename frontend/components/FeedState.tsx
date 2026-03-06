import Link from "next/link";

type FeedStateProps = {
  title: string;
  body: string;
  compact?: boolean;
};

export function FeedState({ title, body, compact = false }: FeedStateProps) {
  return (
    <section className={`feed-card ${compact ? "feed-state-compact" : ""}`}>
      <h3>{title}</h3>
      <p className="meta-line">{body}</p>
      {!compact && (
        <p className="meta-line">
          <Link href="/">Return to homepage</Link>
        </p>
      )}
    </section>
  );
}
