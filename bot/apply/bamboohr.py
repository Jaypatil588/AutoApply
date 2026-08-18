"""BambooHR application automation.

Selector contract adapted from SummonIQ/gimme-job's Unlicense BambooHR
submit runner. Completion is reported only after a visible confirmation.
"""

from __future__ import annotations

import logging

from bot.apply.base import ApplyResult, BaseApplier

logger = logging.getLogger(__name__)


class BambooHRApplier(BaseApplier):
    """Fill and submit the current BambooHR careers application form."""

    def _do_apply(self, job, resume_pdf_path, cover_letter_text, profile) -> ApplyResult:
        del cover_letter_text
        logger.info("BambooHR: applying to %s at %s", job.raw.title, job.raw.company)
        self._safe_goto(job.raw.apply_url)
        self._random_pause(1, 2)

        apply_button = self._wait_and_query(
            'button:has-text("Apply for This Job")', timeout=5000,
        )
        if not apply_button:
            return ApplyResult(
                success=False, manual_required=True,
                error_message="BambooHR Apply for This Job button not found",
            )
        apply_button.click()
        self._random_pause(1, 2)

        self._safe_fill('input#firstName', profile.first_name)
        self._safe_fill('input#lastName', profile.last_name)
        self._safe_fill('input#email', profile.email)
        self._safe_fill('input#phone', profile.phone_full)
        self._safe_fill('input#address', profile.address_line1)
        self._safe_fill('input#city', profile.city)
        self._safe_fill('input#zip', profile.zip_code)
        if profile.linkedin_url:
            self._safe_fill('input[aria-label="LinkedIn URL"]', profile.linkedin_url)
        if profile.portfolio_url:
            self._safe_fill(
                'input[aria-label="Website, Blog or Portfolio"]', profile.portfolio_url,
            )

        if not resume_pdf_path:
            return ApplyResult(
                success=False, manual_required=True,
                error_message="BambooHR requires a resume before submission",
            )
        if not self._safe_upload(resume_pdf_path, 'input#resume'):
            return ApplyResult(
                success=False, manual_required=True,
                error_message="BambooHR resume input not found",
            )

        if not self._resolve_captcha("Solve the BambooHR CAPTCHA in the visible browser"):
            return ApplyResult(
                success=False, captcha_detected=True, manual_required=True,
                error_message="BambooHR CAPTCHA requires manual completion",
            )

        submit = self._wait_and_query(
            'button:has-text("Submit Application")', timeout=5000,
        )
        if not submit:
            return ApplyResult(
                success=False, manual_required=True,
                error_message="BambooHR Submit Application button not found",
            )
        submit.click()
        self._random_pause(2, 4)

        confirmation = self._wait_and_query(
            'text="Application submitted", text="Thank you for applying", '
            'h1:has-text("Thank you"), h2:has-text("Thank you")',
            timeout=8000,
        )
        if confirmation:
            return ApplyResult(success=True)

        error = self.page.query_selector('[role="alert"], .error, .field-error')
        if error and error.is_visible():
            return ApplyResult(
                success=False,
                error_message=f"BambooHR form error: {error.inner_text()[:200]}",
            )
        return ApplyResult(
            success=False, manual_required=True,
            error_message="BambooHR submit clicked but no confirmation was detected",
        )
