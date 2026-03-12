/**
 * 3i Fund Portal — Dashboard
 * Loads and displays the user's active and historical ELOCs.
 * Polls on-prem server every 60s for available shares per pricing period.
 * Streams real-time quotes via WebSocket.
 */

const Dashboard = (() => {
    let pollTimer = null;
    let quotesWs = null;
    let workflowsWs = null;
    let wsReconnectTimer = null;
    let workflowsReconnectTimer = null;
    let hasSignatories = true; // assume true until checked

    // ---- ELOC Cards ----

    /**
     * Create an ELOC card element.
     * Cards show one row per pricing period with dynamic shares data.
     */
    function createElocCard(eloc) {
        const card = document.createElement('div');
        card.className = 'card eloc-card';
        card.dataset.elocId = eloc.eloc_id;
        // Build one row per pricing period
        let periodsHtml = '';
        (eloc.pricing_period_types || []).forEach((pt) => {
            const displayName = formatPeriodType(pt);
            periodsHtml += `
                <div class="period-row" data-period-type="${escapeHtml(pt)}" data-eloc-id="${eloc.eloc_id}">
                    <span class="period-name">${escapeHtml(displayName)}</span>
                    <span class="period-data">\u2014</span>
                    <button class="period-btn" disabled>Initiate Purchase Notice</button>
                </div>
            `;
        });

        card.innerHTML = `
            <div class="card-periods">
                ${periodsHtml || '<div class="period-row"><span class="period-data">\u2014</span></div>'}
            </div>
        `;

        console.log('[Dashboard] Created ELOC card:', eloc.eloc_id, 'periods:', eloc.pricing_period_types);
        return card;
    }

    /**
     * Load ELOCs for a given status and render into a grid.
     */
    async function loadElocs(status, gridId, loadingId, emptyId) {
        const grid = document.getElementById(gridId);
        const loading = document.getElementById(loadingId);
        const empty = document.getElementById(emptyId);

        console.log('[Dashboard] Loading ELOCs status=%s grid=%s', status, gridId);

        try {
            const elocs = await API.getElocs(status);
            console.log('[Dashboard] Loaded %d ELOCs for status=%s', elocs?.length || 0, status);

            loading.style.display = 'none';

            if (!elocs || elocs.length === 0) {
                empty.style.display = 'block';
                return;
            }

            grid.innerHTML = '';
            elocs.forEach((eloc) => {
                grid.appendChild(createElocCard(eloc));
            });
        } catch (err) {
            console.error('[Dashboard] Error loading ELOCs:', err);
            loading.style.display = 'none';
            empty.style.display = 'block';
            empty.querySelector('p').textContent = `Error loading ELOCs: ${err.message}`;
        }
    }

    // ---- Shares Polling ----

    /**
     * Fetch available shares and update all dashboard cards.
     * Also populates the quote bar from currentQuote as a fallback.
     */
    async function pollSharesAvailable() {
        console.log('[Dashboard] Polling shares-available...');
        try {
            const data = await API.getSharesAvailable();
            console.log('[Dashboard] shares-available response:', JSON.stringify(data).substring(0, 500));

            if (data && data.pricingPeriods) {
                console.log('[Dashboard] Updating cards with %d pricing periods, hasPendingEloc=%s',
                    data.pricingPeriods.length, data.hasPendingEloc);
                updateCardsWithShares(data);
            } else {
                console.warn('[Dashboard] No pricingPeriods in response');
            }

            // Use currentQuote from REST response as fallback for quote bar
            if (data && data.currentQuote) {
                console.log('[Dashboard] REST currentQuote fallback:', JSON.stringify(data.currentQuote));
                updateQuoteBar({ symbol: data.symbol, ...data.currentQuote });
            } else {
                console.log('[Dashboard] No currentQuote in REST response');
            }
        } catch (err) {
            console.warn('[Dashboard] Shares polling failed:', err.message, err);
        }
    }

    /**
     * Update ELOC card period rows with shares data from on-prem.
     * Display logic:
     *   1. hasPendingEloc → "ELOC Currently Pricing"
     *   2. !isWithinAcceptanceWindow → "Outside of Notice Window"
     *   3. Otherwise → formatted availableShares
     */
    function updateCardsWithShares(data) {
        const hasPending = data.hasPendingEloc;
        const pricingPeriods = data.pricingPeriods || [];
        const symbol = data.symbol;

        // Build a lookup by periodType
        const periodMap = {};
        pricingPeriods.forEach((p) => {
            periodMap[p.periodType] = p;
        });

        // Update all period rows across all cards
        const rows = document.querySelectorAll('.period-row[data-period-type]');
        console.log('[Dashboard] Updating %d period rows', rows.length);

        rows.forEach((row) => {
            const periodType = row.dataset.periodType;
            const period = periodMap[periodType];
            const dataSpan = row.querySelector('.period-data');
            const btn = row.querySelector('.period-btn');
            if (!dataSpan) return;

            let enableBtn = false;

            if (!period) {
                console.log('[Dashboard]   %s: no data in response', periodType);
                dataSpan.textContent = '\u2014';
                dataSpan.className = 'period-data';
            } else if (hasPending) {
                console.log('[Dashboard]   %s: ELOC Currently Pricing', periodType);
                dataSpan.textContent = 'ELOC Currently Pricing';
                dataSpan.className = 'period-data pending-eloc';
            } else if (!period.isWithinAcceptanceWindow) {
                console.log('[Dashboard]   %s: Outside of Notice Window', periodType);
                dataSpan.textContent = 'Outside of Notice Window';
                dataSpan.className = 'period-data outside-window';
            } else if (period.isBlocked) {
                console.log('[Dashboard]   %s: Blocked — %s', periodType, period.blockReason);
                dataSpan.textContent = period.blockReason || 'Blocked';
                dataSpan.className = 'period-data outside-window';
            } else if (period.availableShares != null && period.availableShares > 0) {
                const shares = new Intl.NumberFormat('en-US').format(period.availableShares);
                console.log('[Dashboard]   %s: %s shares available', periodType, shares);
                dataSpan.textContent = `${shares} shares`;
                dataSpan.className = 'period-data has-data';
                enableBtn = true;
            } else {
                console.log('[Dashboard]   %s: availableShares=%s', periodType, period.availableShares);
                dataSpan.textContent = period.availableShares === 0 ? '0 shares' : '\u2014';
                dataSpan.className = 'period-data';
            }

            if (btn) {
                const canInitiate = enableBtn && hasSignatories;
                btn.disabled = !canInitiate;
                if (canInitiate && period) {
                    btn.onclick = () => openSharesModal(symbol, period.pricingPeriodId, period.availableShares);
                } else {
                    btn.onclick = null;
                }
            }
        });
    }

    /**
     * Start polling for shares data every 60 seconds.
     */
    function startPolling() {
        console.log('[Dashboard] Starting shares polling (60s interval)');
        pollSharesAvailable();
        pollTimer = setInterval(pollSharesAvailable, 60_000);
    }

    // ---- WebSocket Quotes ----

    /**
     * Connect to the backend WebSocket for real-time quotes.
     */
    function connectQuotesWs() {
        const token = sessionStorage.getItem('access_token');
        if (!token) {
            console.warn('[Dashboard] No access_token in sessionStorage, skipping WS connect');
            return;
        }

        const baseUrl = window.PORTAL_CONFIG?.apiBaseUrl || 'http://localhost:8000';
        const wsUrl = baseUrl.replace(/^http/, 'ws') + `/ws/quotes?token=${encodeURIComponent(token)}`;
        console.log('[Dashboard] Connecting to quote WS:', wsUrl.replace(/token=[^&]+/, 'token=***'));

        quotesWs = new WebSocket(wsUrl);

        quotesWs.onopen = () => {
            console.log('[Dashboard] Quote WS connected');
        };

        quotesWs.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                console.log('[Dashboard] Quote WS message: type=%s', msg.type, msg.type === 'update' || msg.type === 'snapshot' ? JSON.stringify(msg.quote).substring(0, 200) : '');
                if (msg.type === 'snapshot' || msg.type === 'update') {
                    updateQuoteBar(msg.quote);
                } else if (msg.type === 'error') {
                    console.warn('[Dashboard] Quote WS error message:', msg.message);
                }
            } catch (e) {
                console.warn('[Dashboard] Quote WS non-JSON message:', event.data.substring(0, 200));
            }
        };

        quotesWs.onclose = (event) => {
            console.warn('[Dashboard] Quote WS closed: code=%d reason=%s', event.code, event.reason || '(none)');
            // Reconnect after 5 seconds
            wsReconnectTimer = setTimeout(connectQuotesWs, 5000);
        };

        quotesWs.onerror = (event) => {
            console.error('[Dashboard] Quote WS error event:', event);
        };
    }

    /**
     * Update the quote bar with latest quote data.
     */
    function updateQuoteBar(quote) {
        if (!quote) {
            console.warn('[Dashboard] updateQuoteBar called with null/undefined quote');
            return;
        }

        console.log('[Dashboard] Updating quote bar:', quote.symbol, 'bid=', quote.bid, 'ask=', quote.ask, 'last=', quote.last);

        const bar = document.getElementById('quote-bar');
        if (bar) bar.style.display = 'flex';

        const set = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = val;
        };

        set('quote-symbol', quote.symbol || '\u2014');
        set('quote-bid', quote.bid != null ? formatPrice(quote.bid) : '\u2014');
        set('quote-bid-size', quote.bidSize != null ? new Intl.NumberFormat('en-US').format(quote.bidSize) : '\u2014');
        set('quote-ask', quote.ask != null ? formatPrice(quote.ask) : '\u2014');
        set('quote-ask-size', quote.askSize != null ? new Intl.NumberFormat('en-US').format(quote.askSize) : '\u2014');
        set('quote-last', quote.last != null ? formatPrice(quote.last) : '\u2014');
    }

    function formatPrice(num) {
        return new Intl.NumberFormat('en-US', {
            style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2,
        }).format(num);
    }

    // ---- Tabs ----

    function initTabs() {
        const tabs = document.querySelectorAll('.tab');
        const activePanel = document.getElementById('active-elocs-panel');
        const historyPanel = document.getElementById('history-elocs-panel');
        const actionsPanel = document.getElementById('actions-panel');

        tabs.forEach((tab) => {
            tab.addEventListener('click', () => {
                tabs.forEach((t) => t.classList.remove('active'));
                tab.classList.add('active');

                const target = tab.getAttribute('data-tab');
                activePanel.style.display = target === 'active' ? 'block' : 'none';
                historyPanel.style.display = target === 'history' ? 'block' : 'none';
                actionsPanel.style.display = target === 'actions' ? 'block' : 'none';
            });
        });
    }

    // ---- Action Items ----

    /**
     * Check for pending action items on login.
     * If items exist, flash the Action Items tab red.
     * Stub: will be wired to GET /elocs/action-items later.
     */
    async function checkActionItems() {
        console.log('[Dashboard] Checking action items...');
        try {
            const items = await API.getActionItems();
            console.log('[Dashboard] Action items response:', items);

            const tab = document.getElementById('actions-tab');
            if (items && items.length > 0) {
                console.log('[Dashboard] %d pending action items — flashing tab', items.length);
                tab.classList.add('has-actions');
                tab.textContent = `Action Items (${items.length})`;
            } else {
                console.log('[Dashboard] No pending action items');
                tab.classList.remove('has-actions');
                tab.textContent = 'Action Items';
            }
        } catch (err) {
            console.warn('[Dashboard] Action items check failed:', err.message);
        }
    }

    // ---- Pricing Workflows ----

    /**
     * Load workflow states for ELOCs currently pricing.
     */
    async function loadPricingWorkflows() {
        console.log('[Dashboard] Loading pricing workflows...');
        const container = document.getElementById('pricing-elocs-container');
        const empty = document.getElementById('pricing-empty');

        try {
            const workflows = await API.getPricingWorkflows();
            console.log('[Dashboard] Loaded %d pricing workflows', workflows?.length || 0);

            if (!workflows || workflows.length === 0) {
                empty.style.display = 'block';
                return;
            }

            // Remove existing workflow cards before rendering fresh set
            container.querySelectorAll('.workflow-container').forEach((c) => c.remove());
            empty.style.display = 'none';
            workflows.forEach((wf) => {
                container.appendChild(renderWorkflowCard(wf));
            });
        } catch (err) {
            console.warn('[Dashboard] Pricing workflows load failed:', err.message);
        }
    }

    // Steps that have downloadable documents
    const DOCUMENT_STEPS = new Set([
        'SignedContractToCompany',
        'VwapNotificationToCompany',
        'ReceivedCountersignedVwapNotification',
    ]);

    // Step icons — matches C# ElocWorkflowStep enum
    const STEP_ICONS = {
        SignedContractToCompany: '\u{1F4E5}',
        FinalVwapPricingCalculated: '\u{1F3AF}',
        VwapNotificationToCompany: '\u{1F4E7}',
        ReceivedCountersignedVwapNotification: '\u{1F4E9}',
    };

    // Map PascalCase status from backend to lowercase CSS class
    const STATUS_CSS = {
        Completed: 'completed',
        Pending: 'pending',
        InProgress: 'pending',
        Rejected: 'rejected',
        Failed: 'rejected',
        Awaiting: 'awaiting',
    };

    /**
     * Render a single workflow card for an ELOC currently pricing.
     */
    function renderWorkflowCard(workflow) {
        const card = document.createElement('div');
        card.className = 'workflow-container';
        card.dataset.elocId = workflow.eloc_id;
        card.dataset.source = workflow.source || 'dts';

        let stepsHtml = '';
        (workflow.steps || []).forEach((step) => {
            const cssClass = STATUS_CSS[step.status] || 'awaiting';
            const icon = STEP_ICONS[step.key] || '\u2022';
            const hasDoc = step.status === 'Completed' && DOCUMENT_STEPS.has(step.key);
            const clickable = hasDoc ? 'clickable' : '';
            stepsHtml += `
                <div class="workflow-step ${cssClass} ${clickable}" data-step="${escapeHtml(step.key)}">
                    <div class="workflow-badge ${cssClass} ${clickable}">${icon}</div>
                    <div class="workflow-label">${escapeHtml(step.label)}</div>
                </div>
            `;
        });

        card.innerHTML = `
            <div class="workflow-header">
                <div class="workflow-title">ELOC ${escapeHtml(workflow.eloc_id)}</div>
                <button class="workflow-remove-btn" ${workflow.can_remove ? '' : 'disabled'}>Remove</button>
            </div>
            <div class="workflow-steps">
                ${stepsHtml}
            </div>
        `;

        // Click handlers for completed document badges
        card.querySelectorAll('.workflow-step.clickable').forEach((stepEl) => {
            stepEl.addEventListener('click', () => {
                const stepKey = stepEl.dataset.step;
                openDocumentViewer(workflow.eloc_id, stepKey, workflow.source || 'dts');
            });
            stepEl.style.cursor = 'pointer';
        });

        // Remove button handler
        const removeBtn = card.querySelector('.workflow-remove-btn');
        removeBtn.addEventListener('click', async () => {
            console.log('[Dashboard] Removing workflow for ELOC %s', workflow.eloc_id);
            try {
                await API.removePricingWorkflow(workflow.eloc_id);
                card.remove();
                // Show empty message if no more workflows
                const remaining = document.querySelectorAll('#pricing-elocs-container .workflow-container');
                if (remaining.length === 0) {
                    document.getElementById('pricing-empty').style.display = 'block';
                }
            } catch (err) {
                console.error('[Dashboard] Remove workflow failed:', err.message);
            }
        });

        console.log('[Dashboard] Rendered workflow card: ELOC %s, step=%s status=%s source=%s can_remove=%s',
            workflow.eloc_id, workflow.current_step, workflow.step_status, workflow.source, workflow.can_remove);
        return card;
    }

    /**
     * Update or add a workflow card from a WebSocket message.
     */
    function handleWorkflowUpdate(workflow) {
        const container = document.getElementById('pricing-elocs-container');
        const empty = document.getElementById('pricing-empty');
        const existing = container.querySelector(`.workflow-container[data-eloc-id="${workflow.eloc_id}"]`);

        if (existing) {
            // Replace existing card
            const newCard = renderWorkflowCard(workflow);
            existing.replaceWith(newCard);
        } else {
            // Add new card
            empty.style.display = 'none';
            container.appendChild(renderWorkflowCard(workflow));
        }
    }

    /**
     * Remove a workflow card from the dashboard.
     */
    function handleWorkflowRemoved(elocId) {
        const container = document.getElementById('pricing-elocs-container');
        const card = container.querySelector(`.workflow-container[data-eloc-id="${elocId}"]`);
        if (card) {
            card.remove();
        }
        const remaining = container.querySelectorAll('.workflow-container');
        if (remaining.length === 0) {
            document.getElementById('pricing-empty').style.display = 'block';
        }
    }

    // ---- Document Viewer ----

    const STEP_LABELS = {
        SignedContractToCompany: 'Purchase Notice',
        VwapNotificationToCompany: 'Purchase Confirmation',
        ReceivedCountersignedVwapNotification: 'Countersigned Confirmation',
    };

    async function openDocumentViewer(elocId, step, source) {
        console.log('[Dashboard] Opening document viewer: eloc=%s step=%s source=%s', elocId, step, source);

        const overlay = document.getElementById('document-modal-overlay');
        const title = document.getElementById('document-modal-title');
        const loading = document.getElementById('document-modal-loading');
        const iframe = document.getElementById('document-modal-iframe');
        const statusEl = document.getElementById('document-modal-status');

        title.textContent = STEP_LABELS[step] || 'Document';
        loading.style.display = 'flex';
        iframe.style.display = 'none';
        iframe.src = '';
        statusEl.className = 'modal-status';
        statusEl.textContent = '';
        overlay.classList.add('visible');

        try {
            const doc = await API.getPortalElocDocument(elocId, step);
            loading.style.display = 'none';

            if (doc && doc.pdf_base64) {
                const byteChars = atob(doc.pdf_base64);
                const byteArray = new Uint8Array(byteChars.length);
                for (let i = 0; i < byteChars.length; i++) {
                    byteArray[i] = byteChars.charCodeAt(i);
                }
                const blob = new Blob([byteArray], { type: 'application/pdf' });
                const blobUrl = URL.createObjectURL(blob);
                iframe.src = blobUrl;
                iframe.style.display = 'block';
                // Clean up blob URL when modal closes
                iframe.dataset.blobUrl = blobUrl;
            } else {
                statusEl.className = 'modal-status error';
                statusEl.textContent = 'No document data returned.';
            }
        } catch (err) {
            console.error('[Dashboard] Document fetch failed:', err);
            loading.style.display = 'none';
            statusEl.className = 'modal-status error';
            statusEl.textContent = err.message || 'Failed to load document.';
        }
    }

    function closeDocumentViewer() {
        const overlay = document.getElementById('document-modal-overlay');
        const iframe = document.getElementById('document-modal-iframe');
        overlay.classList.remove('visible');

        // Revoke blob URL to free memory
        if (iframe.dataset.blobUrl) {
            URL.revokeObjectURL(iframe.dataset.blobUrl);
            delete iframe.dataset.blobUrl;
        }
        iframe.src = '';
    }

    function initDocumentViewer() {
        const closeBtn = document.getElementById('document-modal-close');
        if (closeBtn) closeBtn.addEventListener('click', closeDocumentViewer);

        // Close on overlay click
        const overlay = document.getElementById('document-modal-overlay');
        if (overlay) {
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) closeDocumentViewer();
            });
        }
    }

    /**
     * Connect to the backend WebSocket for real-time workflow updates.
     */
    function connectWorkflowsWs() {
        const token = sessionStorage.getItem('access_token');
        if (!token) {
            console.warn('[Dashboard] No access_token, skipping workflows WS connect');
            return;
        }

        const baseUrl = window.PORTAL_CONFIG?.apiBaseUrl || 'http://localhost:8000';
        const wsUrl = baseUrl.replace(/^http/, 'ws') + `/ws/workflows?token=${encodeURIComponent(token)}`;
        console.log('[Dashboard] Connecting to workflows WS');

        workflowsWs = new WebSocket(wsUrl);

        workflowsWs.onopen = () => {
            console.log('[Dashboard] Workflows WS connected');
        };

        workflowsWs.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                console.log('[Dashboard] Workflows WS message: type=%s', msg.type);

                if (msg.type === 'workflow_update' && msg.workflow) {
                    handleWorkflowUpdate(msg.workflow);
                } else if (msg.type === 'workflow_removed' && msg.eloc_id) {
                    handleWorkflowRemoved(msg.eloc_id);
                }
            } catch (e) {
                console.warn('[Dashboard] Workflows WS parse error:', e);
            }
        };

        workflowsWs.onclose = (event) => {
            console.warn('[Dashboard] Workflows WS closed: code=%d reason=%s', event.code, event.reason || '(none)');
            workflowsReconnectTimer = setTimeout(connectWorkflowsWs, 5000);
        };

        workflowsWs.onerror = (event) => {
            console.error('[Dashboard] Workflows WS error:', event);
        };
    }

    // ---- Signatory Management ----

    let editingSignatoryId = null;
    let currentSignatureImage = null;

    function generateSignature(name) {
        const canvas = document.createElement('canvas');
        canvas.width = 400;
        canvas.height = 120;
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, 400, 120);
        ctx.font = 'bold 48px "Dancing Script", cursive';
        ctx.fillStyle = '#1a1a2e';
        ctx.textBaseline = 'middle';
        ctx.fillText(name, 10, 60);
        return canvas.toDataURL('image/png');
    }

    function showSignaturePreview(dataUrl) {
        const preview = document.getElementById('sig-preview');
        if (dataUrl) {
            preview.innerHTML = `<img src="${dataUrl}" alt="Signature preview">`;
        } else {
            preview.innerHTML = '<p class="sig-preview-empty">No signature yet</p>';
        }
    }

    async function loadSignatories() {
        const list = document.getElementById('signatories-list');
        const empty = document.getElementById('signatories-empty');

        try {
            const signatories = await API.getSignatories();

            if (!signatories || signatories.length === 0) {
                list.innerHTML = '';
                empty.style.display = 'block';
                return;
            }

            empty.style.display = 'none';
            list.innerHTML = '';
            signatories.forEach((s) => {
                const div = document.createElement('div');
                div.style.cssText = 'display:flex; justify-content:space-between; align-items:center; padding:0.5rem 0; border-bottom:1px solid var(--input-border);';
                const sigThumb = s.signature_image
                    ? `<img src="${s.signature_image}" class="sig-thumbnail" alt="Signature">`
                    : '';
                div.innerHTML = `
                    <div>
                        <strong>${escapeHtml(s.name)}</strong> — ${escapeHtml(s.title)}<br>
                        <span style="font-size:0.85rem; color:var(--text-secondary);">${escapeHtml(s.email)}</span>
                        ${sigThumb}
                    </div>
                    <div>
                        <button class="btn-action sig-edit-btn" data-id="${escapeHtml(s._id)}">Edit</button>
                        <button class="btn-action sig-delete-btn" data-id="${escapeHtml(s._id)}">Delete</button>
                    </div>
                `;
                list.appendChild(div);
            });

            list.querySelectorAll('.sig-edit-btn').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const sig = signatories.find((s) => s._id === btn.dataset.id);
                    if (sig) startEditSignatory(sig);
                });
            });
            list.querySelectorAll('.sig-delete-btn').forEach((btn) => {
                btn.addEventListener('click', () => handleDeleteSignatory(btn.dataset.id));
            });
        } catch (err) {
            console.error('[Dashboard] Failed to load signatories:', err);
            list.innerHTML = '';
            empty.style.display = 'block';
            empty.querySelector('p').textContent = `Error: ${err.message}`;
        }
    }

    function startEditSignatory(sig) {
        editingSignatoryId = sig._id;
        document.getElementById('signatory-form-title').textContent = 'Edit Signatory';
        document.getElementById('sig-name').value = sig.name || '';
        document.getElementById('sig-title').value = sig.title || '';
        document.getElementById('sig-address').value = sig.address || '';
        document.getElementById('sig-email').value = sig.email || '';
        document.getElementById('sig-editing-id').value = sig._id;
        document.getElementById('signatory-modal-submit').textContent = 'Save';
        currentSignatureImage = sig.signature_image || null;
        showSignaturePreview(currentSignatureImage);
    }

    function resetSignatoryForm() {
        editingSignatoryId = null;
        document.getElementById('signatory-form-title').textContent = 'Add Signatory';
        document.getElementById('sig-name').value = '';
        document.getElementById('sig-title').value = '';
        document.getElementById('sig-address').value = '';
        document.getElementById('sig-email').value = '';
        document.getElementById('sig-editing-id').value = '';
        document.getElementById('signatory-modal-submit').textContent = 'Add';
        document.getElementById('signatory-modal-status').className = 'modal-status';
        document.getElementById('signatory-modal-status').textContent = '';
        currentSignatureImage = null;
        showSignaturePreview(null);
    }

    async function handleSignatorySubmit() {
        const statusEl = document.getElementById('signatory-modal-status');
        const submitBtn = document.getElementById('signatory-modal-submit');
        const name = document.getElementById('sig-name').value.trim();
        const title = document.getElementById('sig-title').value.trim();
        const address = document.getElementById('sig-address').value.trim();
        const email = document.getElementById('sig-email').value.trim();

        if (!name || !title || !email) {
            statusEl.className = 'modal-status error';
            statusEl.textContent = 'Name, title, and email are required.';
            return;
        }

        statusEl.className = 'modal-status sending';
        statusEl.textContent = editingSignatoryId ? 'Saving...' : 'Adding...';
        submitBtn.disabled = true;

        try {
            // Auto-generate signature from name if none provided
            if (!currentSignatureImage && name) {
                currentSignatureImage = generateSignature(name);
            }
            const signature_image = currentSignatureImage || null;

            if (editingSignatoryId) {
                await API.updateSignatory(editingSignatoryId, { name, title, address, email, signature_image });
            } else {
                await API.addSignatory({ name, title, address, email, signature_image });
            }
            statusEl.className = 'modal-status success';
            statusEl.textContent = editingSignatoryId ? 'Signatory updated.' : 'Signatory added.';
            resetSignatoryForm();
            await loadSignatories();
        } catch (err) {
            statusEl.className = 'modal-status error';
            statusEl.textContent = err.message || 'Failed.';
        } finally {
            submitBtn.disabled = false;
        }
    }

    async function handleDeleteSignatory(signatoryId) {
        if (!confirm('Delete this signatory?')) return;
        try {
            await API.deleteSignatory(signatoryId);
            await loadSignatories();
        } catch (err) {
            alert(err.message || 'Failed to delete signatory.');
        }
    }

    function openSignatoryModal() {
        resetSignatoryForm();
        loadSignatories();
        document.getElementById('signatory-modal-overlay').classList.add('visible');
    }

    function closeSignatoryModal() {
        document.getElementById('signatory-modal-overlay').classList.remove('visible');
        resetSignatoryForm();
        // Re-check signatories in case user added/removed one
        checkSignatories();
        // Re-poll shares to update button states
        pollSharesAvailable();
    }

    function initSignatoryManagement() {
        const btn = document.getElementById('manage-signatories-btn');
        if (btn) btn.addEventListener('click', openSignatoryModal);

        const closeBtn = document.getElementById('signatory-modal-close');
        const cancelBtn = document.getElementById('signatory-modal-cancel');
        if (closeBtn) closeBtn.addEventListener('click', closeSignatoryModal);
        if (cancelBtn) cancelBtn.addEventListener('click', closeSignatoryModal);

        const submitBtn = document.getElementById('signatory-modal-submit');
        if (submitBtn) submitBtn.addEventListener('click', handleSignatorySubmit);

        // Signature: generate from name
        const genBtn = document.getElementById('sig-generate-btn');
        if (genBtn) {
            genBtn.addEventListener('click', () => {
                const name = document.getElementById('sig-name').value.trim();
                if (!name) return;
                currentSignatureImage = generateSignature(name);
                showSignaturePreview(currentSignatureImage);
            });
        }

        // Signature: upload custom
        const uploadBtn = document.getElementById('sig-upload-btn');
        const fileInput = document.getElementById('sig-file-input');
        if (uploadBtn && fileInput) {
            uploadBtn.addEventListener('click', () => fileInput.click());
            fileInput.addEventListener('change', (e) => {
                const file = e.target.files[0];
                if (!file) return;
                if (file.size > 500 * 1024) {
                    alert('Signature image must be under 500 KB.');
                    fileInput.value = '';
                    return;
                }
                const reader = new FileReader();
                reader.onload = () => {
                    currentSignatureImage = reader.result;
                    showSignaturePreview(currentSignatureImage);
                };
                reader.readAsDataURL(file);
                fileInput.value = '';
            });
        }
    }

    // ---- Signatory Check ----

    async function checkSignatories() {
        console.log('[Dashboard] Checking if user has signatories...');
        try {
            const signatories = await API.getSignatories();
            hasSignatories = signatories && signatories.length > 0;
            console.log('[Dashboard] hasSignatories=%s (count=%d)', hasSignatories, signatories?.length || 0);

            const warning = document.getElementById('signatory-warning');
            const activeTab = document.getElementById('active-tab');

            if (!hasSignatories) {
                if (warning) warning.style.display = 'block';
                if (activeTab) activeTab.classList.add('has-actions');

                // Disable any already-enabled initiate buttons
                document.querySelectorAll('.period-btn').forEach((btn) => {
                    btn.disabled = true;
                    btn.onclick = null;
                });
            } else {
                if (warning) warning.style.display = 'none';
                if (activeTab) activeTab.classList.remove('has-actions');
            }
        } catch (err) {
            console.warn('[Dashboard] Signatory check failed:', err.message);
        }
    }

    // ---- Shares Input Modal ----

    let sharesModalData = null;

    function openSharesModal(symbol, pricingPeriodId, availableShares) {
        sharesModalData = { symbol, pricingPeriodId };
        document.getElementById('shares-modal-available').textContent =
            new Intl.NumberFormat('en-US').format(availableShares);
        const input = document.getElementById('shares-modal-input');
        input.value = availableShares;
        input.max = availableShares;
        document.getElementById('shares-modal-status').className = 'modal-status';
        document.getElementById('shares-modal-status').textContent = '';
        document.getElementById('shares-modal-overlay').classList.add('visible');
    }

    function closeSharesModal() {
        document.getElementById('shares-modal-overlay').classList.remove('visible');
        sharesModalData = null;
    }

    function handleSharesSubmit() {
        if (!sharesModalData) return;
        const input = document.getElementById('shares-modal-input');
        const shares = parseInt(input.value);
        const statusEl = document.getElementById('shares-modal-status');

        if (!shares || shares <= 0) {
            statusEl.className = 'modal-status error';
            statusEl.textContent = 'Enter a valid number of shares.';
            return;
        }
        if (input.max && shares > parseInt(input.max)) {
            statusEl.className = 'modal-status error';
            statusEl.textContent = `Cannot exceed ${new Intl.NumberFormat('en-US').format(input.max)} available shares.`;
            return;
        }

        const { symbol, pricingPeriodId } = sharesModalData;
        window.location.href = `purchase-notice.html?symbol=${encodeURIComponent(symbol)}&periodId=${pricingPeriodId}&shares=${shares}`;
    }

    function initSharesModal() {
        const closeBtn = document.getElementById('shares-modal-close');
        const cancelBtn = document.getElementById('shares-modal-cancel');
        if (closeBtn) closeBtn.addEventListener('click', closeSharesModal);
        if (cancelBtn) cancelBtn.addEventListener('click', closeSharesModal);

        const submitBtn = document.getElementById('shares-modal-submit');
        if (submitBtn) submitBtn.addEventListener('click', handleSharesSubmit);
    }

    // ---- Utilities ----

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function formatPeriodType(periodType) {
        const wordToNum = {
            'One': '1', 'Two': '2', 'Three': '3', 'Four': '4',
            'Five': '5', 'Six': '6', 'Seven': '7',
        };
        for (const [word, num] of Object.entries(wordToNum)) {
            if (periodType.startsWith(word)) {
                return num + '-' + periodType.slice(word.length);
            }
        }
        return periodType;
    }

    // ---- Init ----

    function init() {
        console.log('[Dashboard] Initializing...');
        initTabs();
        loadElocs('active', 'active-elocs-grid', 'active-loading', 'active-empty');
        loadElocs('history', 'history-elocs-grid', 'history-loading', 'history-empty');

        // Load pricing workflows
        loadPricingWorkflows();

        // Start polling for shares data after cards have rendered
        setTimeout(startPolling, 1000);

        // Check for pending action items
        checkActionItems();

        // Connect to WebSockets
        connectQuotesWs();
        connectWorkflowsWs();

        // Initialize signatory management, shares modal, and document viewer
        initSignatoryManagement();
        initSharesModal();
        initDocumentViewer();

        // Check if user has signatories (controls initiate button)
        checkSignatories();
    }

    document.addEventListener('DOMContentLoaded', init);

    return { init };
})();
