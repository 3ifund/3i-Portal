/**
 * 3i Fund Portal — Authentication
 * Handles login form, token management, route guards, and logout.
 */

const Auth = (() => {
    /**
     * Check if user is authenticated. Redirect to login if not.
     * Call this on every protected page.
     */
    function requireAuth() {
        const token = sessionStorage.getItem('access_token');
        if (!token) {
            window.location.href = 'index.html';
            return false;
        }
        return true;
    }

    /**
     * Where a logged-in user belongs: PRM is the admin landing page (Admin Dashboard is now reached via
     * the persistent nav's "Admin" link, not login) — EXCEPT a still-pending forced password change,
     * which always wins and sends an admin to the Admin Dashboard's Change Password tab instead, since
     * that's the only page carrying that tab. Non-admins are unaffected (dashboard.html + its modal,
     * unchanged).
     */
    function postLoginDestination(role, mustChangePassword) {
        if (role !== 'admin') return 'dashboard.html';
        return mustChangePassword ? 'admin.html' : '/position_risk_management/';
    }

    /**
     * If already authenticated, redirect away from login page.
     */
    function redirectIfAuthenticated() {
        const token = sessionStorage.getItem('access_token');
        if (token) {
            const role = sessionStorage.getItem('user_role');
            const mustChange = sessionStorage.getItem('must_change_password') === 'true';
            const dest = postLoginDestination(role, mustChange);
            window.location.href = mustChange ? dest + '?change_password=1' : dest;
        }
    }

    /**
     * Store authentication data after successful login.
     */
    function storeAuth(data) {
        sessionStorage.setItem('access_token', data.access_token);
        sessionStorage.setItem('user_role', data.role || 'user');
        sessionStorage.setItem('company_name', data.company_name || '');
        sessionStorage.setItem('user_id', data.user_id || '');
        sessionStorage.setItem('must_change_password', data.must_change_password ? 'true' : 'false');
        if (data.refresh_token) {
            localStorage.setItem('refresh_token', data.refresh_token);
        }
    }

    /**
     * Clear authentication data and redirect to login.
     */
    function logout() {
        sessionStorage.removeItem('access_token');
        sessionStorage.removeItem('user_role');
        sessionStorage.removeItem('company_name');
        sessionStorage.removeItem('user_id');
        sessionStorage.removeItem('must_change_password');
        localStorage.removeItem('refresh_token');
        window.location.href = 'index.html';
    }

    /**
     * Populate navbar with company name and attach logout handler.
     */
    function initNavbar() {
        const companyEl = document.getElementById('company-name');
        if (companyEl) {
            companyEl.textContent = sessionStorage.getItem('company_name') || '';
        }

        const logoutBtn = document.getElementById('logout-btn');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', logout);
        }
    }

    /**
     * Initialize login form (only on index.html).
     */
    function initLoginForm() {
        const form = document.getElementById('login-form');
        if (!form) return;

        redirectIfAuthenticated();

        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const userId = document.getElementById('user-id').value.trim();
            const password = document.getElementById('password').value;
            const errorEl = document.getElementById('login-error');
            const btn = document.getElementById('login-btn');

            errorEl.classList.remove('visible');
            btn.disabled = true;
            btn.textContent = 'Signing in...';

            try {
                const data = await API.login(userId, password);
                storeAuth(data);

                const dest = postLoginDestination(data.role, data.must_change_password);
                window.location.href = data.must_change_password ? dest + '?change_password=1' : dest;
            } catch (err) {
                errorEl.textContent = err.message || 'Invalid User ID or password.';
                errorEl.classList.add('visible');
                btn.disabled = false;
                btn.textContent = 'Sign In';
            }
        });
    }

    /**
     * Check if current user is admin.
     */
    function isAdmin() {
        return sessionStorage.getItem('user_role') === 'admin';
    }

    // Auto-initialize based on current page
    document.addEventListener('DOMContentLoaded', async () => {
        const isLoginPage = !!document.getElementById('login-form');

        if (isLoginPage) {
            initLoginForm();
            return;
        }

        if (!sessionStorage.getItem('access_token')) {
            const ok = await API.refreshAccessToken();
            if (!ok) {
                window.location.href = 'index.html';
                return;
            }
        }
        API.startProactiveRefresh();
        initNavbar();
    });

    return {
        requireAuth,
        logout,
        isAdmin,
        initNavbar,
    };
})();
