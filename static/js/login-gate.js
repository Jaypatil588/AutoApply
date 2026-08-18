/* ═══════════════════════════════════════════════════════════════
   LOGIN GATE MODAL — browser handoff for portal authentication
   Implements: FR-089 (browser handoff login gate)
   ═══════════════════════════════════════════════════════════════ */
import { t } from './i18n.js';

export function showLoginGateModal(ctx) {
  const modal = document.getElementById('modal-login-gate');
  const isCaptcha = ctx.portal_type === 'captcha';
  document.getElementById('login-gate-title').textContent = isCaptcha ? 'CAPTCHA Required' : t('login_gate.title');
  document.getElementById('login-gate-desc').textContent = isCaptcha
    ? 'Solve the CAPTCHA in the visible application browser, then continue.'
    : t('login_gate.description');
  document.getElementById('login-gate-done').textContent = isCaptcha ? 'CAPTCHA Solved' : t('login_gate.done_button');
  for (const id of ['login-gate-save-hint', 'login-gate-username-group', 'login-gate-password-group']) {
    document.getElementById(id).classList.toggle('hidden', isCaptcha);
  }
  document.getElementById('login-gate-domain').textContent = ctx.domain || t('login_gate.unknown');
  document.getElementById('login-gate-type').textContent = ctx.portal_type || 'generic';
  if (ctx.url) {
    const link = document.getElementById('login-gate-url');
    link.href = ctx.url;
    link.textContent = ctx.url;
    link.parentElement.classList.remove('hidden');
  }
  document.getElementById('login-gate-username').value = '';
  document.getElementById('login-gate-password').value = '';
  modal.classList.remove('hidden');
}

export function hideLoginGateModal() {
  const modal = document.getElementById('modal-login-gate');
  if (modal) modal.classList.add('hidden');
}

export async function loginGateDone() {
  const username = document.getElementById('login-gate-username').value.trim();
  const password = document.getElementById('login-gate-password').value;
  const body = { decision: 'done' };
  if (username && password) {
    body.username = username;
    body.password = password;
  }
  try {
    await fetch('/api/portal-auth/login-decision', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    hideLoginGateModal();
  } catch (e) {
    console.warn('Login gate done error:', e);
  }
}

export async function loginGateSkip() {
  try {
    await fetch('/api/portal-auth/login-decision', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision: 'skip' }),
    });
    hideLoginGateModal();
  } catch (e) {
    console.warn('Login gate skip error:', e);
  }
}
