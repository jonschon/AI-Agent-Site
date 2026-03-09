import Link from "next/link";

const categories = ["Top News", "Models", "Startups", "Agents", "Research", "Infrastructure"];

export function Header() {
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
        <nav className="nav">
          <Link href="/">Home</Link>
          <Link href="/about">About</Link>
          <Link href="/data-insights">Data Insights</Link>
        </nav>
      </div>
    </>
  );
}
