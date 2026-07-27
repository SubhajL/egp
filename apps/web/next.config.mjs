const nextConfig = {
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // Standalone output is explicit for the self-hosted Docker/start path.
  // Vercel's Next 16 adapter owns serverless output packaging.
  output:
    process.env.EGP_BUILD_STANDALONE === "true" ? "standalone" : undefined,
  outputFileTracingRoot: process.cwd(),
};

export default nextConfig;
