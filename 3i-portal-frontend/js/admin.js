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
            signatories: document.getElementById('signatories-panel'),
            'backward-templates': document.getElementById('backward-templates-panel'),
            'confirm-templates': document.getElementById('confirm-templates-panel'),
            'participation-templates': document.getElementById('participation-templates-panel'),
            verification: document.getElementById('verification-panel'),
        };

        tabs.forEach((tab) => {
            tab.addEventListener('click', () => {
                tabs.forEach((t) => t.classList.remove('active'));
                tab.classList.add('active');

                const target = tab.getAttribute('data-tab');
                Object.entries(panels).forEach(([key, panel]) => {
                    if (panel) panel.style.display = key === target ? 'block' : 'none';
                });

                // Lazily (re)populate the participation company dropdown when its tab is
                // opened. The init-time populate runs asynchronously and can lose a race if
                // the user opens this tab before the company load finishes — which left the
                // dropdown empty until they switched tabs and back. loadElocCompanies() is
                // cached, so this is cheap on every show.
                if (target === 'participation-templates') {
                    populateParticipationCompanyFilter();
                }
            });
        });
    }

    /**
     * Load and render companies table.
     */
    async function loadCompanies() {
        const t = performance.now();
        console.log('[Admin] loadCompanies — START');
        const loading = document.getElementById('companies-loading');
        const table = document.getElementById('companies-table');
        const empty = document.getElementById('companies-empty');
        const tbody = document.getElementById('companies-tbody');

        try {
            const companies = await API.adminGetCompanies();
            console.log('[Admin] loadCompanies — API returned %d companies in %.0fms', companies?.length || 0, performance.now() - t);
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

    // ---- Users Tab ----

    /**
     * Load and render users table.
     */
    async function loadUsers() {
        const t = performance.now();
        console.log('[Admin] loadUsers — START');
        const loading = document.getElementById('users-loading');
        const table = document.getElementById('users-table');
        const empty = document.getElementById('users-empty');
        const tbody = document.getElementById('users-tbody');

        try {
            const users = await API.adminGetUsers();
            console.log('[Admin] loadUsers — API returned %d users in %.0fms', users?.length || 0, performance.now() - t);
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
                    <td>${escapeHtml(u.signatory_name || '—')}</td>
                    <td><span class="eloc-card-status ${statusClass}">${statusLabel}</span></td>
                    <td><span class="eloc-card-status ${mustChangeClass}">${mustChangeLabel}</span></td>
                    <td>${escapeHtml(formatDateTime(u.created_at))}</td>
                    <td>
                        <button class="btn-action edit-user-btn" data-user-id="${escapeHtml(u.user_id)}">Edit</button>
                        <button class="btn-action reset-pwd-btn" data-user-id="${escapeHtml(u.user_id)}">Reset Pwd</button>
                        ${u.role === 'admin' ? '' : `<button class="btn-action toggle-active-btn"
                                data-user-id="${escapeHtml(u.user_id)}"
                                data-active="${u.is_active}">${u.is_active ? 'Deactivate' : 'Activate'}</button>
                            <button class="btn-action delete-user-btn"
                                data-user-id="${escapeHtml(u.user_id)}"
                                style="color:#ef4444;">Delete</button>`}
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
            tbody.querySelectorAll('.delete-user-btn').forEach((btn) => {
                btn.addEventListener('click', () => handleDeleteUser(btn.dataset.userId));
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
        document.getElementById('user-modal-signatory-group').style.display = '';
        document.getElementById('user-modal-signatory-name').value = '';
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
        document.getElementById('user-modal-signatory-group').style.display = showCompany ? '' : 'none';
        document.getElementById('user-modal-signatory-name').value = user.signatory_name || '';
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

            const signatoryName = document.getElementById('user-modal-signatory-name').value.trim();
            const updateData = { role, is_active: isActive, signatory_name: signatoryName };
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

            const signatoryName = document.getElementById('user-modal-signatory-name').value.trim();
            const createData = {
                user_id: userId,
                password,
                role,
                signatory_name: signatoryName,
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

    async function handleDeleteUser(userId) {
        if (!confirm(`PERMANENTLY DELETE user "${userId}"?\n\nThis cannot be undone.`)) return;
        try {
            await API.adminPermanentDeleteUser(userId);
            loadUsers();
        } catch (err) {
            alert(err.message || 'Failed to delete user.');
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
                const isAdmin = roleSelect.value === 'admin';
                document.getElementById('user-modal-company-group').style.display = isAdmin ? 'none' : '';
                document.getElementById('user-modal-signatory-group').style.display = isAdmin ? 'none' : '';
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
    let editingCompanyId = null;
    let elocCompaniesCache = null; // [{company_id, symbol, name, pricing_period_types}]

    async function loadElocCompanies() {
        if (elocCompaniesCache) return elocCompaniesCache;
        try {
            elocCompaniesCache = await API.adminGetCompaniesWithElocs();
        } catch {
            elocCompaniesCache = [];
        }
        return elocCompaniesCache;
    }

    function getSelectedElocCompany() {
        const companyId = document.getElementById('template-company-filter').value;
        if (!companyId || !elocCompaniesCache) return null;
        return elocCompaniesCache.find((c) => String(c.company_id) === String(companyId)) || null;
    }

    async function loadTemplates() {
        const loading = document.getElementById('templates-loading');
        const table = document.getElementById('templates-table');
        const empty = document.getElementById('templates-empty');
        const tbody = document.getElementById('templates-tbody');
        const company = getSelectedElocCompany();

        if (!company) {
            loading.style.display = 'none';
            table.style.display = 'none';
            empty.style.display = 'block';
            empty.querySelector('p').textContent = 'Select a company to view its templates.';
            return;
        }

        loading.style.display = 'flex';
        table.style.display = 'none';
        empty.style.display = 'none';

        try {
            const templates = await API.adminGetCompanyTemplates(company.company_id);
            loading.style.display = 'none';

            if (!templates || templates.length === 0) {
                empty.querySelector('p').textContent = 'No templates configured for this company. Click "+ Add Template" to create one.';
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
                    <td>${escapeHtml(t.agreed_accepted_entity || '\u2014')}</td>
                    <td>
                        <button class="btn-action edit-template-btn"
                            data-period-type="${escapeHtml(t.pricing_period_type)}"
                            data-company-id="${t.company_id || ''}">Edit</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });

            tbody.querySelectorAll('.edit-template-btn').forEach((btn) => {
                btn.addEventListener('click', () => openTemplateModal(btn.dataset.periodType, btn.dataset.companyId || null));
            });

            table.style.display = 'table';
        } catch (err) {
            loading.style.display = 'none';
            empty.style.display = 'block';
            empty.querySelector('p').textContent = `Error: ${err.message}`;
        }
    }

    async function populateTemplateCompanyFilter() {
        const companies = await loadElocCompanies();
        const filter = document.getElementById('template-company-filter');
        if (filter) {
            const existing = filter.value;
            while (filter.options.length > 1) filter.remove(1);
            (companies || []).forEach((c) => {
                const opt = document.createElement('option');
                opt.value = c.company_id;
                opt.textContent = `${c.name} (${c.symbol})`;
                filter.appendChild(opt);
            });
            if (existing) filter.value = existing;
        }
    }

    function populatePeriodTypeDropdown(company, selectedPeriodType) {
        const periodSelect = document.getElementById('template-period-type');
        periodSelect.innerHTML = '<option value="">-- Select Period Type --</option>';
        const periods = company ? company.pricing_period_types || [] : [];
        periods.forEach((pt) => {
            const opt = document.createElement('option');
            opt.value = pt;
            opt.textContent = pt;
            if (pt === selectedPeriodType) opt.selected = true;
            periodSelect.appendChild(opt);
        });
    }

    async function openTemplateModal(periodType, companyId) {
        const company = getSelectedElocCompany();
        if (!company) return;

        editingPeriodType = periodType || null;
        editingCompanyId = company.company_id;

        const titleEl = document.getElementById('template-modal-title');
        const periodSelect = document.getElementById('template-period-type');
        const bodyText = document.getElementById('template-body-text');
        const entity = document.getElementById('template-entity');
        const statusEl = document.getElementById('template-modal-status');

        statusEl.className = 'modal-status';
        statusEl.textContent = '';

        populatePeriodTypeDropdown(company, periodType);

        if (periodType) {
            // Editing existing
            titleEl.textContent = `Edit Template: ${periodType}`;
            periodSelect.disabled = true;

            try {
                const templates = await API.adminGetCompanyTemplates(company.company_id);
                const match = (templates || []).find((t) => t.pricing_period_type === periodType);
                bodyText.value = match ? match.body_text || '' : '';
                entity.value = match ? match.agreed_accepted_entity || '' : '';
            } catch {
                bodyText.value = '';
                entity.value = '';
            }
        } else {
            // Adding new
            titleEl.textContent = 'Add Template';
            periodSelect.disabled = false;
            bodyText.value = '';
            entity.value = '';
        }

        document.getElementById('template-modal-overlay').classList.add('visible');
    }

    function closeTemplateModal() {
        document.getElementById('template-modal-overlay').classList.remove('visible');
        editingPeriodType = null;
        editingCompanyId = null;
    }

    async function handleTemplateSave() {
        const statusEl = document.getElementById('template-modal-status');
        const submitBtn = document.getElementById('template-modal-submit');

        const companyId = editingCompanyId;
        const periodType = editingPeriodType || document.getElementById('template-period-type').value;
        const bodyText = document.getElementById('template-body-text').value;
        const entity = document.getElementById('template-entity').value.trim();

        if (!companyId) {
            statusEl.className = 'modal-status error';
            statusEl.textContent = 'Please select a company.';
            return;
        }
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
            await API.adminUpsertPurchaseNoticeTemplate(companyId, periodType, {
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

    async function initTemplateManagement() {
        const addBtn = document.getElementById('add-template-btn');
        if (addBtn) addBtn.addEventListener('click', () => openTemplateModal(null, null));

        const closeBtn = document.getElementById('template-modal-close');
        const cancelBtn = document.getElementById('template-modal-cancel');
        if (closeBtn) closeBtn.addEventListener('click', closeTemplateModal);
        if (cancelBtn) cancelBtn.addEventListener('click', closeTemplateModal);

        const submitBtn = document.getElementById('template-modal-submit');
        if (submitBtn) submitBtn.addEventListener('click', handleTemplateSave);

        const companyFilter = document.getElementById('template-company-filter');
        if (companyFilter) companyFilter.addEventListener('change', loadTemplates);

        // Populate company filter dropdown
        await populateTemplateCompanyFilter();
    }

    // ---- Backward Notice Templates Tab ----

    let backwardEditingPeriodType = null;
    let backwardEditingCompanyId = null;

    function getSelectedBackwardElocCompany() {
        const companyId = document.getElementById('backward-template-company-filter').value;
        if (!companyId || !elocCompaniesCache) return null;
        return elocCompaniesCache.find((c) => String(c.company_id) === String(companyId)) || null;
    }

    async function loadBackwardTemplates() {
        const loading = document.getElementById('backward-templates-loading');
        const table = document.getElementById('backward-templates-table');
        const empty = document.getElementById('backward-templates-empty');
        const tbody = document.getElementById('backward-templates-tbody');
        const company = getSelectedBackwardElocCompany();

        if (!company) {
            loading.style.display = 'none';
            table.style.display = 'none';
            empty.style.display = 'block';
            empty.querySelector('p').textContent = 'Select a company to view its backward pricing templates.';
            return;
        }

        loading.style.display = 'flex';
        table.style.display = 'none';
        empty.style.display = 'none';

        try {
            const templates = await API.adminGetCompanyBackwardNoticeTemplates(company.company_id);
            loading.style.display = 'none';

            if (!templates || templates.length === 0) {
                empty.querySelector('p').textContent = 'No backward pricing templates configured for this company. Click "+ Add Template" to create one.';
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
                    <td>${escapeHtml(t.agreed_accepted_entity || '\u2014')}</td>
                    <td>
                        <button class="btn-action edit-backward-template-btn"
                            data-period-type="${escapeHtml(t.pricing_period_type)}"
                            data-company-id="${t.company_id || ''}">Edit</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });

            tbody.querySelectorAll('.edit-backward-template-btn').forEach((btn) => {
                btn.addEventListener('click', () => openBackwardTemplateModal(btn.dataset.periodType, btn.dataset.companyId || null));
            });

            table.style.display = 'table';
        } catch (err) {
            loading.style.display = 'none';
            empty.style.display = 'block';
            empty.querySelector('p').textContent = `Error: ${err.message}`;
        }
    }

    async function populateBackwardTemplateCompanyFilter() {
        const companies = await loadElocCompanies();
        const filter = document.getElementById('backward-template-company-filter');
        if (filter) {
            const existing = filter.value;
            while (filter.options.length > 1) filter.remove(1);
            (companies || []).forEach((c) => {
                const opt = document.createElement('option');
                opt.value = c.company_id;
                opt.textContent = `${c.name} (${c.symbol})`;
                filter.appendChild(opt);
            });
            if (existing) filter.value = existing;
        }
    }

    function populateBackwardPeriodTypeDropdown(company, selectedPeriodType) {
        const periodSelect = document.getElementById('backward-template-period-type');
        periodSelect.innerHTML = '<option value="">-- Select Period Type --</option>';
        // Only show backward pricing periods
        const periods = company && company.pricing_periods
            ? company.pricing_periods.filter((p) => p.isBackwardPricing === true)
            : [];
        console.log('[Admin] Backward period types for %s: %o', company?.symbol, periods);
        periods.forEach((p) => {
            const opt = document.createElement('option');
            opt.value = p.periodType;
            opt.textContent = p.periodType;
            if (p.periodType === selectedPeriodType) opt.selected = true;
            periodSelect.appendChild(opt);
        });
    }

    function renderBackwardPlaceholderDropdowns() {
        const bodyText = document.getElementById('backward-template-body-text');
        const container = document.getElementById('backward-template-placeholders');
        const text = bodyText.value;
        const placeholders = detectPlaceholders(text);

        container.innerHTML = '';
        if (placeholders.length === 0) return;

        const heading = document.createElement('p');
        heading.style.cssText = 'font-size:0.85rem; font-weight:600; color:var(--text-secondary); margin-bottom:0.5rem;';
        heading.textContent = `${placeholders.length} placeholder(s) detected — assign fields:`;
        container.appendChild(heading);

        placeholders.forEach((ph, idx) => {
            const row = document.createElement('div');
            row.style.cssText = 'display:flex; align-items:center; gap:0.5rem; margin-bottom:0.4rem;';

            const contextStart = Math.max(0, ph.index - 20);
            const contextEnd = Math.min(text.length, ph.index + ph.length + 20);
            const before = text.substring(contextStart, ph.index).replace(/\n/g, ' ');
            const after = text.substring(ph.index + ph.length, contextEnd).replace(/\n/g, ' ');

            const label = document.createElement('span');
            label.style.cssText = 'font-size:0.8rem; color:var(--text-secondary); min-width:200px; font-family:monospace;';
            label.textContent = `...${before}[___]${after}...`;

            const select = document.createElement('select');
            select.className = 'form-input';
            select.style.cssText = 'font-size:0.85rem; padding:4px 8px; max-width:320px;';

            const emptyOpt = document.createElement('option');
            emptyOpt.value = '';
            emptyOpt.textContent = '-- Select field --';
            select.appendChild(emptyOpt);

            PLACEHOLDER_FIELDS.forEach((f) => {
                const opt = document.createElement('option');
                opt.value = f.tag;
                opt.textContent = f.label;
                if (ph.currentTag === f.tag) opt.selected = true;
                select.appendChild(opt);
            });

            select.addEventListener('change', () => {
                applyBackwardPlaceholderSelection(idx, select.value);
            });

            row.appendChild(label);
            row.appendChild(select);
            container.appendChild(row);
        });
    }

    function applyBackwardPlaceholderSelection(placeholderIdx, tag) {
        const bodyText = document.getElementById('backward-template-body-text');
        const text = bodyText.value;
        const placeholders = detectPlaceholders(text);

        if (placeholderIdx >= placeholders.length) return;
        const ph = placeholders[placeholderIdx];
        if (!tag) return;

        const before = text.substring(0, ph.index);
        const after = text.substring(ph.index + ph.length);
        bodyText.value = before + tag + after;
        renderBackwardPlaceholderDropdowns();
    }

    async function openBackwardTemplateModal(periodType, companyId) {
        const company = getSelectedBackwardElocCompany();
        if (!company) return;

        backwardEditingPeriodType = periodType || null;
        backwardEditingCompanyId = company.company_id;

        const titleEl = document.getElementById('backward-template-modal-title');
        const periodSelect = document.getElementById('backward-template-period-type');
        const bodyText = document.getElementById('backward-template-body-text');
        const entity = document.getElementById('backward-template-entity');
        const statusEl = document.getElementById('backward-template-modal-status');

        statusEl.className = 'modal-status';
        statusEl.textContent = '';

        populateBackwardPeriodTypeDropdown(company, periodType);

        if (periodType) {
            titleEl.textContent = `Edit Backward Template: ${periodType}`;
            periodSelect.disabled = true;

            try {
                const templates = await API.adminGetCompanyBackwardNoticeTemplates(company.company_id);
                const match = (templates || []).find((t) => t.pricing_period_type === periodType);
                bodyText.value = match ? match.body_text || '' : '';
                entity.value = match ? match.agreed_accepted_entity || '' : '';
            } catch {
                bodyText.value = '';
                entity.value = '';
            }
        } else {
            titleEl.textContent = 'Add Backward Template';
            periodSelect.disabled = false;
            bodyText.value = '';
            entity.value = '';
        }

        renderBackwardPlaceholderDropdowns();
        bodyText.removeEventListener('input', renderBackwardPlaceholderDropdowns);
        bodyText.addEventListener('input', renderBackwardPlaceholderDropdowns);

        document.getElementById('backward-template-modal-overlay').classList.add('visible');
    }

    function closeBackwardTemplateModal() {
        document.getElementById('backward-template-modal-overlay').classList.remove('visible');
        backwardEditingPeriodType = null;
        backwardEditingCompanyId = null;
    }

    async function handleBackwardTemplateSave() {
        const statusEl = document.getElementById('backward-template-modal-status');
        const submitBtn = document.getElementById('backward-template-modal-submit');

        const companyId = backwardEditingCompanyId;
        const periodType = backwardEditingPeriodType || document.getElementById('backward-template-period-type').value;
        const bodyText = document.getElementById('backward-template-body-text').value;
        const entity = document.getElementById('backward-template-entity').value.trim();

        if (!companyId) {
            statusEl.className = 'modal-status error';
            statusEl.textContent = 'Please select a company.';
            return;
        }
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
            await API.adminUpsertBackwardNoticeTemplate(companyId, periodType, {
                body_text: bodyText,
                agreed_accepted_entity: entity,
            });
            statusEl.className = 'modal-status success';
            statusEl.textContent = 'Backward template saved.';
            setTimeout(() => {
                closeBackwardTemplateModal();
                loadBackwardTemplates();
            }, 800);
        } catch (err) {
            statusEl.className = 'modal-status error';
            statusEl.textContent = err.message || 'Failed to save template.';
        } finally {
            submitBtn.disabled = false;
        }
    }

    async function initBackwardTemplateManagement() {
        const addBtn = document.getElementById('add-backward-template-btn');
        if (addBtn) addBtn.addEventListener('click', () => openBackwardTemplateModal(null, null));

        const closeBtn = document.getElementById('backward-template-modal-close');
        const cancelBtn = document.getElementById('backward-template-modal-cancel');
        if (closeBtn) closeBtn.addEventListener('click', closeBackwardTemplateModal);
        if (cancelBtn) cancelBtn.addEventListener('click', closeBackwardTemplateModal);

        const submitBtn = document.getElementById('backward-template-modal-submit');
        if (submitBtn) submitBtn.addEventListener('click', handleBackwardTemplateSave);

        const companyFilter = document.getElementById('backward-template-company-filter');
        if (companyFilter) companyFilter.addEventListener('change', loadBackwardTemplates);

        await populateBackwardTemplateCompanyFilter();
    }

    // ---- Confirmation Templates Tab ----

    let confirmEditingPeriodType = null;
    let confirmEditingCompanyId = null;

    function getSelectedConfirmElocCompany() {
        const companyId = document.getElementById('confirm-template-company-filter').value;
        if (!companyId || !elocCompaniesCache) return null;
        return elocCompaniesCache.find((c) => String(c.company_id) === String(companyId)) || null;
    }

    async function loadConfirmationTemplates() {
        const loading = document.getElementById('confirm-templates-loading');
        const table = document.getElementById('confirm-templates-table');
        const empty = document.getElementById('confirm-templates-empty');
        const tbody = document.getElementById('confirm-templates-tbody');
        const company = getSelectedConfirmElocCompany();

        if (!company) {
            loading.style.display = 'none';
            table.style.display = 'none';
            empty.style.display = 'block';
            empty.querySelector('p').textContent = 'Select a company to view its purchase confirmation templates.';
            return;
        }

        loading.style.display = 'flex';
        table.style.display = 'none';
        empty.style.display = 'none';

        try {
            const templates = await API.adminGetCompanyConfirmationTemplates(company.company_id);
            loading.style.display = 'none';

            if (!templates || templates.length === 0) {
                empty.querySelector('p').textContent = 'No confirmation templates configured for this company. Click "+ Add Template" to create one.';
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
                    <td>${escapeHtml(t.agreed_accepted_entity || '\u2014')}</td>
                    <td>
                        <button class="btn-action edit-confirm-template-btn"
                            data-period-type="${escapeHtml(t.pricing_period_type)}"
                            data-company-id="${t.company_id || ''}">Edit</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });

            tbody.querySelectorAll('.edit-confirm-template-btn').forEach((btn) => {
                btn.addEventListener('click', () => openConfirmTemplateModal(btn.dataset.periodType, btn.dataset.companyId || null));
            });

            table.style.display = 'table';
        } catch (err) {
            loading.style.display = 'none';
            empty.style.display = 'block';
            empty.querySelector('p').textContent = `Error: ${err.message}`;
        }
    }

    async function populateConfirmTemplateCompanyFilter() {
        const companies = await loadElocCompanies();
        const filter = document.getElementById('confirm-template-company-filter');
        if (filter) {
            const existing = filter.value;
            while (filter.options.length > 1) filter.remove(1);
            (companies || []).forEach((c) => {
                const opt = document.createElement('option');
                opt.value = c.company_id;
                opt.textContent = `${c.name} (${c.symbol})`;
                filter.appendChild(opt);
            });
            if (existing) filter.value = existing;
        }
    }

    function populateConfirmPeriodTypeDropdown(company, selectedPeriodType) {
        const periodSelect = document.getElementById('confirm-template-period-type');
        periodSelect.innerHTML = '<option value="">-- Select Period Type --</option>';
        const periods = company ? company.pricing_period_types || [] : [];
        periods.forEach((pt) => {
            const opt = document.createElement('option');
            opt.value = pt;
            opt.textContent = pt;
            if (pt === selectedPeriodType) opt.selected = true;
            periodSelect.appendChild(opt);
        });
    }

    // ---- Confirmation Template Placeholder Detection ----

    const PLACEHOLDER_FIELDS = [
        { tag: '{{shares}}', label: 'VWAP Purchase Share Amount (number of Shares)' },
        { tag: '{{exercise_date}}', label: 'VWAP Purchase Exercise Date' },
        { tag: '{{valuation_period_start}}', label: 'Valuation Period start date' },
        { tag: '{{valuation_period_end}}', label: 'Valuation Period end date' },
        { tag: '{{settlement_date}}', label: 'VWAP Purchase Settlement Date' },
        { tag: '{{vwap_purchase_price}}', label: 'VWAP Purchase Price (per Share)' },
        { tag: '{{dollar_amount_calculated}}', label: 'Aggregate VWAP Purchase Price' },
    ];

    /**
     * Scan body text for underscore sequences (blanks) and existing {{tags}}.
     * Returns array of { index, length, currentTag } for each placeholder found.
     */
    function detectPlaceholders(text) {
        const placeholders = [];
        // Match underscore sequences (3+) or existing {{tag}} placeholders
        const regex = /_{3,}|\{\{[a-z_]+\}\}/g;
        let match;
        while ((match = regex.exec(text)) !== null) {
            const isTag = match[0].startsWith('{{');
            placeholders.push({
                index: match.index,
                length: match[0].length,
                raw: match[0],
                currentTag: isTag ? match[0] : null,
            });
        }
        return placeholders;
    }

    /**
     * Render placeholder dropdowns below the body text textarea.
     */
    function renderPlaceholderDropdowns() {
        const bodyText = document.getElementById('confirm-template-body-text');
        const container = document.getElementById('confirm-template-placeholders');
        const text = bodyText.value;
        const placeholders = detectPlaceholders(text);

        container.innerHTML = '';
        if (placeholders.length === 0) return;

        const heading = document.createElement('p');
        heading.style.cssText = 'font-size:0.85rem; font-weight:600; color:var(--text-secondary); margin-bottom:0.5rem;';
        heading.textContent = `${placeholders.length} placeholder(s) detected — assign fields:`;
        container.appendChild(heading);

        placeholders.forEach((ph, idx) => {
            const row = document.createElement('div');
            row.style.cssText = 'display:flex; align-items:center; gap:0.5rem; margin-bottom:0.4rem;';

            // Context preview: show surrounding text
            const contextStart = Math.max(0, ph.index - 20);
            const contextEnd = Math.min(text.length, ph.index + ph.length + 20);
            const before = text.substring(contextStart, ph.index).replace(/\n/g, ' ');
            const after = text.substring(ph.index + ph.length, contextEnd).replace(/\n/g, ' ');

            const label = document.createElement('span');
            label.style.cssText = 'font-size:0.8rem; color:var(--text-secondary); min-width:200px; font-family:monospace;';
            label.textContent = `...${before}[___]${after}...`;

            const select = document.createElement('select');
            select.className = 'form-input';
            select.style.cssText = 'font-size:0.85rem; padding:4px 8px; max-width:320px;';
            select.dataset.placeholderIndex = idx;

            const emptyOpt = document.createElement('option');
            emptyOpt.value = '';
            emptyOpt.textContent = '-- Select field --';
            select.appendChild(emptyOpt);

            PLACEHOLDER_FIELDS.forEach((f) => {
                const opt = document.createElement('option');
                opt.value = f.tag;
                opt.textContent = f.label;
                if (ph.currentTag === f.tag) opt.selected = true;
                select.appendChild(opt);
            });

            select.addEventListener('change', () => {
                applyPlaceholderSelection(idx, select.value);
            });

            row.appendChild(label);
            row.appendChild(select);
            container.appendChild(row);
        });
    }

    /**
     * Replace the placeholder at the given index with the selected tag.
     */
    function applyPlaceholderSelection(placeholderIdx, tag) {
        const bodyText = document.getElementById('confirm-template-body-text');
        const text = bodyText.value;
        const placeholders = detectPlaceholders(text);

        if (placeholderIdx >= placeholders.length) return;
        const ph = placeholders[placeholderIdx];

        if (!tag) return; // No selection — leave as-is

        const before = text.substring(0, ph.index);
        const after = text.substring(ph.index + ph.length);
        bodyText.value = before + tag + after;

        // Re-render dropdowns with updated text
        renderPlaceholderDropdowns();
    }

    async function openConfirmTemplateModal(periodType, companyId) {
        const company = getSelectedConfirmElocCompany();
        if (!company) return;

        confirmEditingPeriodType = periodType || null;
        confirmEditingCompanyId = company.company_id;

        const titleEl = document.getElementById('confirm-template-modal-title');
        const periodSelect = document.getElementById('confirm-template-period-type');
        const bodyText = document.getElementById('confirm-template-body-text');
        const entity = document.getElementById('confirm-template-entity');
        const statusEl = document.getElementById('confirm-template-modal-status');

        statusEl.className = 'modal-status';
        statusEl.textContent = '';

        populateConfirmPeriodTypeDropdown(company, periodType);

        if (periodType) {
            titleEl.textContent = `Edit Confirmation Template: ${periodType}`;
            periodSelect.disabled = true;

            try {
                const templates = await API.adminGetCompanyConfirmationTemplates(company.company_id);
                const match = (templates || []).find((t) => t.pricing_period_type === periodType);
                bodyText.value = match ? match.body_text || '' : '';
                entity.value = match ? match.agreed_accepted_entity || '' : '';
            } catch {
                bodyText.value = '';
                entity.value = '';
            }
        } else {
            titleEl.textContent = 'Add Confirmation Template';
            periodSelect.disabled = false;
            bodyText.value = '';
            entity.value = '';
        }

        // Detect and render placeholder dropdowns
        renderPlaceholderDropdowns();

        // Re-detect when body text changes
        bodyText.removeEventListener('input', renderPlaceholderDropdowns);
        bodyText.addEventListener('input', renderPlaceholderDropdowns);

        document.getElementById('confirm-template-modal-overlay').classList.add('visible');
    }

    function closeConfirmTemplateModal() {
        document.getElementById('confirm-template-modal-overlay').classList.remove('visible');
        confirmEditingPeriodType = null;
        confirmEditingCompanyId = null;
    }

    async function handleConfirmTemplateSave() {
        const statusEl = document.getElementById('confirm-template-modal-status');
        const submitBtn = document.getElementById('confirm-template-modal-submit');

        const companyId = confirmEditingCompanyId;
        const periodType = confirmEditingPeriodType || document.getElementById('confirm-template-period-type').value;
        const bodyText = document.getElementById('confirm-template-body-text').value;
        const entity = document.getElementById('confirm-template-entity').value.trim();

        if (!companyId) {
            statusEl.className = 'modal-status error';
            statusEl.textContent = 'Please select a company.';
            return;
        }
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
            await API.adminUpsertPurchaseConfirmationTemplate(companyId, periodType, {
                body_text: bodyText,
                agreed_accepted_entity: entity,
            });
            statusEl.className = 'modal-status success';
            statusEl.textContent = 'Confirmation template saved.';
            setTimeout(() => {
                closeConfirmTemplateModal();
                loadConfirmationTemplates();
            }, 800);
        } catch (err) {
            statusEl.className = 'modal-status error';
            statusEl.textContent = err.message || 'Failed to save template.';
        } finally {
            submitBtn.disabled = false;
        }
    }

    async function initConfirmTemplateManagement() {
        const addBtn = document.getElementById('add-confirm-template-btn');
        if (addBtn) addBtn.addEventListener('click', () => openConfirmTemplateModal(null, null));

        const closeBtn = document.getElementById('confirm-template-modal-close');
        const cancelBtn = document.getElementById('confirm-template-modal-cancel');
        if (closeBtn) closeBtn.addEventListener('click', closeConfirmTemplateModal);
        if (cancelBtn) cancelBtn.addEventListener('click', closeConfirmTemplateModal);

        const submitBtn = document.getElementById('confirm-template-modal-submit');
        if (submitBtn) submitBtn.addEventListener('click', handleConfirmTemplateSave);

        const companyFilter = document.getElementById('confirm-template-company-filter');
        if (companyFilter) companyFilter.addEventListener('change', loadConfirmationTemplates);

        await populateConfirmTemplateCompanyFilter();
    }

    // ---- Verification Settings Tab ----

    let editingContactId = null;

    async function loadApprovalContacts() {
        const loading = document.getElementById('contacts-loading');
        const table = document.getElementById('contacts-table');
        const empty = document.getElementById('contacts-empty');
        const tbody = document.getElementById('contacts-tbody');

        loading.style.display = 'flex';
        table.style.display = 'none';
        empty.style.display = 'none';

        try {
            const contacts = await API.adminGetApprovalContacts();
            loading.style.display = 'none';

            if (!contacts || contacts.length === 0) {
                empty.style.display = 'block';
                table.style.display = 'none';
                return;
            }

            empty.style.display = 'none';
            tbody.innerHTML = '';
            contacts.forEach((c) => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${escapeHtml(c.name)}</td>
                    <td>${escapeHtml(c.phone_number)}</td>
                    <td><input type="checkbox" class="contact-include-cb" data-id="${c.id}" ${c.include ? 'checked' : ''}></td>
                    <td>
                        <button class="btn-action" onclick="document.dispatchEvent(new CustomEvent('edit-contact', {detail: ${c.id}}))">Edit</button>
                        <button class="btn-action btn-action-danger" onclick="document.dispatchEvent(new CustomEvent('delete-contact', {detail: ${c.id}}))">Delete</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });

            // Bind include checkboxes
            tbody.querySelectorAll('.contact-include-cb').forEach((cb) => {
                cb.addEventListener('change', async () => {
                    try {
                        await API.adminSetContactInclude(parseInt(cb.dataset.id), cb.checked);
                    } catch (err) {
                        alert('Failed to update: ' + (err.message || err));
                        cb.checked = !cb.checked;
                    }
                });
            });

            table.style.display = '';

            // Store contacts for edit lookups
            table._contacts = contacts;
        } catch (err) {
            loading.style.display = 'none';
            empty.querySelector('p').textContent = 'Error: ' + (err.message || err);
            empty.style.display = 'block';
        }
    }

    async function loadCompanyVerifications() {
        const loading = document.getElementById('verifications-loading');
        const table = document.getElementById('verifications-table');
        const tbody = document.getElementById('verifications-tbody');

        loading.style.display = 'flex';
        table.style.display = 'none';

        try {
            const companies = await API.adminGetCompanyVerifications();
            loading.style.display = 'none';

            if (!companies || companies.length === 0) {
                return;
            }

            tbody.innerHTML = '';
            companies.forEach((c) => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${escapeHtml(c.name)}</td>
                    <td>${escapeHtml(c.symbol)}</td>
                    <td><input type="checkbox" class="verification-cb" data-id="${c.company_id}" ${c.require_verification ? 'checked' : ''}></td>
                `;
                tbody.appendChild(tr);
            });

            // Bind verification checkboxes
            tbody.querySelectorAll('.verification-cb').forEach((cb) => {
                cb.addEventListener('change', async () => {
                    try {
                        await API.adminSetCompanyVerification(parseInt(cb.dataset.id), cb.checked);
                    } catch (err) {
                        alert('Failed to update: ' + (err.message || err));
                        cb.checked = !cb.checked;
                    }
                });
            });

            table.style.display = '';
        } catch (err) {
            loading.style.display = 'none';
        }
    }

    async function loadCountersignSettings() {
        const loading = document.getElementById('countersign-settings-loading');
        const table = document.getElementById('countersign-settings-table');
        const tbody = document.getElementById('countersign-settings-tbody');

        loading.style.display = 'flex';
        table.style.display = 'none';

        try {
            const companies = await API.adminGetCountersignSettings();
            loading.style.display = 'none';

            if (!companies || companies.length === 0) {
                return;
            }

            tbody.innerHTML = '';
            companies.forEach((c) => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${escapeHtml(c.name)}</td>
                    <td>${escapeHtml(c.symbol)}</td>
                    <td><input type="checkbox" class="countersign-sms-cb" data-id="${c.company_id}" ${c.enable_countersign_sms ? 'checked' : ''}></td>
                `;
                tbody.appendChild(tr);
            });

            // Bind countersign SMS checkboxes
            tbody.querySelectorAll('.countersign-sms-cb').forEach((cb) => {
                cb.addEventListener('change', async () => {
                    try {
                        await API.adminSetCountersignSms(parseInt(cb.dataset.id), cb.checked);
                    } catch (err) {
                        alert('Failed to update: ' + (err.message || err));
                        cb.checked = !cb.checked;
                    }
                });
            });

            table.style.display = '';
        } catch (err) {
            loading.style.display = 'none';
        }
    }

    function openContactModal(contactId, contacts) {
        editingContactId = contactId;
        const titleEl = document.getElementById('contact-modal-title');
        const submitBtn = document.getElementById('contact-modal-submit');
        const nameInput = document.getElementById('contact-name-input');
        const phoneInput = document.getElementById('contact-phone-input');
        const statusEl = document.getElementById('contact-modal-status');

        statusEl.className = 'modal-status';
        statusEl.textContent = '';

        if (contactId && contacts) {
            const contact = contacts.find((c) => c.id === contactId);
            titleEl.textContent = 'Edit Contact';
            submitBtn.textContent = 'Save';
            nameInput.value = contact ? contact.name : '';
            phoneInput.value = contact ? contact.phone_number : '';
        } else {
            titleEl.textContent = 'Add Contact';
            submitBtn.textContent = 'Add';
            nameInput.value = '';
            phoneInput.value = '';
        }

        document.getElementById('contact-modal-overlay').classList.add('visible');
        nameInput.focus();
    }

    function closeContactModal() {
        editingContactId = null;
        document.getElementById('contact-modal-overlay').classList.remove('visible');
    }

    async function handleContactSave() {
        const statusEl = document.getElementById('contact-modal-status');
        const submitBtn = document.getElementById('contact-modal-submit');
        const name = document.getElementById('contact-name-input').value.trim();
        const phone = document.getElementById('contact-phone-input').value.trim();

        if (!name || !phone) {
            statusEl.className = 'modal-status error';
            statusEl.textContent = 'Name and phone number are required.';
            return;
        }

        submitBtn.disabled = true;
        statusEl.className = 'modal-status';
        statusEl.textContent = '';

        try {
            if (editingContactId) {
                await API.adminUpdateApprovalContact(editingContactId, name, phone);
                statusEl.className = 'modal-status success';
                statusEl.textContent = 'Contact updated.';
            } else {
                await API.adminAddApprovalContact(name, phone);
                statusEl.className = 'modal-status success';
                statusEl.textContent = 'Contact added.';
            }
            setTimeout(() => {
                closeContactModal();
                loadApprovalContacts();
            }, 600);
        } catch (err) {
            statusEl.className = 'modal-status error';
            statusEl.textContent = err.message || 'Failed.';
        } finally {
            submitBtn.disabled = false;
        }
    }

    async function handleDeleteContact(contactId) {
        if (!confirm('Delete this approval contact?')) return;
        try {
            await API.adminDeleteApprovalContact(contactId);
            loadApprovalContacts();
        } catch (err) {
            alert(err.message || 'Failed to delete contact.');
        }
    }

    function initVerificationManagement() {
        const addBtn = document.getElementById('add-contact-btn');
        if (addBtn) addBtn.addEventListener('click', () => openContactModal(null, null));

        const closeBtn = document.getElementById('contact-modal-close');
        const cancelBtn = document.getElementById('contact-modal-cancel');
        if (closeBtn) closeBtn.addEventListener('click', closeContactModal);
        if (cancelBtn) cancelBtn.addEventListener('click', closeContactModal);

        const submitBtn = document.getElementById('contact-modal-submit');
        if (submitBtn) submitBtn.addEventListener('click', handleContactSave);

        // Custom events for edit/delete from table buttons
        document.addEventListener('edit-contact', (e) => {
            const contactId = e.detail;
            const table = document.getElementById('contacts-table');
            openContactModal(contactId, table._contacts || []);
        });

        document.addEventListener('delete-contact', (e) => {
            handleDeleteContact(e.detail);
        });

        loadApprovalContacts();
        loadCompanyVerifications();
        loadCountersignSettings();
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

    async function init() {
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

        const t0 = performance.now();
        console.log('[Admin] init() — START');

        initTabs();
        initUserManagement();
        initVerificationManagement();

        // Fire visible data loads immediately (don't wait for template inits)
        console.log('[Admin] init() — dispatching data loads (companies, users)...');
        loadCompanies();
        loadUsers();
        console.log('[Admin] init() — data loads dispatched in %.0fms', performance.now() - t0);

        // Template inits run in background (they call slow companies-with-elocs)
        const t1 = performance.now();
        console.log('[Admin] init() — loading ELOC companies + template tabs in background...');
        loadElocCompanies().then(() => {
            console.log('[Admin] init() — ELOC companies loaded in %.0fms', performance.now() - t1);
            return Promise.all([
                initTemplateManagement(),
                initBackwardTemplateManagement(),
                initConfirmTemplateManagement(),
                initParticipationTemplates(),
            ]);
        }).then(() => {
            console.log('[Admin] init() — template tabs initialized in %.0fms', performance.now() - t1);
        });

        console.log('[Admin] init() — TOTAL sync init time: %.0fms', performance.now() - t0);
    }

    // ---- Participation Templates Tab ----

    let participationEditingTemplateId = null;
    const participationCatalogCache = {};   // documentType -> [descriptors]
    let participationTemplatesCache = [];    // current company+docType templates

    function getParticipationDocType() {
        const el = document.getElementById('participation-doctype-filter');
        return el ? el.value : 'PurchaseNotice';
    }

    function getParticipationSelectedCompany() {
        const companyId = document.getElementById('participation-company-filter').value;
        if (!companyId || !elocCompaniesCache) return null;
        return elocCompaniesCache.find((c) => String(c.company_id) === String(companyId)) || null;
    }

    async function loadParticipationCatalog(documentType) {
        if (participationCatalogCache[documentType]) return participationCatalogCache[documentType];
        const catalog = await API.adminGetParticipationFieldCatalog(documentType);
        participationCatalogCache[documentType] = catalog || [];
        return participationCatalogCache[documentType];
    }

    async function populateParticipationCompanyFilter() {
        const companies = await loadElocCompanies();
        const filter = document.getElementById('participation-company-filter');
        if (filter) {
            const existing = filter.value;
            while (filter.options.length > 1) filter.remove(1);
            (companies || []).forEach((c) => {
                const opt = document.createElement('option');
                opt.value = c.company_id;
                opt.textContent = `${c.name} (${c.symbol})`;
                filter.appendChild(opt);
            });
            if (existing) filter.value = existing;
        }
    }

    async function loadParticipationTemplates() {
        const loading = document.getElementById('participation-templates-loading');
        const table = document.getElementById('participation-templates-table');
        const empty = document.getElementById('participation-templates-empty');
        const tbody = document.getElementById('participation-templates-tbody');
        const company = getParticipationSelectedCompany();
        const docType = getParticipationDocType();

        if (!company) {
            loading.style.display = 'none';
            table.style.display = 'none';
            empty.style.display = 'block';
            empty.querySelector('p').textContent = 'Select a company to view its participation templates.';
            participationTemplatesCache = [];
            await loadParticipationMappings();
            return;
        }

        loading.style.display = 'flex';
        table.style.display = 'none';
        empty.style.display = 'none';

        try {
            const templates = await API.adminListParticipationTemplates(company.company_id, docType);
            participationTemplatesCache = templates || [];
            loading.style.display = 'none';

            if (!templates || templates.length === 0) {
                empty.querySelector('p').textContent = 'No participation templates for this company / document type. Click "+ Add Template" to create one.';
                empty.style.display = 'block';
                table.style.display = 'none';
            } else {
                tbody.innerHTML = '';
                templates.forEach((t) => {
                    const body = t.body_text || '';
                    const preview = body.substring(0, 70) + (body.length > 70 ? '...' : '');
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td>${escapeHtml(t.name || '—')}</td>
                        <td>${(t.fields || []).length}</td>
                        <td style="font-size:0.85rem; color:var(--text-secondary);">${escapeHtml(preview)}</td>
                        <td>
                            <button class="btn-action edit-participation-template-btn" data-template-id="${escapeHtml(t.template_id)}">Edit</button>
                            <button class="btn-action delete-participation-template-btn" data-template-id="${escapeHtml(t.template_id)}">Delete</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
                tbody.querySelectorAll('.edit-participation-template-btn').forEach((btn) => {
                    btn.addEventListener('click', () => openParticipationTemplateModal(btn.dataset.templateId));
                });
                tbody.querySelectorAll('.delete-participation-template-btn').forEach((btn) => {
                    btn.addEventListener('click', () => handleParticipationTemplateDelete(btn.dataset.templateId));
                });
                table.style.display = 'table';
            }
        } catch (err) {
            loading.style.display = 'none';
            empty.style.display = 'block';
            empty.querySelector('p').textContent = `Error: ${err.message}`;
        }
        await loadParticipationMappings();
    }

    async function loadParticipationMappings() {
        const table = document.getElementById('participation-mappings-table');
        const empty = document.getElementById('participation-mappings-empty');
        const tbody = document.getElementById('participation-mappings-tbody');
        const company = getParticipationSelectedCompany();
        const docType = getParticipationDocType();

        if (!company) {
            table.style.display = 'none';
            empty.style.display = 'block';
            empty.querySelector('p').textContent = 'Select a company to view its pricing-period mappings.';
            return;
        }
        try {
            const mappings = await API.adminListParticipationMappings(company.company_id, docType);
            if (!mappings || mappings.length === 0) {
                table.style.display = 'none';
                empty.querySelector('p').textContent = 'No pricing-period mappings for this company / document type.';
                empty.style.display = 'block';
                return;
            }
            const byId = {};
            participationTemplatesCache.forEach((t) => { byId[t.template_id] = t; });
            tbody.innerHTML = '';
            mappings.forEach((m) => {
                const tmpl = byId[m.template_id];
                const name = tmpl ? tmpl.name : `(template ${String(m.template_id).substring(0, 8)}…)`;
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${escapeHtml(m.pricing_period_type)}</td>
                    <td>${escapeHtml(name)}</td>
                    <td><button class="btn-action delete-participation-mapping-btn" data-period="${escapeHtml(m.pricing_period_type)}">Remove</button></td>
                `;
                tbody.appendChild(tr);
            });
            tbody.querySelectorAll('.delete-participation-mapping-btn').forEach((btn) => {
                btn.addEventListener('click', () => handleParticipationMappingDelete(btn.dataset.period));
            });
            empty.style.display = 'none';
            table.style.display = 'table';
        } catch (err) {
            table.style.display = 'none';
            empty.style.display = 'block';
            empty.querySelector('p').textContent = `Error: ${err.message}`;
        }
    }

    function renderParticipationFieldRow(descriptor, fieldData) {
        const container = document.getElementById('participation-fields-container');
        const key = descriptor.key;
        if (container.querySelector(`[data-field-key="${key}"]`)) return; // no duplicate fields
        const row = document.createElement('div');
        row.className = 'participation-field-row';
        row.setAttribute('data-field-key', key);
        row.style.cssText = 'display:flex; align-items:center; gap:0.5rem; padding:0.4rem 0; border-bottom:1px solid var(--border, #2a2a2a);';
        const badges = [descriptor.renderType, descriptor.source].filter(Boolean).join(' · ');
        // Show the checkbox/option choices (e.g. Types of Purchase → 1-Day, 2-Day, …)
        const opts = (descriptor.options && descriptor.options.length)
            ? ` · options: ${descriptor.options.join(', ')}` : '';
        const cond = descriptor.conditionalOn ? ` · if ${descriptor.conditionalOn}` : '';
        const visible = fieldData ? fieldData.visible !== false : true;
        const labelVal = (fieldData && fieldData.label) || descriptor.defaultLabel || key;
        // For a multi-select catalog field (e.g. Types of Purchase) the admin picks ONE
        // option, which renders as the single checked box on the document. Options are the
        // fixed enum labels (1-Day/2-Day/3-Day/Intraday Purchase) — no quotes, safe inline.
        const isCheckbox = descriptor.renderType === 'CheckboxGroup'
            && Array.isArray(descriptor.options) && descriptor.options.length > 0;
        const optionSelectHtml = isCheckbox
            ? `<select class="form-input participation-field-option" title="Checked option" style="flex:0 1 160px;">`
              + `<option value="">— choose one —</option>`
              + descriptor.options.map((o) => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join('')
              + `</select>`
            : '';
        row.innerHTML = `
            <span style="min-width:170px; font-size:0.85rem;" title="${escapeHtml(key)}">${escapeHtml(key)}</span>
            <input type="text" class="form-input participation-field-label" style="flex:1;" placeholder="label">
            <input type="text" class="form-input participation-field-note" style="flex:1;" placeholder="note beside value (optional)">
            ${optionSelectHtml}
            <label style="font-size:0.8rem; display:flex; align-items:center; gap:0.25rem; white-space:nowrap;">
                <input type="checkbox" class="participation-field-visible" ${visible ? 'checked' : ''}> visible
            </label>
            <span style="font-size:0.72rem; color:var(--text-secondary); min-width:150px;">${escapeHtml(badges + opts + cond)}</span>
            <button type="button" class="btn-action participation-field-remove">Remove</button>
        `;
        // Set label + note (and the checked option) as DOM properties so values
        // containing quotes can't break out of the markup — escapeHtml does not
        // escape quote characters.
        row.querySelector('.participation-field-label').value = labelVal;
        row.querySelector('.participation-field-note').value = (fieldData && fieldData.note) || '';
        const optionSelect = row.querySelector('.participation-field-option');
        if (optionSelect && fieldData && fieldData.options_config && fieldData.options_config.selected) {
            optionSelect.value = fieldData.options_config.selected;
        }
        row.querySelector('.participation-field-remove').addEventListener('click', () => row.remove());
        container.appendChild(row);
    }

    function setParticipationAllocationType(value) {
        // Absent ⇒ legacy/Known.
        const v = (value === 'Unknown') ? 'Unknown' : 'Known';
        const radio = document.querySelector(`input[name="participation-allocation-type"][value="${v}"]`);
        if (radio) radio.checked = true;
    }

    function getParticipationAllocationType() {
        return document.querySelector('input[name="participation-allocation-type"]:checked')?.value || 'Known';
    }

    function collectParticipationFields() {
        const rows = document.querySelectorAll('#participation-fields-container .participation-field-row');
        const fields = [];
        rows.forEach((row, idx) => {
            const field = {
                key: row.getAttribute('data-field-key'),
                label: row.querySelector('.participation-field-label').value.trim(),
                note: row.querySelector('.participation-field-note').value.trim(),
                visible: row.querySelector('.participation-field-visible').checked,
                order: idx,
            };
            // CheckboxGroup fields carry the single checked option in options_config.
            const optionSelect = row.querySelector('.participation-field-option');
            if (optionSelect) field.options_config = { selected: optionSelect.value || null };
            fields.push(field);
        });
        return fields;
    }

    async function openParticipationTemplateModal(templateId) {
        participationEditingTemplateId = templateId || null;
        const company = getParticipationSelectedCompany();
        const docType = getParticipationDocType();
        if (!company) { alert('Select a company first.'); return; }

        const titleEl = document.getElementById('participation-template-modal-title');
        const nameEl = document.getElementById('participation-template-name');
        const bodyEl = document.getElementById('participation-template-body-text');
        const entityEl = document.getElementById('participation-template-entity');
        const statusEl = document.getElementById('participation-template-modal-status');
        const contextEl = document.getElementById('participation-template-context');
        const fieldsContainer = document.getElementById('participation-fields-container');

        statusEl.textContent = '';
        fieldsContainer.innerHTML = '';
        contextEl.textContent = `${docType} · ${company.name} (${company.symbol})`;

        const catalog = await loadParticipationCatalog(docType);
        const fieldSelect = document.getElementById('participation-field-select');
        fieldSelect.innerHTML = '<option value="">-- Select a field to add --</option>';
        catalog.forEach((d) => {
            const opt = document.createElement('option');
            opt.value = d.key;
            opt.textContent = d.defaultLabel;
            fieldSelect.appendChild(opt);
        });

        if (participationEditingTemplateId) {
            titleEl.textContent = 'Edit Participation Template';
            const tmpl = participationTemplatesCache.find((t) => t.template_id === participationEditingTemplateId)
                || await API.adminGetParticipationTemplate(participationEditingTemplateId);
            nameEl.value = tmpl.name || '';
            bodyEl.value = tmpl.body_text || '';
            entityEl.value = tmpl.agreed_accepted_entity || '';
            setParticipationAllocationType(tmpl.allocation_type);
            const byKey = {};
            catalog.forEach((d) => { byKey[d.key] = d; });
            (tmpl.fields || []).slice().sort((a, b) => (a.order || 0) - (b.order || 0)).forEach((f) => {
                const descriptor = byKey[f.key] || { key: f.key, defaultLabel: f.key, renderType: '', source: '' };
                renderParticipationFieldRow(descriptor, f);
            });
        } else {
            titleEl.textContent = 'Add Participation Template';
            nameEl.value = '';
            bodyEl.value = '';
            entityEl.value = '';
            setParticipationAllocationType('Known');
        }

        document.getElementById('participation-template-modal-overlay').classList.add('visible');
    }

    function closeParticipationTemplateModal() {
        document.getElementById('participation-template-modal-overlay').classList.remove('visible');
    }

    async function handleParticipationTemplateSave() {
        const company = getParticipationSelectedCompany();
        const docType = getParticipationDocType();
        const statusEl = document.getElementById('participation-template-modal-status');
        const submitBtn = document.getElementById('participation-template-modal-submit');
        const name = document.getElementById('participation-template-name').value.trim();
        if (!company) { statusEl.textContent = 'No company selected.'; return; }
        if (!name) { statusEl.textContent = 'Template name is required.'; return; }

        const payload = {
            name,
            company_id: company.company_id,
            document_type: docType,
            allocation_type: getParticipationAllocationType(),
            body_text: document.getElementById('participation-template-body-text').value,
            agreed_accepted_entity: document.getElementById('participation-template-entity').value.trim(),
            fields: collectParticipationFields(),
        };

        submitBtn.disabled = true;
        statusEl.textContent = 'Saving...';
        try {
            if (participationEditingTemplateId) {
                await API.adminUpdateParticipationTemplate(participationEditingTemplateId, payload);
            } else {
                await API.adminCreateParticipationTemplate(payload);
            }
            statusEl.textContent = 'Saved.';
            setTimeout(() => {
                closeParticipationTemplateModal();
                loadParticipationTemplates();
            }, 500);
        } catch (err) {
            statusEl.textContent = err.message || 'Failed to save template.';
        } finally {
            submitBtn.disabled = false;
        }
    }

    async function handleParticipationTemplateDelete(templateId) {
        if (!confirm('Delete this template? This cannot be undone.')) return;
        try {
            await API.adminDeleteParticipationTemplate(templateId);
            loadParticipationTemplates();
        } catch (err) {
            alert(err.message || 'Failed to delete template.');
        }
    }

    async function handleParticipationTemplatePreview() {
        const statusEl = document.getElementById('participation-template-modal-status');
        const docType = getParticipationDocType();
        const payload = {
            documentType: docType,
            title: '',
            bodyText: document.getElementById('participation-template-body-text').value,
            agreedAcceptedEntity: document.getElementById('participation-template-entity').value.trim(),
            // Fill each field with a placeholder value so the layout is visible in the preview.
            // A CheckboxGroup field renders its single checked option (checkbox=true) instead.
            fields: collectParticipationFields().map((f) => {
                const sel = f.options_config && f.options_config.selected;
                return sel ? { ...f, value: sel, checkbox: true } : { ...f, value: `«${f.key}»` };
            }),
        };
        statusEl.textContent = 'Rendering preview…';
        try {
            const blob = await API.adminPreviewParticipationPdf(payload);
            const url = URL.createObjectURL(blob);
            window.open(url, '_blank');
            setTimeout(() => URL.revokeObjectURL(url), 60000);
            statusEl.textContent = '';
        } catch (err) {
            statusEl.textContent = err.message || 'Preview failed.';
        }
    }

    function openParticipationMappingModal() {
        const company = getParticipationSelectedCompany();
        const docType = getParticipationDocType();
        if (!company) { alert('Select a company first.'); return; }

        const contextEl = document.getElementById('participation-mapping-context');
        const periodSelect = document.getElementById('participation-mapping-period');
        const templateSelect = document.getElementById('participation-mapping-template');
        const statusEl = document.getElementById('participation-mapping-modal-status');
        statusEl.textContent = '';
        contextEl.textContent = `${docType} · ${company.name} (${company.symbol})`;

        periodSelect.innerHTML = '<option value="">-- Select Pricing Period --</option>';
        (company.pricing_period_types || []).forEach((p) => {
            const opt = document.createElement('option');
            opt.value = p;
            opt.textContent = p;
            periodSelect.appendChild(opt);
        });

        templateSelect.innerHTML = '<option value="">-- Select Template --</option>';
        participationTemplatesCache.forEach((t) => {
            const opt = document.createElement('option');
            opt.value = t.template_id;
            opt.textContent = t.name;
            templateSelect.appendChild(opt);
        });

        document.getElementById('participation-mapping-modal-overlay').classList.add('visible');
    }

    function closeParticipationMappingModal() {
        document.getElementById('participation-mapping-modal-overlay').classList.remove('visible');
    }

    async function handleParticipationMappingSave() {
        const company = getParticipationSelectedCompany();
        const docType = getParticipationDocType();
        const statusEl = document.getElementById('participation-mapping-modal-status');
        const period = document.getElementById('participation-mapping-period').value;
        const templateId = document.getElementById('participation-mapping-template').value;
        if (!company) { statusEl.textContent = 'No company selected.'; return; }
        if (!period) { statusEl.textContent = 'Select a pricing period.'; return; }
        if (!templateId) { statusEl.textContent = 'Select a template.'; return; }

        statusEl.textContent = 'Saving...';
        try {
            await API.adminUpsertParticipationMapping({
                company_id: company.company_id,
                pricing_period_type: period,
                document_type: docType,
                template_id: templateId,
            });
            statusEl.textContent = 'Saved.';
            setTimeout(() => {
                closeParticipationMappingModal();
                loadParticipationMappings();
            }, 500);
        } catch (err) {
            statusEl.textContent = err.message || 'Failed to save mapping.';
        }
    }

    async function handleParticipationMappingDelete(period) {
        const company = getParticipationSelectedCompany();
        const docType = getParticipationDocType();
        if (!company) return;
        if (!confirm(`Remove the mapping for ${period}?`)) return;
        try {
            await API.adminDeleteParticipationMapping(company.company_id, period, docType);
            loadParticipationMappings();
        } catch (err) {
            alert(err.message || 'Failed to remove mapping.');
        }
    }

    async function initParticipationTemplates() {
        const doctypeFilter = document.getElementById('participation-doctype-filter');
        const companyFilter = document.getElementById('participation-company-filter');
        if (doctypeFilter) doctypeFilter.addEventListener('change', loadParticipationTemplates);
        if (companyFilter) companyFilter.addEventListener('change', loadParticipationTemplates);

        const addBtn = document.getElementById('add-participation-template-btn');
        if (addBtn) addBtn.addEventListener('click', () => openParticipationTemplateModal(null));

        const addFieldBtn = document.getElementById('participation-add-field-btn');
        if (addFieldBtn) addFieldBtn.addEventListener('click', () => {
            const select = document.getElementById('participation-field-select');
            const key = select.value;
            if (!key) return;
            const docType = getParticipationDocType();
            const catalog = participationCatalogCache[docType] || [];
            const descriptor = catalog.find((d) => d.key === key);
            if (descriptor) renderParticipationFieldRow(descriptor, null);
            select.value = '';
        });

        ['participation-template-modal-close', 'participation-template-modal-cancel'].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.addEventListener('click', closeParticipationTemplateModal);
        });
        const tmplSubmit = document.getElementById('participation-template-modal-submit');
        if (tmplSubmit) tmplSubmit.addEventListener('click', handleParticipationTemplateSave);
        const tmplPreview = document.getElementById('participation-template-modal-preview');
        if (tmplPreview) tmplPreview.addEventListener('click', handleParticipationTemplatePreview);

        const addMappingBtn = document.getElementById('add-participation-mapping-btn');
        if (addMappingBtn) addMappingBtn.addEventListener('click', openParticipationMappingModal);
        ['participation-mapping-modal-close', 'participation-mapping-modal-cancel'].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.addEventListener('click', closeParticipationMappingModal);
        });
        const mapSubmit = document.getElementById('participation-mapping-modal-submit');
        if (mapSubmit) mapSubmit.addEventListener('click', handleParticipationMappingSave);

        await populateParticipationCompanyFilter();
    }

    document.addEventListener('DOMContentLoaded', init);

    return { init };
})();
