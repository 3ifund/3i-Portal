/**
 * 3i Fund Portal — API Client
 * Handles all HTTP requests to the FastAPI backend.
 */

const API = (() => {
    // Base URL of the FastAPI backend — update for each environment
    const BASE_URL = window.PORTAL_CONFIG?.apiBaseUrl || 'http://localhost:8000';

    /**
     * Get the stored JWT token.
     */
    function getToken() {
        return sessionStorage.getItem('access_token');
    }

    /**
     * Build headers for authenticated requests.
     */
    function authHeaders() {
        const token = getToken();
        const headers = { 'Content-Type': 'application/json' };
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        return headers;
    }

    /**
     * Handle response — check for auth errors, parse JSON.
     */
    async function handleResponse(response) {
        if (response.status === 401) {
            sessionStorage.removeItem('access_token');
            window.location.href = 'index.html';
            return null;
        }

        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            throw new Error(body.detail || `Request failed (${response.status})`);
        }

        return response.json();
    }

    /**
     * POST /auth/login
     */
    async function login(userId, password) {
        const response = await fetch(`${BASE_URL}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, password }),
        });
        return handleResponse(response);
    }

    /**
     * GET /auth/me — get current user info
     */
    async function getMe() {
        const response = await fetch(`${BASE_URL}/auth/me`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    /**
     * GET /elocs — list ELOCs for the current user's company
     */
    async function getElocs(status) {
        const params = status ? `?status=${encodeURIComponent(status)}` : '';
        const response = await fetch(`${BASE_URL}/elocs${params}`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    /**
     * GET /elocs/:id — ELOC detail (pricing periods, shares, state)
     */
    async function getEloc(elocId) {
        const response = await fetch(`${BASE_URL}/elocs/${encodeURIComponent(elocId)}`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    /**
     * GET /elocs/:id/workflow — workflow state and events from MongoDB
     */
    async function getElocWorkflow(elocId) {
        const response = await fetch(`${BASE_URL}/elocs/${encodeURIComponent(elocId)}/workflow`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    /**
     * GET /elocs/:id/documents/:step — get document for a workflow step
     */
    async function getElocDocument(elocId, step) {
        const response = await fetch(
            `${BASE_URL}/elocs/${encodeURIComponent(elocId)}/documents/${encodeURIComponent(step)}`,
            { headers: authHeaders() }
        );
        return handleResponse(response);
    }

    /**
     * POST /elocs/:id/purchase-notice — submit purchase notice
     */
    async function submitPurchaseNotice(elocId, pricingPeriod, shares) {
        const response = await fetch(
            `${BASE_URL}/elocs/${encodeURIComponent(elocId)}/purchase-notice`,
            {
                method: 'POST',
                headers: authHeaders(),
                body: JSON.stringify({
                    pricing_period: pricingPeriod,
                    shares: shares,
                }),
            }
        );
        return handleResponse(response);
    }

    /**
     * GET /elocs/shares-available — available shares for all pricing periods
     */
    async function getSharesAvailable() {
        const response = await fetch(`${BASE_URL}/elocs/shares-available`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    /**
     * GET /elocs/action-items — pending action items for the current user
     */
    async function getActionItems() {
        const response = await fetch(`${BASE_URL}/elocs/action-items`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    /**
     * GET /elocs/pricing-workflows — workflow states for ELOCs currently pricing
     */
    async function getPricingWorkflows() {
        const response = await fetch(`${BASE_URL}/elocs/pricing-workflows`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    /**
     * POST /elocs/:id/workflow/remove — remove ELOC from currently pricing
     */
    async function removePricingWorkflow(elocId) {
        const response = await fetch(
            `${BASE_URL}/elocs/${encodeURIComponent(elocId)}/workflow/remove`,
            { method: 'POST', headers: authHeaders() }
        );
        return handleResponse(response);
    }

    // --- Auth: password management ---

    /**
     * POST /auth/change-password
     */
    async function changePassword(currentPassword, newPassword) {
        const response = await fetch(`${BASE_URL}/auth/change-password`, {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
        });
        return handleResponse(response);
    }

    // --- Admin endpoints ---

    /**
     * GET /admin/companies
     */
    async function adminGetCompanies() {
        const response = await fetch(`${BASE_URL}/admin/companies`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    /**
     * GET /admin/elocs
     */
    async function adminGetElocs() {
        const response = await fetch(`${BASE_URL}/admin/elocs`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    /**
     * GET /admin/purchase-notices
     */
    async function adminGetPurchaseNotices() {
        const response = await fetch(`${BASE_URL}/admin/purchase-notices`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    // --- Admin: user management ---

    /**
     * GET /admin/users
     */
    async function adminGetUsers() {
        const response = await fetch(`${BASE_URL}/admin/users`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    /**
     * POST /admin/users
     */
    async function adminCreateUser(userData) {
        const response = await fetch(`${BASE_URL}/admin/users`, {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify(userData),
        });
        return handleResponse(response);
    }

    /**
     * PUT /admin/users/:userId
     */
    async function adminUpdateUser(userId, userData) {
        const response = await fetch(`${BASE_URL}/admin/users/${encodeURIComponent(userId)}`, {
            method: 'PUT',
            headers: authHeaders(),
            body: JSON.stringify(userData),
        });
        return handleResponse(response);
    }

    /**
     * POST /admin/users/:userId/reset-password
     */
    async function adminResetPassword(userId, newPassword) {
        const response = await fetch(`${BASE_URL}/admin/users/${encodeURIComponent(userId)}/reset-password`, {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify({ new_password: newPassword }),
        });
        return handleResponse(response);
    }

    /**
     * DELETE /admin/users/:userId
     */
    async function adminDeleteUser(userId) {
        const response = await fetch(`${BASE_URL}/admin/users/${encodeURIComponent(userId)}`, {
            method: 'DELETE',
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    /**
     * GET /admin/companies-list — lightweight list for dropdowns
     */
    async function adminGetCompaniesList() {
        const response = await fetch(`${BASE_URL}/admin/companies-list`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    /**
     * GET /admin/companies-with-elocs — only companies that have ELOCs
     */
    async function adminGetCompaniesWithElocs() {
        const response = await fetch(`${BASE_URL}/admin/companies-with-elocs`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    // --- Admin: purchase notice templates ---

    async function adminGetPurchaseNoticeTemplates() {
        const response = await fetch(`${BASE_URL}/admin/purchase-notice-templates`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    async function adminGetCompanyTemplates(companyId) {
        const response = await fetch(`${BASE_URL}/admin/purchase-notice-templates/company/${encodeURIComponent(companyId)}`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    async function adminUpsertPurchaseNoticeTemplate(companyId, periodType, data) {
        const response = await fetch(`${BASE_URL}/admin/purchase-notice-templates/${encodeURIComponent(companyId)}/${encodeURIComponent(periodType)}`, {
            method: 'PUT',
            headers: authHeaders(),
            body: JSON.stringify(data),
        });
        return handleResponse(response);
    }

    // --- User: signatories ---

    async function getSignatories() {
        const response = await fetch(`${BASE_URL}/purchase-notices/signatories`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    async function addSignatory(data) {
        const response = await fetch(`${BASE_URL}/purchase-notices/signatories`, {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify(data),
        });
        return handleResponse(response);
    }

    async function updateSignatory(signatoryId, data) {
        const response = await fetch(`${BASE_URL}/purchase-notices/signatories/${encodeURIComponent(signatoryId)}`, {
            method: 'PUT',
            headers: authHeaders(),
            body: JSON.stringify(data),
        });
        return handleResponse(response);
    }

    async function deleteSignatory(signatoryId) {
        const response = await fetch(`${BASE_URL}/purchase-notices/signatories/${encodeURIComponent(signatoryId)}`, {
            method: 'DELETE',
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    // --- Purchase notice prefill ---

    async function getPurchaseNoticePrefill(symbol, pricingPeriodId, shares) {
        const response = await fetch(
            `${BASE_URL}/purchase-notices/prefill/${encodeURIComponent(symbol)}/${pricingPeriodId}?shares=${shares}`,
            { headers: authHeaders() }
        );
        return handleResponse(response);
    }

    return {
        login,
        getMe,
        getElocs,
        getEloc,
        getSharesAvailable,
        getActionItems,
        getPricingWorkflows,
        removePricingWorkflow,
        getElocWorkflow,
        getElocDocument,
        submitPurchaseNotice,
        changePassword,
        adminGetCompanies,
        adminGetElocs,
        adminGetPurchaseNotices,
        adminGetUsers,
        adminCreateUser,
        adminUpdateUser,
        adminResetPassword,
        adminDeleteUser,
        adminGetCompaniesList,
        adminGetCompaniesWithElocs,
        adminGetPurchaseNoticeTemplates,
        adminGetCompanyTemplates,
        adminUpsertPurchaseNoticeTemplate,
        getSignatories,
        addSignatory,
        updateSignatory,
        deleteSignatory,
        getPurchaseNoticePrefill,
    };
})();
