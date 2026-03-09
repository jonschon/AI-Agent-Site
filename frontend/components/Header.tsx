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
