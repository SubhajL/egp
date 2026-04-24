"""Shared browser state helpers for e-GP site-level UI errors."""

from __future__ import annotations

import time


def has_site_error_toast(page) -> bool:
    try:
        return bool(
            page.evaluate(
                r"""() => {
                    const compact = (value) => (value || '').replace(/\s+/g, '');
                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        return style.display !== 'none'
                            && style.visibility !== 'hidden'
                            && style.opacity !== '0'
                            && (el.offsetParent !== null || style.position === 'fixed');
                    };
                    const matchesToast = (el) => {
                        const text = compact(el.textContent || '');
                        return text.includes('ระบบเกิดข้อผิดพลาด')
                            && text.includes('กรุณาตรวจสอบ');
                    };
                    return Array.from(
                        document.querySelectorAll(
                            '[role="alert"], .toast, .alert, .toast-error, .swal2-popup'
                        )
                    ).some((el) => isVisible(el) && matchesToast(el));
                }"""
            )
        )
    except Exception:
        return False


def clear_site_error_toast(page) -> bool:
    try:
        closed = page.evaluate(
            r"""() => {
                const compact = (value) => (value || '').replace(/\s+/g, '');
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && style.opacity !== '0'
                        && (el.offsetParent !== null || style.position === 'fixed');
                };
                const matchesToast = (el) => {
                    const text = compact(el.textContent || '');
                    return text.includes('ระบบเกิดข้อผิดพลาด')
                        && text.includes('กรุณาตรวจสอบ');
                };
                const candidates = Array.from(
                    document.querySelectorAll(
                        '[role="alert"], .toast, .alert, .toast-error, .swal2-popup'
                    )
                ).filter(isVisible);
                const toast = candidates.find(matchesToast);
                if (!toast) return false;
                const closeSelectors = [
                    '.toast-close-button',
                    '.close',
                    '[aria-label*="close" i]',
                    '[aria-label*="ปิด"]',
                    'button',
                ];
                for (const selector of closeSelectors) {
                    const button = toast.querySelector(selector);
                    if (button && isVisible(button)) {
                        button.click();
                        return true;
                    }
                }
                return false;
            }"""
        )
        if closed:
            time.sleep(0.3)
        return bool(closed)
    except Exception:
        return False
