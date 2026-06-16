import type { MetadataRoute } from "next";

import { getSiteBaseUrl } from "@/lib/site-url";

const BASE_URL = getSiteBaseUrl();

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/login", "/signup", "/forgot-password"],
        disallow: [
          "/dashboard",
          "/projects",
          "/runs",
          "/rules",
          "/billing",
          "/security",
          "/admin",
          "/invite",
          "/reset-password",
          "/verify-email",
          "/api/",
        ],
      },
    ],
    sitemap: `${BASE_URL}/sitemap.xml`,
    host: BASE_URL,
  };
}
