"""iCIMS frame-based application automation.

The step and identity selectors are adapted from SummonIQ/gimme-job's
Unlicense iCIMS submit runner. CAPTCHA challenges are surfaced for manual
completion; they are never bypassed.
"""

from __future__ import annotations

import logging

from bot.apply.base import ApplyResult, BaseApplier

logger = logging.getLogger(__name__)


class ICIMSApplier(BaseApplier):
    """Run the legacy iCIMS application wizard inside its named iframe."""

    MAX_STEPS = 10

    def _do_apply(self, job, resume_pdf_path, cover_letter_text, profile) -> ApplyResult:
        del cover_letter_text
        logger.info("iCIMS: applying to %s at %s", job.raw.title, job.raw.company)
        self._safe_goto(job.raw.apply_url)
        self._random_pause(1, 2)

        frame = self.page.frame(name="icims_content_iframe")
        if not frame:
            return ApplyResult(
                success=False, manual_required=True,
                error_message="iCIMS content iframe not found",
            )

        apply_link = self._frame_wait(
            frame, 'a:has-text("Apply for this job online")', timeout=8000,
        )
        if not apply_link:
            return ApplyResult(
                success=False, manual_required=True,
                error_message="iCIMS online application link not found",
            )
        apply_link.click()
        self._random_pause(1, 2)

        for _ in range(self.MAX_STEPS):
            frame = self.page.frame(name="icims_content_iframe")
            if not frame:
                return ApplyResult(
                    success=False, manual_required=True,
                    error_message="iCIMS content iframe disappeared",
                )
            if self._frame_has_captcha(frame):
                if self._captcha_gate is None or not self._captcha_gate(
                    "Solve the iCIMS CAPTCHA in the visible browser",
                ):
                    return ApplyResult(
                        success=False, captcha_detected=True, manual_required=True,
                        error_message="iCIMS CAPTCHA requires manual completion",
                    )
                continue
            if self._is_confirmed(frame):
                return ApplyResult(success=True)

            changed = self._fill_identity(frame, profile)
            if resume_pdf_path:
                resume = frame.query_selector('input[name*="resume" i][type="file"]')
                if resume:
                    resume.set_input_files(str(resume_pdf_path))
                    changed = True

            submit = frame.query_selector('input[type="submit"][value*="Submit" i]')
            if submit and submit.is_visible():
                submit.click()
                self._random_pause(2, 4)
                frame = self.page.frame(name="icims_content_iframe")
                if frame and self._is_confirmed(frame):
                    return ApplyResult(success=True)
                return ApplyResult(
                    success=False, manual_required=True,
                    error_message="iCIMS submit clicked but no confirmation was detected",
                )

            next_button = frame.query_selector('button:has-text("Next")')
            if next_button and next_button.is_visible():
                next_button.click()
                self._random_pause(1, 2)
                continue

            if not changed:
                return ApplyResult(
                    success=False, manual_required=True,
                    error_message="iCIMS reached an unsupported required step",
                )

        return ApplyResult(
            success=False, manual_required=True,
            error_message="iCIMS wizard exceeded the 10-step limit",
        )

    def _frame_wait(self, frame, selector: str, timeout: int):
        try:
            frame.wait_for_selector(selector, timeout=timeout, state="visible")
            return frame.query_selector(selector)
        except Exception:
            return None

    def _frame_has_captcha(self, frame) -> bool:
        if frame.query_selector('iframe[src*="hcaptcha.com"]'):
            return True
        return any("hcaptcha.com" in (child.url or "") for child in frame.child_frames)

    def _is_confirmed(self, frame) -> bool:
        body = frame.query_selector("body")
        if not body:
            return False
        text = body.inner_text().lower()
        return "thank you for applying" in text or "application has been submitted" in text

    def _fill_identity(self, frame, profile) -> bool:
        fields = (
            ('input[name="firstname"]', profile.first_name),
            ('input[name="lastname"]', profile.last_name),
            ('input[name="email"]', profile.email),
            ('input[name="phone"]', profile.phone),
        )
        changed = False
        for selector, value in fields:
            element = frame.query_selector(selector)
            if element and element.is_visible() and not element.input_value() and value:
                element.fill(value)
                changed = True
        return changed
