"""Contract tests for the CareerOps-to-AutoApply bridge."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from bot.search.career_ops import CareerOpsSearcher, load_career_ops_jobs
from config.settings import AppConfig
from core.filter import score_job
from core.filter import ScoredJob


NOW = datetime(2026, 8, 18, 22, 0, tzinfo=timezone.utc)


def _job(ats: str, url: str) -> dict:
    return {
        "ats": ats,
        "company": "Example",
        "description": "Required: 2 years of software development experience.",
        "location": "Remote",
        "postedAt": "2026-08-18T08:00:00.000Z",
        "title": "Software Engineer",
        "url": url,
    }


def _write_queue(tmp_path, jobs: list[dict], generated_at: datetime = NOW):
    timestamp = generated_at.isoformat().replace("+00:00", "Z")
    path = tmp_path / "discovered-jobs.json"
    path.write_text(json.dumps({
        "schemaVersion": 1,
        "generatedAt": timestamp,
        "filter": {"referenceTime": timestamp},
        "jobs": jobs,
    }), encoding="utf-8")
    return path


def test_loads_existing_ats_appliers_and_reports_unsupported(tmp_path):
    path = _write_queue(tmp_path, [
        _job("Greenhouse", "https://job-boards.greenhouse.io/acme/jobs/1"),
        _job("Ashby", "https://jobs.ashbyhq.com/acme/role"),
        _job("Workday", "https://acme.wd5.myworkdayjobs.com/en-US/jobs/job/1"),
        _job("Lever", "https://jobs.lever.co/acme/role"),
        _job("BambooHR", "https://acme.bamboohr.com/careers/1"),
        _job("iCIMS", "https://careers-acme.icims.com/jobs/1/job"),
    ])

    jobs, excluded = load_career_ops_jobs(path, now=NOW)

    assert len(jobs) == 6
    assert all(job.prequalified and job.platform == "career_ops" for job in jobs)
    assert excluded == []
    assert len({job.external_id for job in jobs}) == 6


def test_searcher_yields_the_validated_jobs(tmp_path):
    path = _write_queue(tmp_path, [
        _job("Greenhouse", "https://boards.greenhouse.io/acme/jobs/1"),
    ])
    searcher = CareerOpsSearcher(path)
    jobs = list(searcher.search(criteria=None))
    assert len(jobs) == 1
    assert jobs[0].description.startswith("Required:")


def test_rejects_stale_queue(tmp_path):
    path = _write_queue(tmp_path, [], generated_at=NOW - timedelta(hours=7))
    with pytest.raises(ValueError, match="regenerate discovery"):
        load_career_ops_jobs(path, now=NOW)


def test_rejects_wrong_host_for_claimed_ats(tmp_path):
    path = _write_queue(tmp_path, [
        _job("Greenhouse", "https://attacker.example/jobs/1"),
    ])
    with pytest.raises(ValueError, match="outside the supported ATS host"):
        load_career_ops_jobs(path, now=NOW)


def test_rejects_supported_job_without_description(tmp_path):
    record = _job("Ashby", "https://jobs.ashbyhq.com/acme/role")
    record["description"] = ""
    path = _write_queue(tmp_path, [record])
    with pytest.raises(ValueError, match="missing the fetched description"):
        load_career_ops_jobs(path, now=NOW)


def test_prequalified_job_bypasses_second_scoring_pass(valid_app_config_data):
    config = AppConfig(**valid_app_config_data)
    config.search_criteria.job_titles = ["Unrelated title"]
    job = _job("Greenhouse", "https://boards.greenhouse.io/acme/jobs/1")
    from bot.search.base import RawJob
    raw = RawJob(
        title=job["title"], company=job["company"], location=job["location"],
        salary=None, description=job["description"], apply_url=job["url"],
        platform="career_ops", external_id="career-ops-test", posted_at=job["postedAt"],
        prequalified=True,
    )
    scored = score_job(raw, config)
    assert scored.pass_filter is True
    assert scored.score == 100


def test_prequalified_job_reuses_static_resume_without_llm(
    tmp_path, valid_app_config_data,
):
    from bot.bot import _generate_docs
    from bot.search.base import RawJob

    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-test")
    config = AppConfig(**valid_app_config_data)
    config.profile.fallback_resume_path = str(resume)
    config.bot.cover_letter_enabled = False
    raw = RawJob(
        title="Software Engineer", company="Example", location="Remote",
        salary=None, description="Software", apply_url="https://jobs.lever.co/acme/1",
        platform="career_ops", external_id="career-ops-test", posted_at=None,
        prequalified=True,
    )
    scored = ScoredJob(id="1", raw=raw, score=100, pass_filter=True, skip_reason=None)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "core.ai_engine.generate_documents",
            lambda **kwargs: pytest.fail("CareerOps must not call the LLM document generator"),
        )
        generated, _, cover_letter, meta = _generate_docs(
            scored, config, tmp_path,
        )

    assert generated == resume.resolve()
    assert cover_letter == ""
    assert meta["reuse_source"] == "career_ops_static_resume"


def test_career_ops_run_is_not_capped_by_default_daily_limit(
    valid_app_config_data,
):
    """The explicit one-shot queue must be allowed to process all 93 records."""
    from bot.bot import _daily_limit_reached
    from bot.state import BotState

    config = AppConfig(**valid_app_config_data)
    config.bot.max_applications_per_day = 0
    state = BotState()

    assert _daily_limit_reached(state, config, career_ops_run=True) is False
    assert _daily_limit_reached(state, config, career_ops_run=False) is True
