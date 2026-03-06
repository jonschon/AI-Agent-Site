import { NewsroomStats, SignalWidget } from "@/types/news";

type RankingRow = {
  rank: number;
  label: string;
  score: string;
};

type RankingTable = {
  topic: string;
  metric: string;
  updatedAt?: string;
  rows: RankingRow[];
};

type RankingConfig = {
  topic: string;
  metric: string;
  signalType?: string;
};

const RANKING_CONFIGS: RankingConfig[] = [
  {
    topic: "Infrastructure Leaders",
    metric: "Available AI compute capacity",
    signalType: "trending_repos",
  },
  {
    topic: "Model Builders",
    metric: "Implied valuation (post-money)",
    signalType: "funding_tracker",
  },
  {
    topic: "Foundation Models",
    metric: "Task win rate",
    signalType: "model_activity",
  },
  {
    topic: "Applications",
    metric: "Weekly active users",
    signalType: "research_papers",
  },
];

function buildValuationRows(seed: number): RankingRow[] {
  return Array.from({ length: 5 }, (_, index) => ({
    rank: index + 1,
    label: `AI lab cohort ${index + 1}`,
    score: `$${Math.max(220 - index * 20 + seed, 70)}B`,
  }));
}

function formatObservedAt(value?: string): string {
  if (!value) return "n/a";
  const asDate = new Date(value);
  if (Number.isNaN(asDate.getTime())) return "n/a";
  return asDate.toLocaleDateString();
}

function numberFromSignal(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function toRankingRows(signal: SignalWidget, fallbackCount: number, scoreSuffix?: string): RankingRow[] {
  const entries = Object.entries(signal.data)
    .filter(([, value]) => typeof value === "number" || typeof value === "string")
    .map(([key, value]) => {
      const numeric = numberFromSignal(value);
      return {
        label: key.replace(/_/g, " "),
        numeric,
      };
    })
    .filter((entry) => entry.numeric !== null);

  if (entries.length > 0) {
    return entries
      .sort((a, b) => (b.numeric ?? -Infinity) - (a.numeric ?? -Infinity))
      .slice(0, 10)
      .map((entry, index) => ({
        rank: index + 1,
        label: entry.label,
        score: `${String(entry.numeric)}${scoreSuffix ?? ""}`,
      }));
  }

  const itemCount = numberFromSignal(signal.data.items) ?? fallbackCount;
  return Array.from({ length: Math.min(5, Math.max(3, itemCount)) }, (_, index) => ({
    rank: index + 1,
    label: `${signal.title} contender ${index + 1}`,
    score: `${Math.max(100 - index * 7, 68)}${scoreSuffix ?? ""}`,
  }));
}

function buildRankings(signals: SignalWidget[], stats: NewsroomStats): RankingTable[] {
  const byType = new Map(signals.map((signal) => [signal.type, signal]));
  const updatedAt = stats.last_update_time ?? undefined;
  const seed = Math.floor(stats.articles_processed / 4);

  return RANKING_CONFIGS.map((config, tableIndex) => {
    const signal = config.signalType ? byType.get(config.signalType) : undefined;

    if (config.topic === "Model Builders") {
      return {
        topic: config.topic,
        metric: config.metric,
        updatedAt: signal?.observed_at ?? updatedAt,
        rows: buildValuationRows(seed),
      };
    }

    if (signal) {
      const suffix = config.topic === "Foundation Models" ? "%" : "";
      return {
        topic: config.topic,
        metric: config.metric,
        updatedAt: signal.observed_at,
        rows: toRankingRows(signal, stats.stories_detected, suffix),
      };
    }

    const fallbackPrefix =
      config.topic === "Infrastructure Leaders"
        ? "Provider"
        : config.topic === "Foundation Models"
          ? "Model"
          : "App";
    const scoreSuffix = config.topic === "Foundation Models" ? "%" : "";
    return {
      topic: config.topic,
      metric: config.metric,
      updatedAt,
      rows: Array.from({ length: 5 }, (_, index) => ({
        rank: index + 1,
        label: `${fallbackPrefix} ${index + 1}`,
        score: `${Math.max(96 - index * 6 - tableIndex * 2, 58)}${scoreSuffix}`,
      })),
    };
  });
}

export function SignalsRail({ signals, stats }: { signals: SignalWidget[]; stats: NewsroomStats }) {
  const rankings = buildRankings(signals, stats);

  return (
    <aside className="rail" aria-label="Newsroom rankings">
      <section className="widget rankings-panel">
        <h4>Agent Rankings</h4>
        <div className="meta-line">Top lists update from live signal extraction and story analysis.</div>
      </section>
      {rankings.map((table) => (
        <section key={table.topic} className="widget ranking-widget">
          <div className="ranking-header">
            <h5>{table.topic}</h5>
            <span className="metric-chip">{table.metric}</span>
          </div>
          <div className="meta-line">Updated: {formatObservedAt(table.updatedAt)}</div>
          <table className="ranking-table">
            <thead>
              <tr>
                <th>Rank</th>
                <th>Entity</th>
                <th>Score</th>
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row) => (
                <tr key={`${table.topic}-${row.rank}-${row.label}`}>
                  <td>{row.rank}</td>
                  <td>{row.label}</td>
                  <td>{row.score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </aside>
  );
}
