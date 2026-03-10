"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { NewsroomStats } from "@/types/news";

const categories = ["Top News", "Models", "Startups", "Agents", "Research", "Infrastructure"];
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/v1";

function formatLastRefreshed(raw: string | null): string {
  if (!raw) return "Pending";
  const dt = new Date(raw);
  if (Number.isNaN(dt.getTime())) return "Pending";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(dt);
}

export function Header() {
  const [lastRefreshed, setLastRefreshed] = useState<string>("Pending");

  useEffect(() => {
    let isMounted = true;
    const controller = new AbortController();
    async function loadStats() {
      try {
        const response = await fetch(`${API_BASE}/stats/newsroom`, {
          signal: controller.signal,
          cache: "no-store",
        });
        if (!response.ok) return;
        const stats = (await response.json()) as NewsroomStats;
        if (!isMounted) return;
        setLastRefreshed(formatLastRefreshed(stats.last_pull_time ?? stats.last_update_time));
      } catch {
        if (isMounted) {
          setLastRefreshed("Pending");
        }
      }
    }
    void loadStats();
    return () => {
      isMounted = false;
      controller.abort();
    };
  }, []);

  return (
    <>
      <header className="header">
        <div className="brand-row brand-row-static">
          <Link href="/" className="logo">
            SignalWire AI News
          </Link>
        </div>
      </header>
      <div className="sticky-nav-row">
        <div className="filters-wrap">
          <div className="filters">
            {categories.map((category) => (
              <Link
                key={category}
                href={category === "Top News" ? "/" : `/category/${encodeURIComponent(category)}`}
              >
                {category}
              </Link>
            ))}
          </div>
          <div className="last-refreshed" aria-live="polite">
            Last refreshed: {lastRefreshed}
          </div>
        </div>
        <nav className="nav">
          <Link href="/">Home</Link>
          <Link href="/about">About</Link>
          <Link href="/data-insights">Data Insights</Link>
        </nav>
      </div>
    </>
  );
}
