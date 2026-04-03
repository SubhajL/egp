import type { ReactNode } from "react";
import { AppHeader } from "./app-header";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-[var(--bg-page)]">
      <AppHeader />
      <main className="mx-auto max-w-[1400px] px-6 py-8">{children}</main>
    </div>
  );
}
