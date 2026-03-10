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

        if (!symbol || !periodId || !shares) {
            showError('Missing required parameters. Please return to the dashboard.');
            return;
        }

        params = {
            symbol: symbol,
            periodId: parseInt(periodId, 10),
            shares: parseInt(shares, 10),
        };

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

        document.getElementById('pn-signatory-select').addEventListener('change', onSignatoryChange);
    }

    // ---- Data Loading ----

    async function loadPrefill() {
        try {
            const data = await API.getPurchaseNoticePrefill(
                params.symbol, params.periodId, params.shares
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

        // Body text
        const bodyEl = document.getElementById('pn-body-text');
        bodyEl.textContent = data.body_text || '';

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
        setText('pn-dollar-cap', formatCurrency(data.dollarCapPerNotice));

        // Company signature block
        const companyName = sessionStorage.getItem('company_name') || data.companyName || '';
        setText('pn-company-name-upper', companyName.toUpperCase());

        // Populate signatory dropdown
        populateSignatories(data.signatories || []);

        // Agreed and Accepted block
        setText('pn-agreed-entity', data.agreed_accepted_entity || '');
        setText('pn-firm-signer-name', data.signerName || '');
        setText('pn-firm-signer-title', data.signerTitle || '');

        // Dated line
        setText('pn-dated', formatDate(new Date().toISOString()));
    }

    function populateSignatories(signatories) {
        const select = document.getElementById('pn-signatory-select');
        // Clear existing options beyond the placeholder
        select.innerHTML = '<option value="">— Select signatory —</option>';

        signatories.forEach((sig) => {
            const opt = document.createElement('option');
            opt.value = sig._id;
            opt.textContent = `${sig.name} — ${sig.title}`;
            opt.dataset.name = sig.name;
            opt.dataset.title = sig.title;
            opt.dataset.signature = sig.signature_image || '';
            select.appendChild(opt);
        });

        // Auto-select if only one signatory
        if (signatories.length === 1) {
            select.value = signatories[0]._id;
            onSignatoryChange();
        }
    }

    function onSignatoryChange() {
        const select = document.getElementById('pn-signatory-select');
        const selected = select.options[select.selectedIndex];
        const sigImg = document.getElementById('pn-signatory-signature');
        const sigLine = document.getElementById('pn-signature-line-co');

        if (selected && selected.value) {
            setText('pn-signatory-name', selected.dataset.name || '');
            setText('pn-signatory-title', selected.dataset.title || '');

            if (selected.dataset.signature) {
                sigImg.src = selected.dataset.signature;
                sigImg.style.display = '';
                if (sigLine) sigLine.style.display = 'none';
            } else {
                sigImg.style.display = 'none';
                if (sigLine) sigLine.style.display = '';
            }
        } else {
            setText('pn-signatory-name', '\u2014');
            setText('pn-signatory-title', '\u2014');
            sigImg.style.display = 'none';
            if (sigLine) sigLine.style.display = '';
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
