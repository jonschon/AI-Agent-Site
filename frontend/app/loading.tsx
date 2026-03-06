import { Header } from "@/components/Header";

export default function Loading() {
  return (
    <>
      <Header />
      <main className="layout">
        <section>
          <section className="feed-card skeleton-card" />
          <section className="feed-card skeleton-card" />
          <section className="feed-card skeleton-card" />
        </section>
        <aside className="rail">
          <section className="widget skeleton-card" />
          <section className="widget skeleton-card" />
        </aside>
      </main>
    </>
  );
}
