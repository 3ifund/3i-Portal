/**
 * 3i Fund Portal — API Client
 * Handles all HTTP requests to the FastAPI backend.
 */

const API = (() => {
    // Base URL of the FastAPI backend — update for each environment
    const BASE_URL = window.PORTAL_CONFIG?.apiBaseUrl || `http://${window.location.hostname}:8000`;

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
            if (!handleResponse._retried && await refreshAccessToken()) {
                handleResponse._retried = true;
                window.location.reload();
                return null;
            }
            sessionStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            window.location.href = 'index.html';
            return null;
        }

        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            // FastAPI returns either body.detail (string) or body.detail ({...structured...}).
            // For structured detail (e.g., the 409 ELOC_ALREADY_PRICING response from /submit)
            // we keep the original object on the thrown error so callers can render
            // code/blocking_eloc_id/etc. without re-parsing.
            const detail = body && body.detail;
            const message = (typeof detail === 'string' ? detail
                            : (detail && detail.message) ? detail.message
                            : `Request failed (${response.status})`);
            const err = new Error(message);
            err.status = response.status;
            err.body = body;
            err.detail = detail;
            throw err;
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
     * GET /elocs/shares-available — available shares for all pricing periods
     */
    async function getSharesAvailable() {
        const response = await fetch(`${BASE_URL}/elocs/shares-available`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    /**
     * GET /elocs/available-capital — per-period per-day "could have raised" backtest series
     */
    async function getAvailableCapital() {
        const response = await fetch(`${BASE_URL}/elocs/available-capital`, {
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

    async function adminPermanentDeleteUser(userId) {
        const response = await fetch(`${BASE_URL}/admin/users/${encodeURIComponent(userId)}/permanent`, {
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

    // --- Admin: purchase confirmation templates ---

    async function adminGetPurchaseConfirmationTemplates() {
        const response = await fetch(`${BASE_URL}/admin/purchase-confirmation-templates`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    async function adminGetCompanyConfirmationTemplates(companyId) {
        const response = await fetch(`${BASE_URL}/admin/purchase-confirmation-templates/company/${encodeURIComponent(companyId)}`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    async function adminUpsertPurchaseConfirmationTemplate(companyId, periodType, data) {
        const response = await fetch(`${BASE_URL}/admin/purchase-confirmation-templates/${encodeURIComponent(companyId)}/${encodeURIComponent(periodType)}`, {
            method: 'PUT',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        return handleResponse(response);
    }

    // --- User: signatory (single per user) ---

    async function getMySignatory() {
        const response = await fetch(`${BASE_URL}/purchase-notices/my-signatory`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    async function updateMySignatory(data) {
        const response = await fetch(`${BASE_URL}/purchase-notices/my-signatory`, {
            method: 'PUT',
            headers: authHeaders(),
            body: JSON.stringify(data),
        });
        return handleResponse(response);
    }

    // --- Purchase notice prefill ---

    async function getPurchaseNoticePrefill(symbol, pricingPeriodId, shares, backward) {
        let url = `${BASE_URL}/purchase-notices/prefill/${encodeURIComponent(symbol)}/${pricingPeriodId}?shares=${shares}`;
        if (backward) url += '&backward=true';
        const response = await fetch(url, { headers: authHeaders() });
        return handleResponse(response);
    }

    /**
     * POST /purchase-notices/submit — submit portal-initiated purchase notice to DTS
     */
    async function submitPortalPurchaseNotice(payload) {
        const response = await fetch(`${BASE_URL}/purchase-notices/submit`, {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify(payload),
        });
        return handleResponse(response);
    }

    /**
     * GET /purchase-notices/confirmation-prefill/:elocId — prefill data for purchase confirmation countersign
     */
    async function getPurchaseConfirmationPrefill(elocId) {
        const response = await fetch(
            `${BASE_URL}/purchase-notices/confirmation-prefill/${encodeURIComponent(elocId)}`,
            { headers: authHeaders() }
        );
        return handleResponse(response);
    }

    /**
     * POST /purchase-notices/countersign — submit countersigned purchase confirmation
     */
    async function submitCountersign(payload) {
        const response = await fetch(`${BASE_URL}/purchase-notices/countersign`, {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify(payload),
        });
        return handleResponse(response);
    }

    /**
     * GET /purchase-notices/documents/:elocId/:step — fetch document for portal ELOC
     */
    async function getPortalElocDocument(elocId, step) {
        const response = await fetch(
            `${BASE_URL}/purchase-notices/documents/${encodeURIComponent(elocId)}/${encodeURIComponent(step)}`,
            { headers: authHeaders() }
        );
        return handleResponse(response);
    }

    // --- Admin Approval Contacts ---

    async function adminGetApprovalContacts() {
        const response = await fetch(`${BASE_URL}/admin/approval-contacts`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    async function adminAddApprovalContact(name, phone_number) {
        const response = await fetch(`${BASE_URL}/admin/approval-contacts`, {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify({ name, phone_number }),
        });
        return handleResponse(response);
    }

    async function adminUpdateApprovalContact(contactId, name, phone_number) {
        const response = await fetch(`${BASE_URL}/admin/approval-contacts/${contactId}`, {
            method: 'PUT',
            headers: authHeaders(),
            body: JSON.stringify({ name, phone_number }),
        });
        return handleResponse(response);
    }

    async function adminDeleteApprovalContact(contactId) {
        const response = await fetch(`${BASE_URL}/admin/approval-contacts/${contactId}`, {
            method: 'DELETE',
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    async function adminSetContactInclude(contactId, include) {
        const response = await fetch(`${BASE_URL}/admin/approval-contacts/${contactId}/include`, {
            method: 'PUT',
            headers: authHeaders(),
            body: JSON.stringify({ include }),
        });
        return handleResponse(response);
    }

    // --- Admin Company Verifications ---

    async function adminGetCompanyVerifications() {
        const response = await fetch(`${BASE_URL}/admin/company-verifications`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    async function adminSetCompanyVerification(companyId, require_verification) {
        const response = await fetch(`${BASE_URL}/admin/company-verifications/${companyId}`, {
            method: 'PUT',
            headers: authHeaders(),
            body: JSON.stringify({ require_verification }),
        });
        return handleResponse(response);
    }

    // --- Admin Backward Purchase Notice Templates ---

    async function adminGetCompanyBackwardNoticeTemplates(companyId) {
        const response = await fetch(`${BASE_URL}/admin/purchase-notice-backward-templates/company/${encodeURIComponent(companyId)}`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    async function adminUpsertBackwardNoticeTemplate(companyId, periodType, data) {
        const response = await fetch(`${BASE_URL}/admin/purchase-notice-backward-templates/${encodeURIComponent(companyId)}/${encodeURIComponent(periodType)}`, {
            method: 'PUT',
            headers: authHeaders(),
            body: JSON.stringify(data),
        });
        return handleResponse(response);
    }

    // --- Admin Countersign SMS Settings ---

    async function adminGetCountersignSettings() {
        const response = await fetch(`${BASE_URL}/admin/countersign-settings`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    async function adminSetCountersignSms(companyId, enable_countersign_sms) {
        const response = await fetch(`${BASE_URL}/admin/countersign-settings/${companyId}`, {
            method: 'PUT',
            headers: authHeaders(),
            body: JSON.stringify({ enable_countersign_sms }),
        });
        return handleResponse(response);
    }

    // --- Admin: participation-ELOC templates + mappings ---

    async function adminGetParticipationFieldCatalog(documentType) {
        const response = await fetch(`${BASE_URL}/admin/participation-field-catalog/${encodeURIComponent(documentType)}`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    async function adminListParticipationTemplates(companyId, documentType) {
        const params = new URLSearchParams();
        if (companyId != null && companyId !== '') params.set('company_id', companyId);
        if (documentType) params.set('document_type', documentType);
        const response = await fetch(`${BASE_URL}/admin/participation-templates?${params.toString()}`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    async function adminGetParticipationTemplate(templateId) {
        const response = await fetch(`${BASE_URL}/admin/participation-templates/${encodeURIComponent(templateId)}`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    async function adminCreateParticipationTemplate(data) {
        const response = await fetch(`${BASE_URL}/admin/participation-templates`, {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify(data),
        });
        return handleResponse(response);
    }

    async function adminUpdateParticipationTemplate(templateId, data) {
        const response = await fetch(`${BASE_URL}/admin/participation-templates/${encodeURIComponent(templateId)}`, {
            method: 'PUT',
            headers: authHeaders(),
            body: JSON.stringify(data),
        });
        return handleResponse(response);
    }

    async function adminDeleteParticipationTemplate(templateId) {
        const response = await fetch(`${BASE_URL}/admin/participation-templates/${encodeURIComponent(templateId)}`, {
            method: 'DELETE',
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    async function adminListParticipationMappings(companyId, documentType) {
        const params = new URLSearchParams();
        if (companyId != null && companyId !== '') params.set('company_id', companyId);
        if (documentType) params.set('document_type', documentType);
        const response = await fetch(`${BASE_URL}/admin/participation-template-mappings?${params.toString()}`, {
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    async function adminUpsertParticipationMapping(data) {
        const response = await fetch(`${BASE_URL}/admin/participation-template-mappings`, {
            method: 'PUT',
            headers: authHeaders(),
            body: JSON.stringify(data),
        });
        return handleResponse(response);
    }

    async function adminDeleteParticipationMapping(companyId, pricingPeriodType, documentType) {
        const params = new URLSearchParams({
            company_id: companyId,
            pricing_period_type: pricingPeriodType,
            document_type: documentType,
        });
        const response = await fetch(`${BASE_URL}/admin/participation-template-mappings?${params.toString()}`, {
            method: 'DELETE',
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    async function adminPreviewParticipationPdf(payload) {
        const response = await fetch(`${BASE_URL}/admin/participation-pdf/preview`, {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify(payload),
        });
        if (response.status === 401) {
            sessionStorage.removeItem('access_token');
            window.location.href = 'index.html';
            return null;
        }
        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            const detail = body && body.detail;
            const message = (typeof detail === 'string' ? detail : `Preview failed (${response.status})`);
            const err = new Error(message);
            err.status = response.status;
            throw err;
        }
        return response.blob();
    }

    function decodeExpMs(token) {
        try {
            return (JSON.parse(atob(token.split('.')[1])).exp || 0) * 1000;
        } catch (e) {
            return 0;
        }
    }

    let refreshTimer = null;

    async function refreshAccessToken() {
        const rt = localStorage.getItem('refresh_token');
        if (!rt) return false;
        try {
            const resp = await fetch(`${BASE_URL}/auth/refresh`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: rt }),
            });
            if (!resp.ok) {
                if (resp.status === 401) localStorage.removeItem('refresh_token');
                return false;
            }
            const data = await resp.json();
            sessionStorage.setItem('access_token', data.access_token);
            if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token);
            return true;
        } catch (e) {
            return false;
        }
    }

    function startProactiveRefresh() {
        if (refreshTimer) clearTimeout(refreshTimer);
        const token = getToken();
        if (!token) return;
        const delay = Math.max(30000, decodeExpMs(token) - Date.now() - 120000);
        refreshTimer = setTimeout(async () => {
            await refreshAccessToken();
            startProactiveRefresh();
        }, delay);
    }

    async function adminListConversionTemplates(base) {
        const response = await fetch(`${BASE_URL}/admin/${base}/templates`, { headers: authHeaders() });
        return handleResponse(response);
    }

    async function adminGetConversionTemplate(base, templateId) {
        const response = await fetch(`${BASE_URL}/admin/${base}/templates/${encodeURIComponent(templateId)}`, { headers: authHeaders() });
        return handleResponse(response);
    }

    async function adminListConversionClasses(base) {
        const response = await fetch(`${BASE_URL}/admin/${base}/classes`, { headers: authHeaders() });
        return handleResponse(response);
    }

    async function adminMapConversionTemplate(base, instrumentId, templateId) {
        const response = await fetch(`${BASE_URL}/admin/${base}/mappings`, {
            method: 'PUT',
            headers: authHeaders(),
            body: JSON.stringify({ instrument_id: instrumentId, template_id: templateId }),
        });
        return handleResponse(response);
    }

    async function adminUnmapConversionTemplate(base, instrumentId) {
        const response = await fetch(`${BASE_URL}/admin/${base}/mappings/${instrumentId}`, {
            method: 'DELETE',
            headers: authHeaders(),
        });
        return handleResponse(response);
    }

    return {
        login,
        refreshAccessToken,
        startProactiveRefresh,
        getMe,
        getElocs,
        getEloc,
        getSharesAvailable,
        getAvailableCapital,
        getActionItems,
        getPricingWorkflows,
        removePricingWorkflow,
        getElocWorkflow,
        getElocDocument,
        submitPortalPurchaseNotice,
        getPortalElocDocument,
        changePassword,
        adminGetCompanies,
        adminGetUsers,
        adminCreateUser,
        adminUpdateUser,
        adminResetPassword,
        adminDeleteUser,
        adminPermanentDeleteUser,
        adminGetCompaniesList,
        adminGetCompaniesWithElocs,
        adminGetPurchaseNoticeTemplates,
        adminGetCompanyTemplates,
        adminUpsertPurchaseNoticeTemplate,
        adminGetPurchaseConfirmationTemplates,
        adminGetCompanyConfirmationTemplates,
        adminUpsertPurchaseConfirmationTemplate,
        getMySignatory,
        updateMySignatory,
        getPurchaseNoticePrefill,
        getPurchaseConfirmationPrefill,
        submitCountersign,
        adminGetApprovalContacts,
        adminAddApprovalContact,
        adminUpdateApprovalContact,
        adminDeleteApprovalContact,
        adminSetContactInclude,
        adminGetCompanyVerifications,
        adminSetCompanyVerification,
        adminGetCompanyBackwardNoticeTemplates,
        adminUpsertBackwardNoticeTemplate,
        adminGetCountersignSettings,
        adminSetCountersignSms,
        adminGetParticipationFieldCatalog,
        adminListParticipationTemplates,
        adminGetParticipationTemplate,
        adminCreateParticipationTemplate,
        adminUpdateParticipationTemplate,
        adminDeleteParticipationTemplate,
        adminListParticipationMappings,
        adminUpsertParticipationMapping,
        adminDeleteParticipationMapping,
        adminPreviewParticipationPdf,
        adminListConversionTemplates,
        adminGetConversionTemplate,
        adminListConversionClasses,
        adminMapConversionTemplate,
        adminUnmapConversionTemplate,
    };
})();
