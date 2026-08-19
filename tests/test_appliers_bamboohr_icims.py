"""Contracts for the BambooHR and iCIMS CareerOps routes."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from bot.apply.bamboohr import BambooHRApplier
from bot.apply.icims import ICIMSApplier
from bot.search.base import RawJob
from core.filter import ScoredJob, detect_ats


def _job(url: str) -> ScoredJob:
    raw = RawJob(
        title="Software Engineer", company="Acme", location="Remote", salary=None,
        description="Software role", apply_url=url, platform="career_ops",
        external_id="career-ops-test", posted_at=None, prequalified=True,
    )
    return ScoredJob(id="job", raw=raw, score=100, pass_filter=True, skip_reason=None)


def _profile():
    profile = MagicMock()
    profile.first_name = "Jane"
    profile.last_name = "Doe"
    profile.email = "jane@example.com"
    profile.phone = "5550100"
    profile.phone_full = "+15550100"
    profile.address_line1 = "1 Main St"
    profile.city = "Austin"
    profile.zip_code = "78701"
    profile.linkedin_url = "https://linkedin.com/in/jane"
    profile.portfolio_url = "https://jane.dev"
    return profile


@patch("bot.apply.base.time.sleep")
def test_bamboohr_requires_manual_captcha(_sleep):
    page = MagicMock()
    apply_button = MagicMock()
    applier = BambooHRApplier(page)
    applier._wait_and_query = MagicMock(return_value=apply_button)
    applier._safe_upload = MagicMock(return_value=True)
    applier._detect_captcha = MagicMock(return_value=True)

    result = applier.apply(
        _job("https://acme.bamboohr.com/careers/1"),
        Path("/tmp/resume.pdf"), "", _profile(),
    )

    assert result.success is False
    assert result.captcha_detected is True
    assert result.manual_required is True


@patch("bot.apply.base.time.sleep")
def test_bamboohr_requires_confirmation_after_submit(_sleep):
    page = MagicMock()
    page.query_selector.return_value = None
    apply_button = MagicMock()
    submit_button = MagicMock()
    applier = BambooHRApplier(page)
    applier._wait_and_query = MagicMock(side_effect=[apply_button, submit_button, None])
    applier._safe_upload = MagicMock(return_value=True)
    applier._detect_captcha = MagicMock(return_value=False)

    result = applier.apply(
        _job("https://acme.bamboohr.com/careers/1"),
        Path("/tmp/resume.pdf"), "", _profile(),
    )

    assert result.success is False
    assert result.manual_required is True
    submit_button.click.assert_called_once()


@patch("bot.apply.base.time.sleep")
def test_icims_requires_manual_captcha(_sleep):
    page = MagicMock()
    frame = MagicMock()
    page.frame.return_value = frame
    applier = ICIMSApplier(page)
    applier._content_frame = MagicMock(return_value=frame)
    applier._frame_wait = MagicMock(return_value=MagicMock())
    applier._frame_has_captcha = MagicMock(return_value=True)

    result = applier.apply(
        _job("https://careers-acme.icims.com/jobs/1/job"),
        Path("/tmp/resume.pdf"), "", _profile(),
    )

    assert result.success is False
    assert result.captcha_detected is True
    assert result.manual_required is True


@patch("bot.apply.base.time.sleep")
def test_icims_requires_confirmation_after_submit(_sleep):
    page = MagicMock()
    frame = MagicMock()
    page.frame.return_value = frame
    submit = MagicMock()
    submit.is_visible.return_value = True
    frame.query_selector.side_effect = lambda selector: (
        submit if "Submit" in selector else None
    )
    applier = ICIMSApplier(page)
    applier._content_frame = MagicMock(return_value=frame)
    applier._frame_wait = MagicMock(return_value=MagicMock())
    applier._frame_has_captcha = MagicMock(return_value=False)
    applier._is_confirmed = MagicMock(return_value=False)
    applier._fill_identity = MagicMock(return_value=False)

    result = applier.apply(
        _job("https://careers-acme.icims.com/jobs/1/job"),
        Path("/tmp/resume.pdf"), "", _profile(),
    )

    assert result.success is False
    assert result.manual_required is True
    submit.click.assert_called_once()


def test_new_ats_routes_are_registered():
    from bot.bot import APPLIERS

    assert APPLIERS["bamboohr"] is BambooHRApplier
    assert APPLIERS["icims"] is ICIMSApplier
    assert detect_ats("https://acme.bamboohr.com/careers/1") == "bamboohr"
    assert detect_ats("https://careers-acme.icims.com/jobs/1/job") == "icims"
