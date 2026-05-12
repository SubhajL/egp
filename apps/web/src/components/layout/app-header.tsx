"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Bell, LogOut, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { startTransition, useState } from "react";

import {
  clearStoredCurrentSession,
  getUserDisplayName,
  getUserInitials,
} from "@/lib/auth";
import { logout } from "@/lib/api";
import { getNavItems } from "@/lib/constants";
import { useMe } from "@/lib/hooks";
import { cn } from "@/lib/utils";

export function AppHeader() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const pathname = usePathname() ?? "";
  const { data: currentSession } = useMe();
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const navItems = getNavItems(currentSession?.user.role);

  const displayName = currentSession ? getUserDisplayName(currentSession.user) : "กำลังโหลด...";
  const initials = currentSession ? getUserInitials(currentSession.user) : "?";

  async function handleLogout() {
    setIsLoggingOut(true);
    try {
      await logout();
    } finally {
      clearStoredCurrentSession();
      queryClient.clear();
      startTransition(() => {
        router.replace("/login");
      });
      setIsLoggingOut(false);
    }
  }

  return (
    <header
      className={cn(
        "sticky top-0 z-50 h-[72px] border-b",
        "bg-[var(--bg-surface)]/80 backdrop-blur-xl",
        "border-[var(--border-default)]",
      )}
    >
      <div className="mx-auto flex h-full max-w-[1400px] items-center justify-between px-6">
        {/* Left: Logo */}
        <div className="flex items-center gap-8">
          <Link href="/dashboard" className="flex items-center gap-3">
            <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Search className="size-5" />
            </div>
            <span className="text-xl font-bold tracking-tight text-[var(--text-primary)]">
              e-GP Intelligence
            </span>
          </Link>
        </div>

        {/* Center: Navigation */}
        <nav className="hidden items-center gap-6 lg:flex">
          {navItems.map((item) => {
            const isActive =
              pathname === item.href || pathname.startsWith(item.href + "/");
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "text-sm font-medium transition-colors",
                  isActive
                    ? "font-semibold text-primary"
                    : "text-[var(--text-muted)] hover:text-primary",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Right: Actions */}
        <div className="flex items-center gap-3 border-l border-[var(--border-default)] pl-6">
          <button
            type="button"
            className="relative flex size-10 items-center justify-center rounded-xl text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)]"
          >
            <Bell className="size-5" />
            <span className="absolute right-2.5 top-2.5 size-2 rounded-full bg-red-500" />
          </button>

          <div className="flex items-center gap-2 rounded-full border border-[var(--border-default)] bg-[var(--bg-surface)] py-1 pl-1 pr-2">
            <div className="flex size-8 items-center justify-center rounded-full bg-primary/20 text-xs font-semibold text-primary">
              {initials}
            </div>
            <div className="min-w-0">
              <p className="truncate text-xs font-semibold text-[var(--text-secondary)]">
                {displayName}
              </p>
              <p className="truncate text-[10px] uppercase tracking-[0.12em] text-[var(--text-muted)]">
                {currentSession?.tenant.slug ?? "session"}
              </p>
            </div>
            <button
              type="button"
              onClick={handleLogout}
              disabled={isLoggingOut}
              className="flex size-8 items-center justify-center rounded-full text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-surface-hover)] hover:text-[var(--text-primary)] disabled:cursor-not-allowed disabled:opacity-60"
              aria-label="ออกจากระบบ"
            >
              <LogOut className="size-4" />
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
