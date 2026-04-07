import type { ReactNode } from "react";

import { localizeApiError } from "@/lib/api";

type QueryStateProps = {
  isLoading: boolean;
  isError: boolean;
  error?: Error | null;
  isEmpty?: boolean;
  emptyMessage?: string;
  children: ReactNode;
};

export function QueryState({
  isLoading,
  isError,
  error,
  isEmpty = false,
  emptyMessage = "ไม่มีข้อมูล",
  children,
}: QueryStateProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center rounded-2xl bg-[var(--bg-surface)] p-12 shadow-[var(--shadow-soft)]">
        <div className="text-center">
          <div className="mx-auto mb-3 size-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="text-sm text-[var(--text-muted)]">กำลังโหลดข้อมูล...</p>
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="rounded-2xl border border-[var(--badge-red-bg)] bg-[var(--bg-surface)] p-8 shadow-[var(--shadow-soft)]">
        <h3 className="text-sm font-semibold text-[var(--badge-red-text)]">
          ไม่สามารถเชื่อมต่อ API ได้
        </h3>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          {localizeApiError(error, "เกิดข้อผิดพลาดในการเชื่อมต่อ กรุณาลองใหม่อีกครั้ง")}
        </p>
      </div>
    );
  }

  if (isEmpty) {
    return (
      <div className="flex items-center justify-center rounded-2xl bg-[var(--bg-surface)] p-12 shadow-[var(--shadow-soft)]">
        <p className="text-sm text-[var(--text-muted)]">{emptyMessage}</p>
      </div>
    );
  }

  return <>{children}</>;
}
