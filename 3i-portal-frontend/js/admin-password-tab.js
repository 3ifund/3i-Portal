/**
 * 3i Fund Portal — Admin Dashboard: Change Password tab
 * Inline replacement for the old password-change modal, specific to admin.html now that Change
 * Password lives as a dashboard tab rather than a global nav button. dashboard.html (the non-admin
 * landing page) is untouched and still uses the original js/password-modal.js overlay.
 *
 * Forced change (must_change_password sessionStorage flag, or ?change_password=1 on load): auto-selects
 * this tab and disables every other way to navigate off the page — the other tabs/subtabs, and the
 * persistent nav's Data Management / Position & Risk Management / Admin links — until the password is
 * actually changed. Sign Out is deliberately left enabled throughout: always a valid way out of a forced
 * change, same as it always has been.
 */
const AdminPasswordTab = (() => {
    function init() {
        const panel = document.getElementById('change-password-panel');
        if (!panel) return;

        const submitBtn = document.getElementById('change-password-submit');
        const statusEl = document.getElementById('change-password-status');

        const mustChange = sessionStorage.getItem('must_change_password') === 'true'
            || new URLSearchParams(window.location.search).get('change_password') === '1';

        panel.querySelectorAll('.password-toggle').forEach((btn) => {
            btn.addEventListener('click', () => {
                const input = document.getElementById(btn.dataset.target);
                if (!input) return;
                const showing = input.type === 'text';
                input.type = showing ? 'password' : 'text';
                btn.textContent = showing ? 'Show' : 'Hide';
            });
        });

        if (submitBtn) {
            submitBtn.addEventListener('click', async () => {
                const current = document.getElementById('current-password').value;
                const newPwd = document.getElementById('new-password').value;
                const confirm = document.getElementById('confirm-password').value;

                if (!current || !newPwd || !confirm) {
                    statusEl.className = 'modal-status error';
                    statusEl.textContent = 'All fields are required.';
                    return;
                }
                if (newPwd !== confirm) {
                    statusEl.className = 'modal-status error';
                    statusEl.textContent = 'New passwords do not match.';
                    return;
                }
                if (newPwd.length < 8) {
                    statusEl.className = 'modal-status error';
                    statusEl.textContent = 'New password must be at least 8 characters.';
                    return;
                }

                statusEl.className = 'modal-status sending';
                statusEl.textContent = 'Changing password...';
                submitBtn.disabled = true;

                try {
                    await API.changePassword(current, newPwd);
                    statusEl.className = 'modal-status success';
                    statusEl.textContent = 'Password changed successfully.';
                    sessionStorage.setItem('must_change_password', 'false');

                    if (window.location.search.includes('change_password')) {
                        const url = new URL(window.location);
                        url.searchParams.delete('change_password');
                        window.history.replaceState({}, '', url);
                    }

                    document.getElementById('current-password').value = '';
                    document.getElementById('new-password').value = '';
                    document.getElementById('confirm-password').value = '';

                    if (mustChange) unlockRestOfPage();
                } catch (err) {
                    statusEl.className = 'modal-status error';
                    statusEl.textContent = err.message || 'Failed to change password.';
                } finally {
                    submitBtn.disabled = false;
                }
            });
        }

        if (mustChange) lockToChangePasswordOnly();
    }

    function lockToChangePasswordOnly() {
        // Switches to the panel directly rather than via a synthetic click on admin.js's tab handler —
        // this script's own DOMContentLoaded listener can run before admin.js's (script include order
        // isn't a safe thing to depend on here), so admin.js's click handler may not be wired yet.
        document.querySelectorAll('[id$="-panel"]').forEach((el) => { el.style.display = 'none'; });
        document.getElementById('change-password-panel').style.display = '';
        document.getElementById('eloc-subtabs')?.style.setProperty('display', 'none');
        document.getElementById('conversions-subtabs')?.style.setProperty('display', 'none');

        document.querySelectorAll('.tab').forEach((t) => {
            t.classList.toggle('active', t.id === 'change-password-tab');
            if (t.id !== 'change-password-tab') t.setAttribute('disabled', 'disabled');
        });
        document.querySelectorAll('.subtab').forEach((t) => t.setAttribute('disabled', 'disabled'));
        document.querySelectorAll('.navbar-logout').forEach((el) => {
            if (el.id !== 'logout-btn') el.setAttribute('disabled', 'disabled');
        });
    }

    function unlockRestOfPage() {
        document.querySelectorAll('.tab, .subtab, .navbar-logout').forEach((el) => el.removeAttribute('disabled'));
    }

    document.addEventListener('DOMContentLoaded', init);
    return { init };
})();
