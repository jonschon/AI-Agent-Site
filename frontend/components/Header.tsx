import Link from "next/link";

const categories = ["All", "Models", "Startups", "Agents", "Research", "Infrastructure"];

export function Header() {
  return (
    <header className="header">
      <div className="brand-row">
        <div className="logo">SignalWire AI News</div>
        <nav className="nav">
          <Link href="/">Home</Link>
          <Link href="/category/Models">Models</Link>
          <Link href="/category/Startups">Startups</Link>
          <Link href="/category/Agents">Agents</Link>
          <Link href="/category/Research">Research</Link>
          <Link href="/category/Infrastructure">Infrastructure</Link>
          <Link href="/search">Search</Link>
        </nav>
      </div>
      <div className="filters">
        {categories.map((category) => (
          <Link
            key={category}
            href={category === "All" ? "/" : `/category/${encodeURIComponent(category)}`}
          >
            {category}
          </Link>
        ))}
      </div>
    </header>
  );
}
