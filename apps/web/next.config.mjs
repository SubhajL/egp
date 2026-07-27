const nextConfig = {
  distDir: process.env.NEXT_DIST_DIR || ".next",
  output: "standalone",
  outputFileTracingRoot: process.cwd(),
};

export default nextConfig;
