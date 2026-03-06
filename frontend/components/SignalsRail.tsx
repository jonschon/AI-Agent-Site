import { NewsroomStats, SignalWidget } from "@/types/news";

export function SignalsRail({ signals, stats }: { signals: SignalWidget[]; stats: NewsroomStats }) {
  return (
    <aside className="rail">
      {signals.length === 0 ? (
        <section className="widget">
          <h4>Live Signals</h4>
          <div className="meta-line">Signal widgets will appear after the first publish cycle.</div>
        </section>
      ) : (
        signals.map((signal) => (
          <section key={`${signal.type}-${signal.observed_at}`} className="widget">
            <h4>{signal.title}</h4>
            <div className="meta-line">Items: {String(signal.data.items ?? "n/a")}</div>
          </section>
        ))
      )}
      <section className="widget">
        <h4>Agent Newsroom Stats</h4>
        <div className="meta-line">Articles processed: {stats.articles_processed}</div>
        <div className="meta-line">Stories detected: {stats.stories_detected}</div>
        <div className="meta-line">Last update: {stats.last_update_time ?? "n/a"}</div>
      </section>
    </aside>
  );
}
