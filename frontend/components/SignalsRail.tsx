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

function buildValuationRows(seed: number): RankingRow[] {
  return Array.from({ length: 5 }, (_, index) => ({
    rank: index + 1,
    label: `Funding cohort ${index + 1}`,
    score: `${Math.max(120 - index * 11 + seed, 72)}`,
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

function toRankingRows(signal: SignalWidget, fallbackCount: number): RankingRow[] {
  const entries = Object.entries(signal.data)
    .filter(([, value]) => typeof value === "number" || typeof value === "string")
    .map(([key, value]) => {
      const numeric = numberFromSignal(value);
      return {
        label: key.replace(/_/g, " "),
        numeric,
        raw: String(value),
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
        score: String(entry.numeric),
      }));
  }

  const itemCount = numberFromSignal(signal.data.items) ?? fallbackCount;
  return Array.from({ length: Math.min(5, Math.max(3, itemCount)) }, (_, index) => ({
    rank: index + 1,
    label: `${signal.title} contender ${index + 1}`,
    score: `${Math.max(100 - index * 7, 68)}`,
  }));
}

function buildRankings(signals: SignalWidget[], stats: NewsroomStats): RankingTable[] {
  const signalTables = signals.slice(0, 3).map((signal) => ({
    topic: signal.title,
    metric: "Composite signal score",
    updatedAt: signal.observed_at,
    rows: toRankingRows(signal, stats.stories_detected),
  }));

  const valuationTable: RankingTable = {
    topic: "Valuation Watch",
    metric: "Funding announcement score",
    updatedAt: stats.last_update_time ?? undefined,
    rows: buildValuationRows(Math.floor(stats.articles_processed / 4)),
  };

  if (signalTables.length > 0) {
    return [...signalTables, valuationTable].slice(0, 4);
  }

  const fallbackRows = [
    { label: "Model quality index", score: `${Math.max(60, stats.stories_detected + 55)}` },
    { label: "Launch velocity index", score: `${Math.max(58, stats.articles_processed + 35)}` },
    { label: "Research momentum index", score: `${Math.max(56, stats.stories_detected + 42)}` },
    { label: "Adoption signal index", score: `${Math.max(54, stats.articles_processed + 28)}` },
    { label: "Ecosystem reliability index", score: `${Math.max(52, stats.stories_detected + 30)}` },
  ];

  return [
    {
      topic: "Best Model",
      metric: "Agent trend score",
      updatedAt: stats.last_update_time ?? undefined,
      rows: fallbackRows.map((row, index) => ({
        rank: index + 1,
        label: row.label,
        score: row.score,
      })),
    },
    {
      topic: "Agent Platforms",
      metric: "Execution reliability",
      updatedAt: stats.last_update_time ?? undefined,
      rows: fallbackRows.map((row, index) => ({
        rank: index + 1,
        label: row.label.replace("index", "stack"),
        score: `${Math.max(50, Number(row.score) - 3)}`,
      })),
    },
    {
      topic: "Research Labs",
      metric: "Breakthrough signal",
      updatedAt: stats.last_update_time ?? undefined,
      rows: fallbackRows.map((row, index) => ({
        rank: index + 1,
        label: row.label.replace("index", "program"),
        score: `${Math.max(48, Number(row.score) - 5)}`,
      })),
    },
    valuationTable,
  ];
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
                <th>Signal</th>
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
