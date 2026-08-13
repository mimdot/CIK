import type { NextConfig } from "next";

const isTauri = process.env.TAURI === "true";

const nextConfig: NextConfig = {
  output: isTauri ? "export" : "standalone",
  images: isTauri ? { unoptimized: true } : {},
};

export default nextConfig;
