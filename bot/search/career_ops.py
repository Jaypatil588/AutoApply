"""Read a CareerOps discovery result as a one-shot AutoApply source."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterator
from urllib.parse import urlparse

from bot.search.base import BaseSearcher, RawJob

if TYPE_CHECKING:
    from config.settings import SearchCriteria


QUEUE_ENV = "AUTOAPPLY_CAREER_OPS_QUEUE"
SUPPORTED_ATS = frozenset({
    "Greenhouse", "Ashby", "Workday", "Lever", "BambooHR", "iCIMS",
})
MAX_QUEUE_AGE_HOURS = 6


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"CareerOps queue requires {field}")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"CareerOps queue has invalid {field}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"CareerOps queue {field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validate_host(ats: str, url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = {
        "Greenhouse": host in {
            "boards.greenhouse.io",
            "job-boards.greenhouse.io",
            "job-boards.eu.greenhouse.io",
        },
        "Ashby": host == "jobs.ashbyhq.com",
        "Workday": bool(re.fullmatch(r"[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com", host)),
        "Lever": host == "jobs.lever.co",
        "BambooHR": host.endswith(".bamboohr.com"),
        "iCIMS": bool(re.fullmatch(r"(?:careers|jobs)-[a-z0-9-]+\.icims\.com", host)),
    }.get(ats, False)
    if parsed.scheme != "https" or not allowed:
        raise ValueError(f"CareerOps {ats} URL is outside the supported ATS host")


def load_career_ops_jobs(
    queue_path: str | Path,
    *,
    now: datetime | None = None,
) -> tuple[list[RawJob], list[dict[str, str]]]:
    """Validate the discovery artifact and return supported jobs plus exclusions."""
    path = Path(queue_path).expanduser().resolve(strict=True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ValueError("CareerOps queue must use discovery schemaVersion 1")
    generated_at = _parse_timestamp(payload.get("generatedAt"), "generatedAt")
    reference_time = _parse_timestamp(
        (payload.get("filter") or {}).get("referenceTime"),
        "filter.referenceTime",
    )
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_hours = (current - generated_at).total_seconds() / 3600
    if age_hours < 0 or age_hours > MAX_QUEUE_AGE_HOURS:
        raise ValueError(f"CareerOps queue age is {age_hours:.1f} hours; regenerate discovery")
    if generated_at != reference_time:
        raise ValueError("CareerOps generatedAt and filter.referenceTime must match")
    records = payload.get("jobs")
    if not isinstance(records, list):
        raise ValueError("CareerOps queue jobs must be an array")

    jobs: list[RawJob] = []
    excluded: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"CareerOps job {index} must be an object")
        ats = record.get("ats")
        url = record.get("url")
        title = record.get("title")
        company = record.get("company")
        description = record.get("description")
        if not all(isinstance(value, str) and value.strip() for value in (ats, url, title, company)):
            raise ValueError(f"CareerOps job {index} is missing ats, url, title, or company")
        if url in seen_urls:
            raise ValueError(f"CareerOps queue contains duplicate URL: {url}")
        seen_urls.add(url)
        if ats not in SUPPORTED_ATS:
            excluded.append({"ats": ats, "url": url, "reason": "no AutoApply applier"})
            continue
        _validate_host(ats, url)
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"CareerOps {ats} job is missing the fetched description: {url}")
        external_id = "career-ops-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        jobs.append(RawJob(
            title=title.strip(),
            company=company.strip(),
            location=str(record.get("location") or "").strip(),
            salary=None,
            description=description.strip(),
            apply_url=url,
            platform="career_ops",
            external_id=external_id,
            posted_at=str(record.get("postedAt") or "") or None,
            prequalified=True,
        ))
    return jobs, excluded


class CareerOpsSearcher(BaseSearcher):
    """Yield a validated CareerOps queue exactly once."""

    one_shot = True

    def __init__(self, queue_path: str | Path | None = None) -> None:
        configured = str(queue_path or os.environ.get(QUEUE_ENV, "")).strip()
        if not configured:
            raise ValueError(f"{QUEUE_ENV} must point to discovered-jobs.json")
        self.queue_path = configured
        self.excluded: list[dict[str, str]] = []

    def search(self, criteria: SearchCriteria, page=None) -> Iterator[RawJob]:
        del criteria, page
        jobs, self.excluded = load_career_ops_jobs(self.queue_path)
        yield from jobs


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a CareerOps discovery queue")
    parser.add_argument("queue", type=Path)
    args = parser.parse_args()
    jobs, excluded = load_career_ops_jobs(args.queue)
    supported_counts: dict[str, int] = {}
    for job in jobs:
        host = (urlparse(job.apply_url).hostname or "").lower()
        ats = (
            "Greenhouse" if "greenhouse.io" in host else
            "Ashby" if host == "jobs.ashbyhq.com" else
            "Workday" if host.endswith(".myworkdayjobs.com") else
            "Lever" if host == "jobs.lever.co" else
            "BambooHR" if host.endswith(".bamboohr.com") else
            "iCIMS"
        )
        supported_counts[ats] = supported_counts.get(ats, 0) + 1
    excluded_counts: dict[str, int] = {}
    for record in excluded:
        ats = record["ats"]
        excluded_counts[ats] = excluded_counts.get(ats, 0) + 1
    print(json.dumps({
        "queue": str(args.queue.expanduser().resolve()),
        "supported": len(jobs),
        "supportedByAts": supported_counts,
        "excluded": len(excluded),
        "excludedByAts": excluded_counts,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
