"""Persist sanitized failed-form DOMs and compact control signatures."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from config.settings import get_data_dir


def capture_failed_form(page, *, platform: str, external_id: str, reason: str) -> Path:
    """Capture the rendered form DOM without user-entered values and index its controls."""
    root = get_data_dir() / "failure_doms"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", external_id)[:80]
    dom_path = root / f"{stamp}_{platform}_{safe_id}.html"

    snapshot = page.evaluate(
        """() => {
          const clone = document.documentElement.cloneNode(true);
          clone.querySelectorAll('script,style,noscript').forEach(el => el.remove());
          clone.querySelectorAll('input,textarea,select').forEach(el => {
            el.removeAttribute('value');
            el.removeAttribute('checked');
            el.removeAttribute('selected');
            if (el.tagName === 'TEXTAREA') el.textContent = '';
          });
          const controls = [...document.querySelectorAll('input,textarea,select,button')]
            .filter(el => {
              const style = getComputedStyle(el);
              return style.display !== 'none' && style.visibility !== 'hidden';
            })
            .map(el => ({
              tag: el.tagName.toLowerCase(),
              type: el.getAttribute('type'),
              id: el.id || null,
              name: el.getAttribute('name'),
              role: el.getAttribute('role'),
              ariaLabel: el.getAttribute('aria-label'),
              placeholder: el.getAttribute('placeholder'),
              labels: el.labels ? [...el.labels].map(x => (x.innerText || '').trim()) : [],
              text: (el.innerText || '').trim().slice(0, 160),
              required: el.required || el.getAttribute('aria-required') === 'true',
              options: el.tagName === 'SELECT'
                ? [...el.options].map(x => (x.textContent || '').trim()).slice(0, 40)
                : []
            }));
          return {html: '<!doctype html>' + String.fromCharCode(10) + clone.outerHTML, controls};
        }"""
    )
    dom_path.write_text(snapshot["html"], encoding="utf-8")

    bank_path = get_data_dir() / "selector_bank.json"
    bank = json.loads(bank_path.read_text(encoding="utf-8")) if bank_path.exists() else {
        "schema_version": 1,
        "failures": [],
    }
    bank["failures"].append({
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform,
        "host": (urlparse(page.url).hostname or "").lower(),
        "url": page.url,
        "external_id": external_id,
        "reason": reason,
        "dom_path": str(dom_path),
        "controls": snapshot["controls"],
    })
    bank_path.write_text(json.dumps(bank, indent=2), encoding="utf-8")
    bank_path.chmod(0o600)
    return dom_path
