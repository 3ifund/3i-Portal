/**
 * 3i Fund Portal — Admin Dashboard
 * Loads and displays all companies, ELOCs, purchase notices, and user management.
 */

const Admin = (() => {
    // Cached companies list for dropdowns
    let companiesListCache = null;
    // Track if we're editing vs creating
    let editingUserId = null;

    /**
     * Set up tab switching between Companies / ELOCs / Notices / Users.
     */
    function initTabs() {
        const tabs = document.querySelectorAll('.tab');
        const panels = {
            companies: document.getElementById('companies-panel'),
            elocs: document.getElementById('elocs-panel'),
            notices: document.getElementById('notices-panel'),
            users: document.getElementById('users-panel'),
            templates: document.getElementById('templates-panel'),
        };

        tabs.forEach((tab) => {
            tab.addEventListener('click', () => {
                tabs.forEach((t) => t.classList.remove('active'));
                tab.classList.add('active');

                const target = tab.getAttribute('data-tab');
                Object.entries(panels).forEach(([key, panel]) => {
                    if (panel) panel.style.display = key === target ? 'block' : 'none';
                });
            });
        });
    }

    /**
     * Load and render companies table.
     */
    async function loadCompanies() {
        const loading = document.getElementById('companies-loading');
        const table = document.getElementById('companies-table');
        const empty = document.getElementById('companies-empty');
        const tbody = document.getElementById('companies-tbody');

        try {
            const companies = await API.adminGetCompanies();
            loading.style.display = 'none';

            if (!companies || companies.length === 0) {
                empty.style.display = 'block';
                return;
            }

            tbody.innerHTML = '';
            companies.forEach((c) => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${escapeHtml(c.name)}</td>
                    <td>${escapeHtml(String(c.active_elocs || 0))}</td>
                    <td>${escapeHtml(String(c.total_elocs || 0))}</td>
                    <td>${escapeHtml(formatDateTime(c.last_activity))}</td>
                `;
                tbody.appendChild(tr);
            });
            table.style.display = 'table';
        } catch (err) {
            loading.style.display = 'none';
            empty.style.display = 'block';
            empty.querySelector('p').textContent = `Error: ${err.message}`;
        }
    }

    /**
     * Load and render all ELOCs table.
     */
    async function loadElocs() {
        const loading = document.getElementById('elocs-loading');
        const table = document.getElementById('elocs-table');
        const empty = document.getElementById('elocs-empty');
        const tbody = document.getElementById('elocs-tbody');

        try {
            const elocs = await API.adminGetElocs();
            loading.style.display = 'none';

            if (!elocs || elocs.length === 0) {
                empty.style.display = 'block';
                return;
            }

            tbody.innerHTML = '';
            elocs.forEach((e) => {
                const statusClass = e.status === 'active' ? 'active'
                    : e.status === 'rejected' ? 'rejected'
                    : 'completed';

                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td><a href="eloc.html?id=${encodeURIComponent(e.eloc_id)}">${escapeHtml(e.eloc_id)}</a></td>
                    <td>${escapeHtml(e.company_name)}</td>
                    <td>${escapeHtml(e.type || '—')}</td>
                    <td><span class="eloc-card-status ${statusClass}">${escapeHtml(e.status)}</span></td>
                    <td>${escapeHtml(e.current_workflow_step || '—')}</td>
                    <td>${escapeHtml(formatDateTime(e.created_at))}</td>
                `;
                tbody.appendChild(tr);
            });
            table.style.display = 'table';
        } catch (err) {
            loading.style.display = 'none';
            empty.style.display = 'block';
            empty.querySelector('p').textContent = `Error: ${err.message}`;
        }
    }

    /**
     * Load and render purchase notices table.
     */
    async function loadPurchaseNotices() {
        const loading = document.getElementById('notices-loading');
        const table = document.getElementById('notices-table');
        const empty = document.getElementById('notices-empty');
        const tbody = document.getElementById('notices-tbody');

        try {
            const notices = await API.adminGetPurchaseNotices();
            loading.style.display = 'none';

            if (!notices || notices.length === 0) {
                empty.style.display = 'block';
                return;
            }

            tbody.innerHTML = '';
            notices.forEach((n) => {
                const statusClass = n.status === 'acknowledged' ? 'active'
                    : n.status === 'rejected' ? 'rejected'
                    : 'completed';

                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${escapeHtml(n.notice_id || '—')}</td>
                    <td>${escapeHtml(n.company_name)}</td>
                    <td><a href="eloc.html?id=${encodeURIComponent(n.eloc_id)}">${escapeHtml(n.eloc_id)}</a></td>
                    <td>${escapeHtml(formatNumber(n.shares))}</td>
                    <td>${escapeHtml(formatCurrency(n.estimated_value))}</td>
                    <td><span class="eloc-card-status ${statusClass}">${escapeHtml(n.status)}</span></td>
                    <td>${escapeHtml(formatDateTime(n.submitted_at))}</td>
                `;
                tbody.appendChild(tr);
            });
            table.style.display = 'table';
        } catch (err) {
            loading.style.display = 'none';
            empty.style.display = 'block';
            empty.querySelector('p').textContent = `Error: ${err.message}`;
        }
    }

    // ---- Users Tab ----

    /**
     * Load and render users table.
     */
    async function loadUsers() {
        const loading = document.getElementById('users-loading');
        const table = document.getElementById('users-table');
        const empty = document.getElementById('users-empty');
        const tbody = document.getElementById('users-tbody');

        try {
            const users = await API.adminGetUsers();
            loading.style.display = 'none';

            if (!users || users.length === 0) {
                empty.style.display = 'block';
                table.style.display = 'none';
                return;
            }

            empty.style.display = 'none';
            tbody.innerHTML = '';
            users.forEach((u) => {
                const statusClass = u.is_active ? 'active' : 'rejected';
                const statusLabel = u.is_active ? 'Active' : 'Inactive';
                const mustChangeClass = u.must_change_password ? 'completed' : 'active';
                const mustChangeLabel = u.must_change_password ? 'Yes' : 'No';

                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${escapeHtml(u.user_id)}</td>
                    <td>${escapeHtml(u.role)}</td>
                    <td>${escapeHtml(u.company_name || u.company_symbol || '—')}</td>
                    <td><span class="eloc-card-status ${statusClass}">${statusLabel}</span></td>
                    <td><span class="eloc-card-status ${mustChangeClass}">${mustChangeLabel}</span></td>
                    <td>${escapeHtml(formatDateTime(u.created_at))}</td>
                    <td>
                        <button class="btn-action edit-user-btn" data-user-id="${escapeHtml(u.user_id)}">Edit</button>
                        <button class="btn-action reset-pwd-btn" data-user-id="${escapeHtml(u.user_id)}">Reset Pwd</button>
                        <button class="btn-action toggle-active-btn"
                                data-user-id="${escapeHtml(u.user_id)}"
                                data-active="${u.is_active}">${u.is_active ? 'Deactivate' : 'Activate'}</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });

            // Attach action handlers
            tbody.querySelectorAll('.edit-user-btn').forEach((btn) => {
                btn.addEventListener('click', () => openEditUserModal(btn.dataset.userId, users));
            });
            tbody.querySelectorAll('.reset-pwd-btn').forEach((btn) => {
                btn.addEventListener('click', () => openResetPasswordModal(btn.dataset.userId));
            });
            tbody.querySelectorAll('.toggle-active-btn').forEach((btn) => {
                btn.addEventListener('click', () => toggleUserActive(btn.dataset.userId, btn.dataset.active === 'true'));
            });

            table.style.display = 'table';
        } catch (err) {
            loading.style.display = 'none';
            empty.style.display = 'block';
            empty.querySelector('p').textContent = `Error: ${err.message}`;
        }
    }

    /**
     * Fetch and cache companies list for dropdown.
     */
    async function loadCompaniesForDropdown() {
        if (companiesListCache) return companiesListCache;
        try {
            companiesListCache = await API.adminGetCompaniesList();
        } catch {
            companiesListCache = [];
        }
        return companiesListCache;
    }

    /**
     * Populate company dropdown in user modal.
     */
    async function populateCompanyDropdown(selectedId) {
        const select = document.getElementById('user-modal-company');
        const companies = await loadCompaniesForDropdown();

        // Clear existing options except placeholder
        select.innerHTML = '<option value="">-- Select Company --</option>';
        companies.forEach((c) => {
            const opt = document.createElement('option');
            opt.value = c.company_id;
            opt.textContent = `${c.name} (${c.symbol})`;
            if (selectedId && c.company_id === selectedId) opt.selected = true;
            select.appendChild(opt);
        });
    }

    /**
     * Open the user modal for creating a new user.
     */
    function openCreateUserModal() {
        editingUserId = null;
        document.getElementById('user-modal-title').textContent = 'Create User';
        document.getElementById('user-modal-submit').textContent = 'Create';
        document.getElementById('user-modal-id').value = '';
        document.getElementById('user-modal-id').disabled = false;
        document.getElementById('user-modal-password').value = '';
        document.getElementById('user-modal-password-group').style.display = '';
        document.getElementById('user-modal-role').value = 'user';
        document.getElementById('user-modal-company-group').style.display = '';
        document.getElementById('user-modal-active-group').style.display = 'none';
        document.getElementById('user-modal-status').className = 'modal-status';
        document.getElementById('user-modal-status').textContent = '';

        populateCompanyDropdown(null);
        document.getElementById('user-modal-overlay').classList.add('visible');
    }

    /**
     * Open the user modal for editing an existing user.
     */
    function openEditUserModal(userId, usersList) {
        const user = usersList.find((u) => u.user_id === userId);
        if (!user) return;

        editingUserId = userId;
        document.getElementById('user-modal-title').textContent = 'Edit User';
        document.getElementById('user-modal-submit').textContent = 'Save';
        document.getElementById('user-modal-id').value = user.user_id;
        document.getElementById('user-modal-id').disabled = true;
        document.getElementById('user-modal-password-group').style.display = 'none';
        document.getElementById('user-modal-role').value = user.role;
        document.getElementById('user-modal-active-group').style.display = '';
        document.getElementById('user-modal-active').value = String(user.is_active);
        document.getElementById('user-modal-status').className = 'modal-status';
        document.getElementById('user-modal-status').textContent = '';

        const showCompany = user.role !== 'admin';
        document.getElementById('user-modal-company-group').style.display = showCompany ? '' : 'none';
        populateCompanyDropdown(user.company_id);

        document.getElementById('user-modal-overlay').classList.add('visible');
    }

    /**
     * Close the user modal.
     */
    function closeUserModal() {
        document.getElementById('user-modal-overlay').classList.remove('visible');
        editingUserId = null;
    }

    /**
     * Handle user modal submit (create or update).
     */
    async function handleUserModalSubmit() {
        const statusEl = document.getElementById('user-modal-status');
        const submitBtn = document.getElementById('user-modal-submit');

        if (editingUserId) {
            // Update existing user
            const role = document.getElementById('user-modal-role').value;
            const companyId = document.getElementById('user-modal-company').value;
            const isActive = document.getElementById('user-modal-active').value === 'true';

            const updateData = { role, is_active: isActive };
            if (role === 'user' && companyId) {
                updateData.company_id = parseInt(companyId);
            }

            statusEl.className = 'modal-status sending';
            statusEl.textContent = 'Saving...';
            submitBtn.disabled = true;

            try {
                await API.adminUpdateUser(editingUserId, updateData);
                statusEl.className = 'modal-status success';
                statusEl.textContent = 'User updated.';
                setTimeout(() => {
                    closeUserModal();
                    loadUsers();
                }, 800);
            } catch (err) {
                statusEl.className = 'modal-status error';
                statusEl.textContent = err.message || 'Failed to update user.';
            } finally {
                submitBtn.disabled = false;
            }
        } else {
            // Create new user
            const userId = document.getElementById('user-modal-id').value.trim();
            const password = document.getElementById('user-modal-password').value;
            const role = document.getElementById('user-modal-role').value;
            const companyId = document.getElementById('user-modal-company').value;

            if (!userId) {
                statusEl.className = 'modal-status error';
                statusEl.textContent = 'User ID is required.';
                return;
            }
            if (!password || password.length < 8) {
                statusEl.className = 'modal-status error';
                statusEl.textContent = 'Password must be at least 8 characters.';
                return;
            }
            if (role === 'user' && !companyId) {
                statusEl.className = 'modal-status error';
                statusEl.textContent = 'Company is required for user accounts.';
                return;
            }

            const createData = {
                user_id: userId,
                password,
                role,
            };
            if (role === 'user' && companyId) {
                createData.company_id = parseInt(companyId);
            }

            statusEl.className = 'modal-status sending';
            statusEl.textContent = 'Creating user...';
            submitBtn.disabled = true;

            try {
                await API.adminCreateUser(createData);
                statusEl.className = 'modal-status success';
                statusEl.textContent = 'User created.';
                setTimeout(() => {
                    closeUserModal();
                    loadUsers();
                }, 800);
            } catch (err) {
                statusEl.className = 'modal-status error';
                statusEl.textContent = err.message || 'Failed to create user.';
            } finally {
                submitBtn.disabled = false;
            }
        }
    }

    /**
     * Open reset password modal.
     */
    function openResetPasswordModal(userId) {
        document.getElementById('reset-modal-user-id').textContent = userId;
        document.getElementById('reset-modal-password').value = '';
        document.getElementById('reset-modal-status').className = 'modal-status';
        document.getElementById('reset-modal-status').textContent = '';
        document.getElementById('reset-password-modal-overlay').classList.add('visible');
    }

    /**
     * Close reset password modal.
     */
    function closeResetPasswordModal() {
        document.getElementById('reset-password-modal-overlay').classList.remove('visible');
    }

    /**
     * Handle reset password submit.
     */
    async function handleResetPasswordSubmit() {
        const userId = document.getElementById('reset-modal-user-id').textContent;
        const newPassword = document.getElementById('reset-modal-password').value;
        const statusEl = document.getElementById('reset-modal-status');
        const submitBtn = document.getElementById('reset-modal-submit');

        if (!newPassword || newPassword.length < 8) {
            statusEl.className = 'modal-status error';
            statusEl.textContent = 'Password must be at least 8 characters.';
            return;
        }

        statusEl.className = 'modal-status sending';
        statusEl.textContent = 'Resetting password...';
        submitBtn.disabled = true;

        try {
            await API.adminResetPassword(userId, newPassword);
            statusEl.className = 'modal-status success';
            statusEl.textContent = 'Password reset. User will be prompted to change it on next login.';
            setTimeout(() => {
                closeResetPasswordModal();
                loadUsers();
            }, 1500);
        } catch (err) {
            statusEl.className = 'modal-status error';
            statusEl.textContent = err.message || 'Failed to reset password.';
        } finally {
            submitBtn.disabled = false;
        }
    }

    /**
     * Toggle user active/inactive.
     */
    async function toggleUserActive(userId, currentlyActive) {
        const action = currentlyActive ? 'deactivate' : 'activate';
        if (!confirm(`Are you sure you want to ${action} "${userId}"?`)) return;

        try {
            if (currentlyActive) {
                await API.adminDeleteUser(userId);
            } else {
                await API.adminUpdateUser(userId, { is_active: true });
            }
            loadUsers();
        } catch (err) {
            alert(err.message || `Failed to ${action} user.`);
        }
    }

    /**
     * Initialize user management modal event handlers.
     */
    function initUserManagement() {
        // Create user button
        const createBtn = document.getElementById('create-user-btn');
        if (createBtn) createBtn.addEventListener('click', openCreateUserModal);

        // User modal close/cancel
        const userClose = document.getElementById('user-modal-close');
        const userCancel = document.getElementById('user-modal-cancel');
        if (userClose) userClose.addEventListener('click', closeUserModal);
        if (userCancel) userCancel.addEventListener('click', closeUserModal);

        // User modal submit
        const userSubmit = document.getElementById('user-modal-submit');
        if (userSubmit) userSubmit.addEventListener('click', handleUserModalSubmit);

        // Role dropdown toggles company visibility
        const roleSelect = document.getElementById('user-modal-role');
        if (roleSelect) {
            roleSelect.addEventListener('change', () => {
                const companyGroup = document.getElementById('user-modal-company-group');
                companyGroup.style.display = roleSelect.value === 'admin' ? 'none' : '';
            });
        }

        // Reset password modal close/cancel
        const resetClose = document.getElementById('reset-modal-close');
        const resetCancel = document.getElementById('reset-modal-cancel');
        if (resetClose) resetClose.addEventListener('click', closeResetPasswordModal);
        if (resetCancel) resetCancel.addEventListener('click', closeResetPasswordModal);

        // Reset password modal submit
        const resetSubmit = document.getElementById('reset-modal-submit');
        if (resetSubmit) resetSubmit.addEventListener('click', handleResetPasswordSubmit);
    }

    // ---- Notice Templates Tab ----

    let editingPeriodType = null;

    async function loadTemplates() {
        const loading = document.getElementById('templates-loading');
        const table = document.getElementById('templates-table');
        const empty = document.getElementById('templates-empty');
        const tbody = document.getElementById('templates-tbody');

        try {
            const templates = await API.adminGetPurchaseNoticeTemplates();
            loading.style.display = 'none';

            if (!templates || templates.length === 0) {
                empty.style.display = 'block';
                table.style.display = 'none';
                return;
            }

            empty.style.display = 'none';
            tbody.innerHTML = '';
            templates.forEach((t) => {
                const preview = (t.body_text || '').substring(0, 80) + ((t.body_text || '').length > 80 ? '...' : '');
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${escapeHtml(t.pricing_period_type)}</td>
                    <td style="font-size:0.85rem; color:var(--text-secondary);">${escapeHtml(preview)}</td>
                    <td>${escapeHtml(t.agreed_accepted_entity || '—')}</td>
                    <td>
                        <button class="btn-action edit-template-btn" data-period-type="${escapeHtml(t.pricing_period_type)}">Edit</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });

            tbody.querySelectorAll('.edit-template-btn').forEach((btn) => {
                btn.addEventListener('click', () => openTemplateModal(btn.dataset.periodType));
            });

            table.style.display = 'table';
        } catch (err) {
            loading.style.display = 'none';
            empty.style.display = 'block';
            empty.querySelector('p').textContent = `Error: ${err.message}`;
        }
    }

    async function openTemplateModal(periodType) {
        editingPeriodType = periodType || null;
        const titleEl = document.getElementById('template-modal-title');
        const periodSelect = document.getElementById('template-period-type');
        const bodyText = document.getElementById('template-body-text');
        const entity = document.getElementById('template-entity');
        const statusEl = document.getElementById('template-modal-status');

        statusEl.className = 'modal-status';
        statusEl.textContent = '';

        if (periodType) {
            titleEl.textContent = `Edit Template: ${periodType}`;
            periodSelect.value = periodType;
            periodSelect.disabled = true;

            try {
                const template = await API.adminGetPurchaseNoticeTemplates();
                const match = (template || []).find((t) => t.pricing_period_type === periodType);
                bodyText.value = match ? match.body_text || '' : '';
                entity.value = match ? match.agreed_accepted_entity || '' : '';
            } catch {
                bodyText.value = '';
                entity.value = '';
            }
        } else {
            titleEl.textContent = 'Add Template';
            periodSelect.value = '';
            periodSelect.disabled = false;
            bodyText.value = '';
            entity.value = '';
        }

        document.getElementById('template-modal-overlay').classList.add('visible');
    }

    function closeTemplateModal() {
        document.getElementById('template-modal-overlay').classList.remove('visible');
        editingPeriodType = null;
    }

    async function handleTemplateSave() {
        const statusEl = document.getElementById('template-modal-status');
        const submitBtn = document.getElementById('template-modal-submit');

        const periodType = editingPeriodType || document.getElementById('template-period-type').value;
        const bodyText = document.getElementById('template-body-text').value;
        const entity = document.getElementById('template-entity').value.trim();

        if (!periodType) {
            statusEl.className = 'modal-status error';
            statusEl.textContent = 'Please select a period type.';
            return;
        }
        if (!bodyText.trim()) {
            statusEl.className = 'modal-status error';
            statusEl.textContent = 'Body text is required.';
            return;
        }
        if (!entity) {
            statusEl.className = 'modal-status error';
            statusEl.textContent = 'Entity name is required.';
            return;
        }

        statusEl.className = 'modal-status sending';
        statusEl.textContent = 'Saving...';
        submitBtn.disabled = true;

        try {
            await API.adminUpsertPurchaseNoticeTemplate(periodType, {
                body_text: bodyText,
                agreed_accepted_entity: entity,
            });
            statusEl.className = 'modal-status success';
            statusEl.textContent = 'Template saved.';
            setTimeout(() => {
                closeTemplateModal();
                loadTemplates();
            }, 800);
        } catch (err) {
            statusEl.className = 'modal-status error';
            statusEl.textContent = err.message || 'Failed to save template.';
        } finally {
            submitBtn.disabled = false;
        }
    }

    function initTemplateManagement() {
        const addBtn = document.getElementById('add-template-btn');
        if (addBtn) addBtn.addEventListener('click', () => openTemplateModal(null));

        const closeBtn = document.getElementById('template-modal-close');
        const cancelBtn = document.getElementById('template-modal-cancel');
        if (closeBtn) closeBtn.addEventListener('click', closeTemplateModal);
        if (cancelBtn) cancelBtn.addEventListener('click', closeTemplateModal);

        const submitBtn = document.getElementById('template-modal-submit');
        if (submitBtn) submitBtn.addEventListener('click', handleTemplateSave);
    }

    // ---- Utilities ----

    function escapeHtml(str) {
        if (str == null) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }

    function formatDateTime(isoStr) {
        if (!isoStr) return '—';
        const d = new Date(isoStr);
        return d.toLocaleString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    }

    function formatNumber(num) {
        if (num == null || isNaN(num)) return '—';
        return new Intl.NumberFormat('en-US').format(num);
    }

    function formatCurrency(num) {
        if (num == null || isNaN(num)) return '—';
        return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(num);
    }

    // ---- Init ----

    function init() {
        // Verify admin role
        if (!Auth.isAdmin()) {
            window.location.href = 'dashboard.html';
            return;
        }

        // Show admin user ID in navbar
        const adminUserEl = document.getElementById('admin-user-id');
        if (adminUserEl) {
            adminUserEl.textContent = sessionStorage.getItem('user_id') || 'Admin';
        }

        initTabs();
        initUserManagement();
        initTemplateManagement();
        loadCompanies();
        loadElocs();
        loadPurchaseNotices();
        loadUsers();
        loadTemplates();
    }

    document.addEventListener('DOMContentLoaded', init);

    return { init };
})();
