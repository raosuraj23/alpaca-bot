import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Resolve cross-origin webpack HMR blocks when testing via playwright or automated IP runners
  allowedDevOrigins: ['127.0.0.1'],
};

export default nextConfig;
