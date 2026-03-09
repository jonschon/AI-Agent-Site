import { NewsroomStats, SignalWidget } from "@/types/news";

type RankingRow = {
  rank: number;
  label: string;
  score: string;
  confidence?: string;
  sourceCount?: number;
};

type RankingTable = {
  topic: string;
  metric: string;
  scoreLabel: string;
  updatedAt?: string;
  rows: RankingRow[];
};

type RankingConfig = {
  topic: string;
  metric: string;
  scoreLabel: string;
  scoreSuffix?: string;
  scorePrefix?: string;
  signalType?: string;
};

const RANKING_CONFIGS: RankingConfig[] = [
  {
    topic: "Monthly Active Users",
    metric: "Reported or inferred monthly active users",
    scoreLabel: "MAU (M)",
    scoreSuffix: "M",
    signalType: "app_adoption",
  },
  {
    topic: "Foundation Models",
    metric: "GPQA accuracy (%)",
    scoreLabel: "GPQA (%)",
    scoreSuffix: "%",
    signalType: "model_activity",
  },
  {
    topic: "Model Builders",
    metric: "Implied valuation (post-money)",
    scoreLabel: "Valuation",
    scoreSuffix: "B",
    scorePrefix: "$",
    signalType: "funding_tracker",
  },
  {
    topic: "Infrastructure Leaders",
    metric: "Estimated total installed AI compute capacity (H100-eq)",
    scoreLabel: "Total Capacity",
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

function toRankingRows(signal: SignalWidget, scoreSuffix?: string, scorePrefix?: string): RankingRow[] {
  const structuredRows = signal.data["rows"];
  if (Array.isArray(structuredRows)) {
    type ParsedStructuredRow = {
      label: string;
      numeric: number;
      confidence: string | undefined;
      sourceCount: number;
    };
    const parsed = structuredRows
      .map((item) => {
        if (!item || typeof item !== "object") return null;
        const row = item as Record<string, unknown>;
        const labelRaw = row["entity"];
        const valueRaw = row["value"];
        const confidenceRaw = row["confidence"];
        const sourceCountRaw = row["source_count"];
        if (typeof labelRaw !== "string") return null;
        const numeric = numberFromSignal(valueRaw);
        if (numeric === null) return null;
        return {
          label: labelRaw,
          numeric,
          confidence: typeof confidenceRaw === "string" ? confidenceRaw : undefined,
          sourceCount: typeof sourceCountRaw === "number" && Number.isFinite(sourceCountRaw) ? sourceCountRaw : 0,
        };
      })
      .filter((entry): entry is ParsedStructuredRow => !!entry);

    if (parsed.length > 0) {
      return parsed
        .sort((a, b) => b.numeric - a.numeric)
        .slice(0, 10)
        .map((entry, index) => ({
          rank: index + 1,
          label: entry.label,
          score: `${scorePrefix ?? ""}${String(entry.numeric)}${scoreSuffix ?? ""}`,
          confidence: entry.confidence,
          sourceCount: entry.sourceCount,
        }));
    }
  }

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
        score: `${scorePrefix ?? ""}${String(entry.numeric)}${scoreSuffix ?? ""}`,
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
      const formattedRows = toRankingRows(signal, config.scoreSuffix, config.scorePrefix);
      return {
        topic: config.topic,
        metric: config.metric,
        scoreLabel: config.scoreLabel,
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
      scoreLabel: config.scoreLabel,
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
                <th>{table.scoreLabel}</th>
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row) => (
                <tr key={`${table.topic}-${row.rank}-${row.label}`}>
                  <td>{row.rank}</td>
                  <td>
                    <div>{row.label}</div>
                    {row.confidence && (row.sourceCount ?? 0) > 0 ? (
                      <div className="ranking-submeta">
                        {row.confidence}, {row.sourceCount ?? 0} sources
                      </div>
                    ) : null}
                  </td>
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
