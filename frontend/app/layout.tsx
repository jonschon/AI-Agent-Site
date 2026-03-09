import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SignalWire AI News",
  description: "Techmeme-inspired AI ecosystem intelligence feed",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="page-shell">
          {children}
          <footer className="site-disclaimer">
            AI-generated news summaries may contain errors or hallucinations. Verify critical details with original
            sources.
          </footer>
        </div>
      </body>
    </html>
  );
}
