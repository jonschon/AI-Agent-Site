"use client";

import { Header } from "@/components/Header";
import { FeedState } from "@/components/FeedState";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <>
      <Header />
      <FeedState
        title="Feed temporarily unavailable"
        body="The app hit an unexpected issue while loading this page. Try again in a moment."
      />
      <div className="feed-card">
        <button className="retry-btn" onClick={reset} type="button">
          Retry
        </button>
      </div>
    </>
  );
}
