"use client";

import type { CSSProperties } from "react";
import { useEffect, useState } from "react";

import { fetchProjects, getApiBaseUrl, getTenantId, type ProjectSummary } from "@/lib/api";

const shellStyle: CSSProperties = {
  minHeight: "100vh",
  padding: "48px 20px 72px",
};

const frameStyle: CSSProperties = {
  maxWidth: 1120,
  margin: "0 auto",
  display: "grid",
  gap: 24,
};

const heroStyle: CSSProperties = {
  padding: "32px 36px",
  border: "1px solid var(--border)",
  borderRadius: 28,
  background: "var(--surface-strong)",
  boxShadow: "0 24px 70px rgba(48, 32, 16, 0.08)",
};

const cardStyle: CSSProperties = {
  border: "1px solid var(--border)",
  borderRadius: 24,
  background: "var(--surface)",
  backdropFilter: "blur(10px)",
  boxShadow: "0 18px 42px rgba(48, 32, 16, 0.06)",
};

const badgeStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  borderRadius: 999,
  padding: "6px 12px",
  fontSize: 12,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  background: "var(--accent-soft)",
  color: "var(--accent)",
};

function formatBudget(value: string | null): string {
  if (!value) {
    return "Budget unknown";
  }
  const amount = Number(value);
  if (!Number.isFinite(amount)) {
    return value;
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "THB",
    maximumFractionDigits: 0,
  }).format(amount);
}

function formatDate(value: string | null): string {
  if (!value) {
    return "Date unknown";
  }
  return new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}

function ProjectCard({ project }: { project: ProjectSummary }) {
  return (
    <article
      style={{
        ...cardStyle,
        padding: "22px 24px",
        display: "grid",
        gap: 14,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 16,
          alignItems: "flex-start",
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "grid", gap: 8 }}>
          <span style={badgeStyle}>{project.project_state.replaceAll("_", " ")}</span>
          <h2 style={{ margin: 0, fontSize: 28, lineHeight: 1.15 }}>{project.project_name}</h2>
          <p style={{ margin: 0, color: "var(--muted)", fontSize: 16 }}>
            {project.organization_name || "Unknown organization"}
          </p>
        </div>
        <div style={{ textAlign: "right", color: "var(--muted)", minWidth: 180 }}>
          <div>{project.project_number ?? "No project number yet"}</div>
          <div>{formatBudget(project.budget_amount)}</div>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 12,
          color: "var(--muted)",
          fontSize: 14,
        }}
      >
        <div>
          <strong style={{ display: "block", color: "var(--text)" }}>Submission</strong>
          {formatDate(project.proposal_submission_date)}
        </div>
        <div>
          <strong style={{ display: "block", color: "var(--text)" }}>Procurement</strong>
          {project.procurement_type}
        </div>
        <div>
          <strong style={{ display: "block", color: "var(--text)" }}>Source Status</strong>
          {project.source_status_text ?? "No status text"}
        </div>
      </div>
    </article>
  );
}

export function ProjectList() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const payload = await fetchProjects();
        if (!cancelled) {
          setProjects(payload);
          setError(null);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Unknown API error");
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, []);

  const tenantId = getTenantId();

  return (
    <main style={shellStyle}>
      <div style={frameStyle}>
        <section style={heroStyle}>
          <div style={{ ...badgeStyle, marginBottom: 18 }}>Phase 1 Project List</div>
          <h1 style={{ margin: 0, fontSize: "clamp(2.4rem, 6vw, 4.7rem)", lineHeight: 0.95 }}>
            Procurement watchlist,
            <br />
            without the spreadsheet drift.
          </h1>
          <p style={{ maxWidth: 760, color: "var(--muted)", fontSize: 18, lineHeight: 1.6 }}>
            This first UI slice reads canonical backend state from the FastAPI control plane.
            Set <code>NEXT_PUBLIC_EGP_TENANT_ID</code> and optionally{" "}
            <code>NEXT_PUBLIC_EGP_API_BASE_URL</code> to point the list at a real tenant.
          </p>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", color: "var(--muted)" }}>
            <span>API: {getApiBaseUrl()}</span>
            <span>Tenant: {tenantId || "not configured"}</span>
          </div>
        </section>

        {!tenantId ? (
          <section style={{ ...cardStyle, padding: "26px 28px" }}>
            <h2 style={{ marginTop: 0 }}>Tenant configuration required</h2>
            <p style={{ marginBottom: 0, color: "var(--muted)" }}>
              Add <code>NEXT_PUBLIC_EGP_TENANT_ID</code> before trying to load the project list.
            </p>
          </section>
        ) : null}

        {isLoading ? (
          <section style={{ ...cardStyle, padding: "26px 28px" }}>
            <h2 style={{ marginTop: 0 }}>Loading projects</h2>
            <p style={{ marginBottom: 0, color: "var(--muted)" }}>
              Pulling canonical project records from the API.
            </p>
          </section>
        ) : null}

        {!isLoading && error ? (
          <section style={{ ...cardStyle, padding: "26px 28px", borderColor: "rgba(138, 47, 47, 0.25)" }}>
            <h2 style={{ marginTop: 0, color: "var(--danger)" }}>Project list failed</h2>
            <p style={{ marginBottom: 0, color: "var(--muted)" }}>{error}</p>
          </section>
        ) : null}

        {!isLoading && !error && tenantId && projects.length === 0 ? (
          <section style={{ ...cardStyle, padding: "26px 28px" }}>
            <h2 style={{ marginTop: 0 }}>No projects yet</h2>
            <p style={{ marginBottom: 0, color: "var(--muted)" }}>
              The API responded successfully, but this tenant does not have any canonical project
              records yet.
            </p>
          </section>
        ) : null}

        {!isLoading && !error && projects.length > 0 ? (
          <section style={{ display: "grid", gap: 18 }}>
            {projects.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
          </section>
        ) : null}
      </div>
    </main>
  );
}
