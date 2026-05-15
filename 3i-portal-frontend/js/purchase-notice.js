/**
 * 3i Fund Portal — Purchase Notice Page
 * Renders a VWAP Purchase Notice from prefilled data.
 * Monitors shares availability and acceptance window in real time.
 */

const PurchaseNotice = (() => {
    let pollTimer = null;
    let currentData = null;
    let params = null;

    // ---- Initialization ----

    function init() {
        console.log('[PurchaseNotice] Initializing...');

        // Parse URL params
        const url = new URLSearchParams(window.location.search);
        const symbol = url.get('symbol');
        const periodId = url.get('periodId');
        const shares = url.get('shares');
        const backward = url.get('backward') === 'true';
        const backwardVwapPrice = url.get('backwardVwapPrice') ? parseFloat(url.get('backwardVwapPrice')) : null;

        if (!symbol || !periodId || !shares) {
            showError('Missing required parameters. Please return to the dashboard.');
            return;
        }

        params = {
            symbol: symbol,
            periodId: parseInt(periodId, 10),
            shares: parseInt(shares, 10),
            backward: backward,
            backwardVwapPrice: backwardVwapPrice,
        };

        console.log('[PurchaseNotice] backward=%s, backwardVwapPrice=%s', backward, backwardVwapPrice);

        console.log('[PurchaseNotice] Params:', params);

        // Load prefill data
        loadPrefill();

        // Wire buttons
        document.getElementById('pn-back-btn').addEventListener('click', () => {
            window.location.href = 'dashboard.html';
        });

        document.getElementById('pn-alert-btn').addEventListener('click', () => {
            window.location.href = 'dashboard.html';
        });

        // Signatory dropdown removed — user's signatory auto-displayed from profile

        // Send button → open confirmation dialog
        document.getElementById('pn-send-btn').addEventListener('click', openConfirmDialog);

        // Confirmation dialog controls
        document.getElementById('pn-confirm-checkbox').addEventListener('change', (e) => {
            document.getElementById('pn-confirm-accept').disabled = !e.target.checked;
        });

        document.getElementById('pn-confirm-reject').addEventListener('click', closeConfirmDialog);

        document.getElementById('pn-confirm-accept').addEventListener('click', handleAcceptAndSubmit);
    }

    // ---- Data Loading ----

    async function loadPrefill() {
        try {
            const data = await API.getPurchaseNoticePrefill(
                params.symbol, params.periodId, params.shares, params.backward
            );
            console.log('[PurchaseNotice] Prefill data loaded');

            currentData = data;
            renderNotice(data);

            // Hide loading, show document
            document.getElementById('pn-loading').style.display = 'none';
            document.getElementById('pn-document').style.display = 'block';

            // Start real-time monitoring
            startMonitoring();
        } catch (err) {
            console.error('[PurchaseNotice] Failed to load prefill:', err);
            showError(err.message || 'Failed to load purchase notice data.');
        }
    }

    // ---- Rendering ----

    function renderNotice(data) {
        // To / CC block
        setText('pn-to-name', data.signerName || '');
        setText('pn-to-email', data.firmEmail || '');

        if (data.adminEmailAddress) {
            document.getElementById('pn-cc-row').style.display = '';
            setText('pn-cc-email', data.adminEmailAddress);
        }

        // Body text — only show if template provides it
        const bodyEl = document.getElementById('pn-body-text');
        if (data.body_text) {
            bodyEl.textContent = data.body_text;
            bodyEl.style.display = '';
        } else {
            bodyEl.style.display = 'none';
        }

        // Fields table
        setText('pn-company-name', data.companyName || '');
        setText('pn-symbol', data.symbol || '');
        setText('pn-period-type', formatPeriodType(data.periodType || ''));
        setText('pn-shares', formatNumber(data.shares));
        setText('pn-exercise-date', formatDate(data.exerciseDate));
        setText('pn-valuation-period',
            `${formatDate(data.valuationPeriodStart)} — ${formatDate(data.valuationPeriodEnd)}`
        );
        setText('pn-trading-days', data.tradingDays || '');
        setText('pn-settlement-date', formatDate(data.settlementDate));
        setText('pn-commitment-remaining', formatCurrency(data.totalCommitmentRemaining));

        // Backward pricing fields
        const vwapPriceRow = document.getElementById('pn-vwap-price-row');
        const totalPriceRow = document.getElementById('pn-total-price-row');
        if (data.pricingDirection === 'Backward' && data.backwardVwapPrice != null) {
            const vwapPrice = data.backwardVwapPrice;
            const totalPrice = data.shares * vwapPrice;
            setText('pn-vwap-price', '$' + Number(vwapPrice).toFixed(6));
            setText('pn-total-price', formatCurrency(totalPrice));
            if (vwapPriceRow) vwapPriceRow.style.display = '';
            if (totalPriceRow) totalPriceRow.style.display = '';
            console.log('[PurchaseNotice] Backward pricing: vwap=$%s, total=%s',
                vwapPrice.toFixed(6), formatCurrency(totalPrice));
        } else {
            if (vwapPriceRow) vwapPriceRow.style.display = 'none';
            if (totalPriceRow) totalPriceRow.style.display = 'none';
        }

        // Company signature block
        const companyName = sessionStorage.getItem('company_name') || data.companyName || '';
        setText('pn-company-name-upper', companyName.toUpperCase());

        // Populate signatory dropdown
        displaySignatory(data.signatory);

        // Agreed and Accepted block — entity from template, signature fields left blank
        const entityEl = document.getElementById('pn-agreed-entity');
        if (data.agreed_accepted_entity) {
            entityEl.textContent = data.agreed_accepted_entity;
            entityEl.style.display = '';
        } else {
            entityEl.style.display = 'none';
        }

        // Dated line
        setText('pn-dated', formatDate(new Date().toISOString()));
    }

    function displaySignatory(sig) {
        const sigImg = document.getElementById('pn-signatory-signature');
        const sigLine = document.getElementById('pn-signature-line-co');
        const sendBtn = document.getElementById('pn-send-btn');
        const nameVal = document.getElementById('pn-signatory-name');
        const nameLine = document.getElementById('pn-signatory-name-line');
        const titleVal = document.getElementById('pn-signatory-title');
        const titleLine = document.getElementById('pn-signatory-title-line');
        const addrVal = document.getElementById('pn-signatory-address');
        const addrLine = document.getElementById('pn-signatory-address-line');

        // Hide the dropdown if it exists
        const selectEl = document.getElementById('pn-signatory-select');
        if (selectEl) selectEl.style.display = 'none';

        if (sig && sig.signatory_name) {
            setText('pn-signatory-name', sig.signatory_name || '');
            setText('pn-signatory-title', sig.signatory_title || '');
            setText('pn-signatory-address', sig.signatory_address || '');
            if (nameVal) nameVal.style.display = '';
            if (nameLine) nameLine.style.display = 'none';
            if (titleVal) titleVal.style.display = sig.signatory_title ? '' : 'none';
            if (titleLine) titleLine.style.display = sig.signatory_title ? 'none' : '';
            if (addrVal) addrVal.style.display = sig.signatory_address ? '' : 'none';
            if (addrLine) addrLine.style.display = sig.signatory_address ? 'none' : '';

            if (sig.signatory_signature_image) {
                sigImg.src = sig.signatory_signature_image;
                sigImg.style.display = '';
                if (sigLine) sigLine.style.display = 'none';
            } else {
                sigImg.style.display = 'none';
                if (sigLine) sigLine.style.display = '';
            }

            // Enable send if signatory has required fields
            if (sendBtn) sendBtn.disabled = !(sig.signatory_title && sig.signatory_signature_image);
        } else {
            if (nameVal) nameVal.style.display = 'none';
            if (nameLine) nameLine.style.display = '';
            if (titleVal) titleVal.style.display = 'none';
            if (titleLine) titleLine.style.display = '';
            if (addrVal) addrVal.style.display = 'none';
            if (addrLine) addrLine.style.display = '';
            sigImg.style.display = 'none';
            if (sigLine) sigLine.style.display = '';

            if (sendBtn) sendBtn.disabled = true;
        }
    }

    // ---- Real-time Monitoring ----

    function startMonitoring() {
        console.log('[PurchaseNotice] Starting monitoring (15s interval)');
        pollTimer = setInterval(pollShares, 15_000);
    }

    function stopMonitoring() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    async function pollShares() {
        try {
            const data = await API.getSharesAvailable();
            if (!data || !data.pricingPeriods) return;

            // Find our pricing period
            const period = data.pricingPeriods.find(
                (p) => p.pricingPeriodId === params.periodId
            );

            if (!period) {
                console.warn('[PurchaseNotice] Pricing period not found in poll response');
                return;
            }

            // Check acceptance window
            if (!period.isWithinAcceptanceWindow) {
                console.log('[PurchaseNotice] Acceptance window closed');
                stopMonitoring();
                showAlert(
                    'Acceptance Window Closed',
                    'The purchase notice acceptance window has closed. This notice can no longer be submitted.'
                );
                return;
            }

            // Check shares availability
            if (period.availableShares <= 0) {
                console.log('[PurchaseNotice] Shares no longer available');
                stopMonitoring();
                showAlert(
                    'Shares No Longer Available',
                    'The shares for this pricing period are no longer available. This notice can no longer be submitted.'
                );
                return;
            }

            // Update shares if changed
            if (period.availableShares !== currentData.shares) {
                console.log('[PurchaseNotice] Available shares changed: %d → %d',
                    currentData.shares, period.availableShares);

                // If requested shares exceed now-available shares, cap it
                if (params.shares > period.availableShares) {
                    params.shares = period.availableShares;
                    currentData.shares = period.availableShares;
                    setText('pn-shares', formatNumber(period.availableShares));
                }
            }
        } catch (err) {
            console.warn('[PurchaseNotice] Monitoring poll failed:', err.message);
        }
    }

    // ---- Alert Dialog ----

    function showAlert(title, message) {
        document.getElementById('pn-document').style.display = 'none';
        document.getElementById('pn-alert-title').textContent = title;
        document.getElementById('pn-alert-message').textContent = message;
        document.getElementById('pn-alert-overlay').style.display = 'flex';
    }

    // ---- Confirmation Dialog ----

    function _onDisclaimerScroll(e) {
        const el = e.target;
        const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 10;
        if (atBottom) {
            const checkbox = document.getElementById('pn-confirm-checkbox');
            const checkboxLabel = document.getElementById('pn-confirm-checkbox-label');
            checkbox.disabled = false;
            checkboxLabel.style.opacity = '1';
            checkboxLabel.style.pointerEvents = 'auto';
            console.log('[PurchaseNotice] Disclaimer scrolled to bottom — checkbox enabled');
        }
    }

    function openConfirmDialog() {
        // Populate dynamic fields in the confirmation modal
        const companyName = sessionStorage.getItem('company_name') || currentData.companyName || '';
        setText('pn-confirm-company', companyName);
        setText('pn-confirm-company2', companyName);
        setText('pn-confirm-shares', formatNumber(currentData.shares) + ' shares of Common Stock');
        setText('pn-confirm-valuation',
            formatDate(currentData.valuationPeriodStart) + ' \u2014 ' + formatDate(currentData.valuationPeriodEnd)
        );
        setText('pn-confirm-settlement', formatDate(currentData.settlementDate));

        // Reset checkbox and button state
        const checkbox = document.getElementById('pn-confirm-checkbox');
        const checkboxLabel = document.getElementById('pn-confirm-checkbox-label');
        checkbox.checked = false;
        checkbox.disabled = true;
        checkboxLabel.style.opacity = '0.5';
        checkboxLabel.style.pointerEvents = 'none';
        document.getElementById('pn-confirm-accept').disabled = true;

        // Scroll the legal text back to top and require full scroll before enabling checkbox
        const scrollArea = document.querySelector('.pn-confirm-scroll');
        if (scrollArea) {
            scrollArea.scrollTop = 0;
            scrollArea.removeEventListener('scroll', _onDisclaimerScroll);
            scrollArea.addEventListener('scroll', _onDisclaimerScroll);
        }

        document.getElementById('pn-confirm-overlay').style.display = 'flex';
    }

    function closeConfirmDialog() {
        document.getElementById('pn-confirm-overlay').style.display = 'none';
    }

    async function handleAcceptAndSubmit() {
        console.log('[PurchaseNotice] User accepted and submitted');
        closeConfirmDialog();

        // Disable send button to prevent double-submit
        const sendBtn = document.getElementById('pn-send-btn');
        if (sendBtn) {
            sendBtn.disabled = true;
            sendBtn.textContent = 'Submitting...';
        }

        // Stop monitoring while submitting
        stopMonitoring();

        try {
            // Build payload — signatory is pulled from user's profile on the backend
            const payload = {
                symbol: params.symbol,
                pricing_period_id: params.periodId,
                shares: params.shares,
                // Template content
                body_text: currentData.body_text || '',
                agreed_accepted_entity: currentData.agreed_accepted_entity || '',
                // Signatory fields sent for backward compatibility but backend overrides from user profile
                signatory_name: '',
                signatory_title: '',
                signatory_address: '',
                signatory_signature_image: null,
                // Calculated fields from prefill
                exercise_date: currentData.exerciseDate || '',
                valuation_period_start: currentData.valuationPeriodStart || '',
                valuation_period_end: currentData.valuationPeriodEnd || '',
                trading_days: currentData.tradingDays || 0,
                settlement_date: currentData.settlementDate || '',
                period_type: currentData.periodType || '',
                total_commitment_remaining: currentData.totalCommitmentRemaining || null,
                dollar_cap_per_notice: currentData.dollarCapPerNotice || null,
                // Pricing direction
                pricing_direction: params.backward ? 'Backward' : 'Forward',
                backward_vwap_price: params.backward ? params.backwardVwapPrice : null,
            };

            console.log('[PurchaseNotice] pricing_direction=%s, backward_vwap_price=%s',
                payload.pricing_direction, payload.backward_vwap_price);

            console.log('[PurchaseNotice] Submitting portal purchase notice: symbol=%s periodId=%d shares=%d signatory=%s',
                params.symbol, params.periodId, params.shares, payload.signatory_name);
            const result = await API.submitPortalPurchaseNotice(payload);

            if (result && result.status === 'pending_verification') {
                showAlert(
                    'Pending Verification',
                    'Your purchase notice has been sent for approval via SMS. You will be notified when it is approved or rejected.'
                );
            } else {
                showAlert(
                    'Purchase Notice Submitted',
                    'Your Purchase Notice has been submitted successfully. You will be redirected to the dashboard.'
                );
            }
        } catch (err) {
            // Concurrency rejection from the backend: another user from the same
            // company already has an ELOC in progress. Show a friendly message —
            // the alert's OK button already routes back to dashboard.html.
            if (err && err.status === 409 && err.detail && err.detail.code === 'ELOC_ALREADY_PRICING') {
                console.warn('[PurchaseNotice] Rejected — ELOC already pricing: blocking=%s step=%s',
                    err.detail.blocking_eloc_id, err.detail.blocking_workflow_step);
                var blocking = err.detail.blocking_eloc_id
                    ? '\n\nIn progress: ' + err.detail.blocking_eloc_id +
                      (err.detail.blocking_workflow_step ? ' (' + err.detail.blocking_workflow_step + ')' : '')
                    : '';
                showAlert(
                    'ELOC Already In Progress',
                    'Another user from your company has already submitted a Purchase Notice that is still in progress. ' +
                    'Wait for it to complete, or use the Remove button on the dashboard to clear it before submitting another.' +
                    blocking
                );
                return;
            }
            console.error('[PurchaseNotice] Submission failed:', err);
            showAlert(
                'Submission Failed',
                err.message || 'Failed to submit purchase notice. Please try again or contact support.'
            );
        }
    }

    // ---- Error State ----

    function showError(message) {
        document.getElementById('pn-loading').style.display = 'none';
        document.getElementById('pn-error-message').textContent = message;
        document.getElementById('pn-error').style.display = 'block';
    }

    // ---- Formatting Utilities ----

    function setText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    function formatDate(isoString) {
        if (!isoString) return '\u2014';
        const d = new Date(isoString);
        if (isNaN(d.getTime())) return isoString;
        return d.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
        });
    }

    function formatNumber(n) {
        if (n == null) return '\u2014';
        return new Intl.NumberFormat('en-US').format(n);
    }

    function formatCurrency(n) {
        if (n == null) return '\u2014';
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            minimumFractionDigits: 2,
        }).format(n);
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

    // ---- Bootstrap ----

    document.addEventListener('DOMContentLoaded', init);

    return { init };
})();
