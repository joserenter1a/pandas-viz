import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

const API_URL = process.env.PANDAS_VIZ_API_URL ?? "http://127.0.0.1:8000";

// Dev: proxy /api to FastAPI. Build: static export that FastAPI serves (web/out).
export default function config(phase: string): NextConfig {
  if (phase === PHASE_DEVELOPMENT_SERVER) {
    return {
      async rewrites() {
        return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
      },
    };
  }
  return { output: "export" };
}
