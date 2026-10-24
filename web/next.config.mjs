/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Browser calls to /api/* go through app/api/[...path]/route.ts, which adds the
  // signed session token the FastAPI backend expects.
};

export default nextConfig;
