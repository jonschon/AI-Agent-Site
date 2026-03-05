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
        <div className="page-shell">{children}</div>
      </body>
    </html>
  );
}
