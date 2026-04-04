"use client";

import { Bell, Search } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";
import { NAV_ITEMS } from "@/lib/constants";

export function AppHeader() {
  const pathname = usePathname() ?? "";

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
          {NAV_ITEMS.map((item) => {
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

          <button
            type="button"
            className="flex items-center gap-2 rounded-full border border-[var(--border-default)] bg-[var(--bg-surface)] py-1 pl-1 pr-3"
          >
            <div className="flex size-8 items-center justify-center rounded-full bg-primary/20 text-xs font-semibold text-primary">
              ส
            </div>
            <span className="text-xs font-semibold text-[var(--text-secondary)]">
              สมชาย ก.
            </span>
          </button>
        </div>
      </div>
    </header>
  );
}
