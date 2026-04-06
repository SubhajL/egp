"""Worker-side crawl profile defaults extracted from the legacy crawler."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


TOR_KEYWORDS_DEFAULT = [
    "วิเคราะห์ข้อมูล",
    "ระบบสารสนเทศ",
    "เทคโนโลยีสารสนเทศ",
    "ระบบคลังข้อมูล",
    "ระบบฐานข้อมูลใหญ่",
    "แผนแม่บท",
    "แผนปฏิบัติการ",
    "สถาปัตยกรรมองค์กร",
    "ธรรมาภิบาลข้อมูล",
    "ที่ปรึกษา",
    "ระบบวิเคราะห์",
    "ระบบบริหารจัดการ",
]

TOE_KEYWORDS_DEFAULT = [
    "จอแสดงผล",
    "จอแสดงภาพ",
    "interactive",
    "LED Wall",
    "Smart TV",
]

LUE_KEYWORDS_DEFAULT = [
    "ประชาสัมพันธ์",
    "โฆษณา",
    "จัดอบรม",
    "เว็บไซต์",
    "สื่อออนไลน์",
]


@dataclass(frozen=True, slots=True)
class WorkerProfileDefaults:
    name: str
    keywords: tuple[str, ...]
    download_dir: Path
    local_fallback_dir: Path


PROFILE_DEFAULTS: dict[str, WorkerProfileDefaults] = {
    "tor": WorkerProfileDefaults(
        name="tor",
        keywords=tuple(TOR_KEYWORDS_DEFAULT),
        download_dir=Path.home() / "OneDrive" / "Download" / "TOR",
        local_fallback_dir=Path.home() / "download" / "TOR",
    ),
    "toe": WorkerProfileDefaults(
        name="toe",
        keywords=tuple(TOE_KEYWORDS_DEFAULT),
        download_dir=Path.home() / "OneDrive" / "Download" / "TOE",
        local_fallback_dir=Path.home() / "download" / "TOE",
    ),
    "lue": WorkerProfileDefaults(
        name="lue",
        keywords=tuple(LUE_KEYWORDS_DEFAULT),
        download_dir=Path.home() / "OneDrive" / "Download" / "LUE",
        local_fallback_dir=Path.home() / "download" / "LUE",
    ),
}


def resolve_profile_keywords(*, profile: str | None = None, keyword: str | None = None) -> list[str]:
    if keyword is not None and keyword.strip():
        return [keyword.strip()]
    normalized_profile = (profile or "tor").strip().casefold()
    if normalized_profile not in PROFILE_DEFAULTS:
        raise ValueError(f"unsupported profile: {profile}")
    return list(PROFILE_DEFAULTS[normalized_profile].keywords)
