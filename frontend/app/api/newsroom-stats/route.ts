import { NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/v1";

export async function GET() {
  try {
    const response = await fetch(`${API_BASE}/stats/newsroom`, {
      next: { revalidate: 30 },
    });
    if (!response.ok) {
      return NextResponse.json(
        { error: `Upstream newsroom stats request failed: ${response.status}` },
        { status: 502 },
      );
    }
    const payload = await response.json();
    return NextResponse.json(payload);
  } catch {
    return NextResponse.json({ error: "Unable to load newsroom stats" }, { status: 502 });
  }
}
