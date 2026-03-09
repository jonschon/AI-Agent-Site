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
    topic: "Foundation Models",
    metric: "GPQA accuracy (%)",
    signalType: "model_activity",
  },
  {
    topic: "Model Builders",
    metric: "Implied valuation (post-money)",
    signalType: "funding_tracker",
  },
  {
    topic: "Infrastructure Leaders",
    metric: "Announced AI compute capacity added (180d, H100-eq)",
    signalType: "trending_repos",
  },
];

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

const NON_ENTITY_KEYS = new Set([
  "items",
  "item",
  "count",
  "total",
  "value",
  "values",
  "score",
  "scores",
  "rank",
  "ranks",
  "type",
  "title",
  "observed_at",
  "updated_at",
  "generated_at",
  "window_days",
]);

function isEntityKey(key: string): boolean {
  const normalized = key.trim().toLowerCase();
  if (!normalized || NON_ENTITY_KEYS.has(normalized)) return false;
  return /[a-z]/i.test(normalized);
}

function toRankingRows(signal: SignalWidget, scoreSuffix?: string): RankingRow[] {
  const entries = Object.entries(signal.data)
    .filter(([key, value]) => isEntityKey(key) && (typeof value === "number" || typeof value === "string"))
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
  return [];
}

function buildRankings(signals: SignalWidget[], stats: NewsroomStats): RankingTable[] {
  const byType = new Map<string, SignalWidget>();
  for (const signal of signals) {
    const existing = byType.get(signal.type);
    if (!existing) {
      byType.set(signal.type, signal);
      continue;
    }
    const existingTs = Date.parse(existing.observed_at);
    const nextTs = Date.parse(signal.observed_at);
    const existingTime = Number.isFinite(existingTs) ? existingTs : 0;
    const nextTime = Number.isFinite(nextTs) ? nextTs : 0;
    if (nextTime >= existingTime) {
      byType.set(signal.type, signal);
    }
  }
  const updatedAt = stats.last_update_time ?? undefined;

  return RANKING_CONFIGS.map((config) => {
    const signal = config.signalType ? byType.get(config.signalType) : undefined;

    if (signal) {
      const suffix =
        config.topic === "Foundation Models" ? "%" : config.topic === "Model Builders" ? "B" : "";
      const formattedRows = toRankingRows(signal, suffix).map((row) => ({
        ...row,
        score: config.topic === "Model Builders" ? `$${row.score}` : row.score,
      }));
      return {
        topic: config.topic,
        metric: config.metric,
        updatedAt: signal.observed_at,
        rows:
          formattedRows.length > 0
            ? formattedRows
            : [{ rank: 1, label: "Insufficient public data", score: "n/a" }],
      };
    }

    return {
      topic: config.topic,
      metric: config.metric,
      updatedAt,
      rows: [{ rank: 1, label: "Insufficient public data", score: "n/a" }],
    };
  });
}

export function SignalsRail({ signals, stats }: { signals: SignalWidget[]; stats: NewsroomStats }) {
  const rankings = buildRankings(signals, stats);

  return (
    <aside className="rail" aria-label="Newsroom rankings">
      <section className="widget rankings-panel">
        <h4>AI Market Leaderboards</h4>
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
