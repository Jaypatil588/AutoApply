"""Ashby ATS application automation.

Implements: FR-071 (Ashby ATS).

Ashby is used by OpenAI, YC startups, and other tech companies.
Application pages live at ``jobs.ashbyhq.com/{company}/application/{id}``
and present a single-page form with personal info, resume upload,
cover letter, and custom questions.
"""

from __future__ import annotations

import json
import logging
import re

from bot.apply.base import ApplyResult, BaseApplier

logger = logging.getLogger(__name__)


_QUESTION_ALIASES = {
    "work_authorization": (
        "legally authorized to work",
        "authorized to work",
        "work authorization",
    ),
    "visa_sponsorship": (
        "require visa sponsorship",
        "require sponsorship",
        "visa sponsorship",
    ),
    "willing_to_work_in_office": (
        "willing to work in office",
        "willing to work in-office",
        "fully in person team",
        "fully in-person team",
    ),
}


def _normalize(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


class AshbyApplier(BaseApplier):
    """Automate Ashby job application submissions.

    Ashby uses a clean single-page React form with standard HTML inputs,
    file upload, and optional custom questions.
    """

    def _do_apply(
        self, job, resume_pdf_path, cover_letter_text, profile
    ) -> ApplyResult:
        logger.info("Ashby: applying to %s at %s", job.raw.title, job.raw.company)
        self._safe_goto(job.raw.apply_url)
        self._random_pause(1, 3)

        if self._detect_captcha():
            return ApplyResult(
                success=False, captcha_detected=True,
                error_message="CAPTCHA detected",
            )

        # Only job-detail pages need an Apply click. On an application page,
        # broad :has-text("Apply") selectors also match "Submit Application".
        if "/application" not in self.page.url.lower():
            self._safe_click(
                'a:text-is("Apply for this job"), '
                'button:text-is("Apply for this job"), '
                'a:text-is("Apply"), '
                'button:text-is("Apply")',
                timeout=3000,
            )
            self._random_pause(1, 2)

        if resume_pdf_path:
            self._upload_resume(resume_pdf_path)
            self._random_pause(2, 3)

        self._fill_form_fields(profile)

        self._fill_cover_letter(cover_letter_text)
        self._answer_custom_questions(profile)
        self._answer_unknown_questions_with_ai(profile)
        self._random_pause(0.5, 1)

        # Submit
        submit_btn = self._wait_and_query(
            'button[type="submit"]:text-is("Submit Application"), '
            'button:text-is("Submit Application")',
            timeout=5000,
        )

        if not submit_btn:
            return ApplyResult(
                success=False, manual_required=True,
                error_message="Submit button not found on Ashby form",
            )

        submit_btn.click()
        self._random_pause(2, 4)

        # Check for success
        success_el = self._wait_and_query(
            'text="Your application has been submitted", '
            'text="Application submitted", '
            'text="Thank you", '
            'h1:has-text("Thank"), '
            'h2:has-text("Thank")',
            timeout=5000,
        )
        if success_el:
            return ApplyResult(success=True)

        # Check for errors
        error_el = self.page.query_selector(
            '[role="alert"], .error-message, .form-error'
        )
        if error_el and error_el.is_visible():
            error_text = error_el.inner_text()[:200]
            return ApplyResult(
                success=False,
                error_message=f"Ashby form error: {error_text}",
            )

        return ApplyResult(
            success=False,
            manual_required=True,
            error_message="Ashby submit clicked but no confirmation was detected",
        )

    def _upload_resume(self, resume_pdf_path) -> bool:
        return self._safe_upload(resume_pdf_path, [
            'input[type="file"][name*="resume"]',
            'input[type="file"][accept*="pdf"]',
            'input[type="file"]',
        ])

    def _fill_form_fields(self, profile) -> None:
        """Fill Ashby personal info fields."""
        field_map = {
            'input#_systemfield_name, input[name="name"], input[name*="Name"]:not([name*="last"])': profile.full_name,
            'input[name*="firstName"], input[name*="first_name"]': profile.first_name,
            'input[name*="lastName"], input[name*="last_name"]': profile.last_name,
            'input[name="email"], input[name*="email"], input[type="email"]': profile.email,
            'input[name="phone"], input[name*="phone"], input[type="tel"]': profile.phone_full,
        }

        for selector, value in field_map.items():
            self._safe_fill(selector, value)

        self._safe_fill_by_label("Name", profile.full_name)
        self._safe_fill_by_label("Email", profile.email)
        self._safe_fill_by_label("Phone Number", profile.phone_full)

        # LinkedIn URL
        if profile.linkedin_url:
            filled = self._safe_fill(
                'input[name*="linkedin"], input[name*="LinkedIn"], '
                'input[placeholder*="LinkedIn"], input[placeholder*="linkedin"]',
                profile.linkedin_url,
            )
            if not filled:
                self._safe_fill_by_label("LinkedIn", profile.linkedin_url)

        if profile.github_url:
            self._safe_fill_by_label("Github", profile.github_url)

        # Portfolio / website
        if profile.portfolio_url:
            self._safe_fill(
                'input[name*="website"], input[name*="portfolio"], '
                'input[placeholder*="Website"], input[placeholder*="Portfolio"]',
                profile.portfolio_url,
            )

        # Location
        self._safe_fill(
            'input[name*="location"], input[name*="Location"], '
            'input[placeholder*="location"]',
            profile.location,
        )

    def _safe_fill_by_label(self, label: str, value: str) -> bool:
        """Fill an empty control by its accessible label."""
        if not value:
            return False
        try:
            locator = self.page.get_by_label(label, exact=True).first
            if not locator.is_visible() or locator.input_value():
                return False
            self._human_type(locator, value)
            self._random_pause(0.2, 0.5)
            return True
        except Exception as e:
            logger.debug("Ashby: label %r was not fillable: %s", label, e)
            return False

    def _fill_cover_letter(self, text: str) -> None:
        """Fill cover letter textarea on Ashby form."""
        if not text:
            return

        page = self.page

        textarea = page.query_selector(
            'textarea[name*="cover"], '
            'textarea[name*="Cover"], '
            'textarea[name*="letter"], '
            'textarea[placeholder*="cover letter"], '
            'textarea[placeholder*="Cover Letter"]'
        )
        if textarea and textarea.is_visible() and not textarea.input_value():
            textarea.fill(text)
            self._random_pause(0.5, 1)
            return

        # Ashby sometimes uses a generic "Additional information" textarea
        additional = page.query_selector(
            'textarea[name*="additional"], '
            'textarea[placeholder*="additional"], '
            'textarea[placeholder*="anything else"]'
        )
        if additional and additional.is_visible() and not additional.input_value():
            additional.fill(text)
            self._random_pause(0.5, 1)

    def _answer_custom_questions(self, profile) -> None:
        """Attempt to answer Ashby custom questions from screening_answers."""
        answers = profile.screening_answers
        if not answers:
            return

        page = self.page

        # Ashby renders Yes/No questions as two submit-typed buttons and a
        # hidden checkbox. They are not associated with a <label for=...>.
        seen_questions: set[str] = set()
        for button in page.query_selector_all("button"):
            try:
                option = button.inner_text().strip()
                if option.lower() not in {"yes", "no"}:
                    continue
                group = button.evaluate(
                    """el => {
                      let node = el.parentElement;
                      while (node && node !== document.body) {
                        const buttons = [...node.querySelectorAll('button')]
                          .map(b => (b.innerText || '').trim().toLowerCase());
                        if (buttons.includes('yes') && buttons.includes('no')) {
                          const field = node.parentElement || node;
                          const clone = field.cloneNode(true);
                          clone.querySelectorAll('button,input,select,textarea')
                            .forEach(control => control.remove());
                          return {
                            question: (clone.innerText || '').trim(),
                            answered: !!field.querySelector('input[type=checkbox]:checked')
                          };
                        }
                        node = node.parentElement;
                      }
                      return null;
                    }"""
                )
                if not group or group["answered"]:
                    continue
                question = group["question"]
                normalized = _normalize(question)
                if not normalized or normalized in seen_questions:
                    continue
                answer = self._known_answer(question, answers)
                if answer and option.lower() == str(answer).strip().lower():
                    button.click()
                    seen_questions.add(normalized)
                    self._random_pause(0.3, 0.6)
            except Exception as e:
                logger.debug("Ashby: failed to inspect segmented question: %s", e)

        # Ashby renders custom questions as labeled form groups
        # Try to match label text to screening_answers keys
        labels = page.query_selector_all("label")
        for label in labels:
            try:
                label_text = label.inner_text().strip().lower()
            except Exception as e:
                logger.debug("Ashby: failed to read label text: %s", e)
                continue

            # Match against screening_answers
            for key, value in answers.items():
                if not value:
                    continue
                key_lower = key.replace("_", " ").lower()
                if key_lower in label_text or label_text in key_lower:
                    label_for = label.get_attribute("for")
                    if label_for:
                        escaped_id = label_for.replace("\\", "\\\\").replace('"', '\\"')
                        inp = page.query_selector(f'[id="{escaped_id}"]')
                        if inp and inp.is_visible():
                            tag = inp.evaluate("el => el.tagName.toLowerCase()")
                            if tag == "select":
                                if not inp.input_value():
                                    inp.select_option(label=value)
                            elif tag == "textarea":
                                if not inp.input_value():
                                    inp.fill(value)
                            elif tag == "button":
                                button_text = inp.inner_text().strip().lower()
                                if not button_text or any(
                                    marker in button_text for marker in ("select", "choose", "--")
                                ):
                                    inp.click()
                                    option = page.get_by_role(
                                        "option", name=str(value), exact=True,
                                    ).first
                                    if option.is_visible():
                                        option.click()
                            else:
                                if not inp.input_value():
                                    self._human_type(inp, value)
                            self._random_pause(0.3, 0.6)
                    break

    @staticmethod
    def _known_answer(question: str, answers: dict) -> str | None:
        normalized_question = _normalize(question)
        for key, value in answers.items():
            if not value:
                continue
            normalized_key = _normalize(key)
            aliases = _QUESTION_ALIASES.get(key, ())
            if (
                normalized_key in normalized_question
                or normalized_question in normalized_key
                or any(_normalize(alias) in normalized_question for alias in aliases)
            ):
                return str(value)
        return None

    def _unanswered_segmented_questions(self) -> list[dict]:
        questions: dict[str, dict] = {}
        for button in self.page.query_selector_all("button"):
            try:
                option = button.inner_text().strip()
                if option.lower() not in {"yes", "no"}:
                    continue
                group = button.evaluate(
                    """el => {
                      let node = el.parentElement;
                      while (node && node !== document.body) {
                        const buttons = [...node.querySelectorAll('button')]
                          .map(b => (b.innerText || '').trim());
                        const lowered = buttons.map(x => x.toLowerCase());
                        if (lowered.includes('yes') && lowered.includes('no')) {
                          const field = node.parentElement || node;
                          const clone = field.cloneNode(true);
                          clone.querySelectorAll('button,input,select,textarea')
                            .forEach(control => control.remove());
                          return {
                            question: (clone.innerText || '').trim(),
                            answered: !!field.querySelector('input[type=checkbox]:checked'),
                            options: buttons.filter(x => /^(yes|no)$/i.test(x))
                          };
                        }
                        node = node.parentElement;
                      }
                      return null;
                    }"""
                )
                if group and group["question"] and not group["answered"]:
                    key = _normalize(group["question"])
                    questions.setdefault(key, {
                        "question": group["question"],
                        "options": list(dict.fromkeys(group["options"])),
                    })
            except Exception as e:
                logger.debug("Ashby: unresolved question inspection failed: %s", e)
        return list(questions.values())

    def _answer_unknown_questions_with_ai(self, profile) -> None:
        """Answer unresolved segmented questions in one strict, batched LLM call."""
        unresolved = self._unanswered_segmented_questions()
        if not unresolved:
            return

        from config.settings import load_config
        from core.ai_engine import invoke_llm

        config = load_config()
        if not config or not config.llm.provider or not config.llm.api_key:
            logger.info("Ashby: %d questions unresolved and no LLM configured", len(unresolved))
            return

        profile_context = {
            "bio": profile.bio,
            "screening_answers": profile.screening_answers,
        }
        prompt = (
            "Answer these job application questions using only the supplied applicant facts. "
            "Return one JSON object mapping each exact question to one exact listed option. "
            "If the facts do not support an answer, use the string UNKNOWN. Do not infer or invent facts.\n"
            f"APPLICANT_FACTS={json.dumps(profile_context, ensure_ascii=True)}\n"
            f"QUESTIONS={json.dumps(unresolved, ensure_ascii=True)}"
        )
        try:
            generated = json.loads(invoke_llm(prompt, config.llm, timeout_seconds=45))
        except Exception as e:
            logger.warning("Ashby: batched question generation failed: %s", e)
            return
        if not isinstance(generated, dict):
            logger.warning("Ashby: question generation returned non-object JSON")
            return

        for question in unresolved:
            answer = generated.get(question["question"])
            if answer == "UNKNOWN" or answer not in question["options"]:
                continue
            for button in self.page.query_selector_all("button"):
                try:
                    if button.inner_text().strip() != answer:
                        continue
                    parent_text = button.evaluate(
                        "el => (el.parentElement && el.parentElement.parentElement "
                        "? el.parentElement.parentElement.innerText : '')"
                    )
                    if _normalize(question["question"]) in _normalize(parent_text):
                        button.click()
                        self._random_pause(0.3, 0.6)
                        break
                except Exception as e:
                    logger.debug("Ashby: generated answer click failed: %s", e)
