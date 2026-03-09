import Link from "next/link";

const categories = ["Top News", "Models", "Startups", "Agents", "Research", "Infrastructure"];

export function Header() {
  return (
    <header className="header">
      <div className="brand-row">
        <Link href="/" className="logo">
          SignalWire AI News
        </Link>
        <nav className="nav">
          <Link href="/">Home</Link>
          <Link href="/about">About</Link>
          <Link href="/category/Models">Models</Link>
          <Link href="/category/Startups">Startups</Link>
          <Link href="/category/Agents">Agents</Link>
          <Link href="/category/Research">Research</Link>
          <Link href="/category/Infrastructure">Infrastructure</Link>
        </nav>
      </div>
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
    </header>
  );
}
