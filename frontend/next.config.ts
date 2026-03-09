import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async headers() {
    const noStore = [{ key: "Cache-Control", value: "no-store, max-age=0, must-revalidate" }];
    return [
      { source: "/", headers: noStore },
      { source: "/about", headers: noStore },
      { source: "/data-insights", headers: noStore },
      { source: "/search", headers: noStore },
      { source: "/story/:path*", headers: noStore },
      { source: "/category/:path*", headers: noStore },
    ];
  },
};

export default nextConfig;
