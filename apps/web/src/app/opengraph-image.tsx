import { ImageResponse } from "next/og";

export const runtime = "edge";

export const alt =
  "e-GP Intelligence Platform — ติดตามการประกวดราคาภาครัฐ อัตโนมัติ";

export const size = { width: 1200, height: 630 };

export const contentType = "image/png";

export default function OGImage() {
  return new ImageResponse(
    (
      <div
        style={{
          background: "linear-gradient(135deg, #0f0c29 0%, #302b63 55%, #24243e 100%)",
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "60px",
          fontFamily: "sans-serif",
        }}
      >
        {/* Grid overlay */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            opacity: 0.04,
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.5) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.5) 1px, transparent 1px)",
            backgroundSize: "40px 40px",
          }}
        />

        {/* Logo mark */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            width: 72,
            height: 72,
            borderRadius: 16,
            background: "#4F46E5",
            marginBottom: 28,
          }}
        >
          {/* Bar chart icon */}
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none">
            <path
              d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
              stroke="white"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>

        {/* Product name */}
        <div
          style={{
            color: "white",
            fontSize: 52,
            fontWeight: 800,
            textAlign: "center",
            lineHeight: 1.15,
            marginBottom: 16,
            letterSpacing: "-0.02em",
          }}
        >
          e-GP Intelligence Platform
        </div>

        {/* Thai tagline */}
        <div
          style={{
            color: "#a5b4fc",
            fontSize: 26,
            textAlign: "center",
            maxWidth: 800,
            marginBottom: 40,
          }}
        >
          ติดตามการประกวดราคาภาครัฐ อัตโนมัติ
        </div>

        {/* Stats pills */}
        <div style={{ display: "flex", gap: 20 }}>
          {["10,000+ โครงการ", "24/7 ทำงาน", "< 1 นาที แจ้งเตือน"].map((stat) => (
            <div
              key={stat}
              style={{
                background: "rgba(99,102,241,0.25)",
                border: "1px solid rgba(165,180,252,0.35)",
                borderRadius: 100,
                padding: "10px 24px",
                color: "#c7d2fe",
                fontSize: 17,
                fontWeight: 600,
              }}
            >
              {stat}
            </div>
          ))}
        </div>

        {/* Source tag */}
        <div
          style={{
            position: "absolute",
            bottom: 32,
            color: "rgba(165,180,252,0.4)",
            fontSize: 14,
          }}
        >
          ข้อมูลจาก gprocurement.go.th · กรมบัญชีกลาง
        </div>
      </div>
    ),
    { ...size },
  );
}
