/**
 * 3i Fund Portal — Password Change Modal
 * Self-contained module for changing passwords.
 * Auto-shows (unclosable) when must_change_password is true.
 * Included on both admin.html and dashboard.html.
 */

const PasswordModal = (() => {
    function init() {
        const overlay = document.getElementById('password-modal-overlay');
        if (!overlay) return;

        const closeBtn = document.getElementById('password-modal-close');
        const cancelBtn = document.getElementById('password-modal-cancel');
        const submitBtn = document.getElementById('password-modal-submit');
        const changePasswordBtn = document.getElementById('change-password-btn');

        const mustChange = sessionStorage.getItem('must_change_password') === 'true'
            || new URLSearchParams(window.location.search).get('change_password') === '1';

        function open() {
            overlay.classList.add('visible');
        }

        function resetPasswordVisibility() {
            overlay.querySelectorAll('.password-toggle').forEach((btn) => {
                const input = document.getElementById(btn.dataset.target);
                if (input) input.type = 'password';
                btn.textContent = 'Show';
            });
        }

        function close() {
            // Don't allow close if forced
            if (mustChange && sessionStorage.getItem('must_change_password') === 'true') return;

            overlay.classList.remove('visible');
            document.getElementById('current-password').value = '';
            document.getElementById('new-password').value = '';
            document.getElementById('confirm-password').value = '';
            resetPasswordVisibility();
            const statusEl = document.getElementById('password-modal-status');
            statusEl.className = 'modal-status';
            statusEl.textContent = '';
        }

        // Show modal on button click
        if (changePasswordBtn) {
            changePasswordBtn.addEventListener('click', open);
        }

        // Close handlers (hidden when forced)
        if (closeBtn) closeBtn.addEventListener('click', close);
        if (cancelBtn) cancelBtn.addEventListener('click', close);

        // Password toggle handlers
        overlay.querySelectorAll('.password-toggle').forEach((btn) => {
            btn.addEventListener('click', () => {
                const input = document.getElementById(btn.dataset.target);
                if (!input) return;
                const showing = input.type === 'text';
                input.type = showing ? 'password' : 'text';
                btn.textContent = showing ? 'Show' : 'Hide';
            });
        });

        // Submit handler
        if (submitBtn) {
            submitBtn.addEventListener('click', async () => {
                const current = document.getElementById('current-password').value;
                const newPwd = document.getElementById('new-password').value;
                const confirm = document.getElementById('confirm-password').value;
                const statusEl = document.getElementById('password-modal-status');

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

                    // Remove query param if present
                    if (window.location.search.includes('change_password')) {
                        const url = new URL(window.location);
                        url.searchParams.delete('change_password');
                        window.history.replaceState({}, '', url);
                    }

                    setTimeout(() => {
                        overlay.classList.remove('visible');
                        // Re-show close/cancel if they were hidden
                        if (closeBtn) closeBtn.style.display = '';
                        if (cancelBtn) cancelBtn.style.display = '';
                    }, 1500);
                } catch (err) {
                    statusEl.className = 'modal-status error';
                    statusEl.textContent = err.message || 'Failed to change password.';
                } finally {
                    submitBtn.disabled = false;
                }
            });
        }

        // Auto-show if forced
        if (mustChange) {
            open();
            if (closeBtn) closeBtn.style.display = 'none';
            if (cancelBtn) cancelBtn.style.display = 'none';
        }
    }

    document.addEventListener('DOMContentLoaded', init);
    return { init };
})();
