/**
 * 3i Fund Portal — Intraday VWAP Purchase Notice (Participation ELOC)
 *
 * Renders the company-facing entry form for an Intraday-period VWAP Purchase Notice.
 * Unlike the legacy Purchase Notice (all fields pre-computed, nothing user-entered),
 * this notice has a fixed, hardcoded mix of locked and editable fields — the rules
 * are specific to the Intraday class and are NOT driven by the generic per-field
 * "visible" template editor (Admin Dashboard ▸ ELOC ▸ Participation Templates only
 * supplies label text + PDF layout, never editability):
 *
 *   Type of VWAP Purchase              locked   — always "Intraday VWAP Purchase"
 *   VWAP Purchase Share Amount         editable — 1..max (ownership/commitment cap)
 *   VWAP Purchase Date                 locked   — current NY date, no time
 *   VWAP Purchase Percentage           editable — 0..default (cannot exceed default)
 *   Aggregate % immediately prior      locked   — fixed 0%
 *   Aggregate % after                  locked   — mirrors Purchase Percentage
 *   VWAP Purchase Volume Threshold     locked   — derived: ceil(ShareAmount / Percentage)
 *   Minimum Price Threshold ($)        editable — 0..previous close (default derived)
 *   Dollar amount of Common Stock...   locked   — Commitment Remaining
 *
 * Editable-field defaults/caps and locked-field computed values (max share amount, default
 * purchase percentage, default minimum price threshold, previous close, commitment remaining)
 * come from GET /purchase-notices/intraday-prefill/{symbol} — real deal data, read from the
 * company's IIntradayEloc business object in DTS (DealTermsServer/Services/Eloc/Intraday).
 *
 * The document-text fields (recipient name/email, agreed-and-accepted entity, body text) are
 * static for now — there is no customer-facing participation-template-fetch endpoint yet (see
 * PARTICIPATION_ELOC_HANDOFF.md); the submission flow itself also isn't wired. Those pieces are
 * isolated in getStaticTemplateContext() below, ready to swap for a real template-fetch call.
 */

const ParticipationPurchaseNotice = (() => {
    let ctx = null;      // prefill context (company/market/cap data)
    let state = null;    // current editable field values

    // ---- Field catalog (order matches the CAPS Intraday Purchase Notice template) ----
    //
    // kind: 'locked-checkbox' | 'locked-text' | 'editable-integer' | 'editable-percent' | 'editable-currency'
    const FIELDS = [
        {
            key: 'PurchaseType',
            label: 'Type of VWAP Purchase',
            kind: 'locked-checkbox',
            options: ['Pre-Market VWAP Purchase', 'Intraday VWAP Purchase'],
            // No static default — which option is checked is locked to ctx.acceptanceWindow
            // (computed by DTS right now) and the customer cannot override it. See purchaseTypeLabel().
        },
        {
            key: 'PurchaseShareAmount',
            label: 'VWAP Purchase Share Amount (number of Shares)',
            kind: 'editable-integer',
        },
        {
            key: 'PurchaseDate',
            label: 'VWAP Purchase Date',
            kind: 'locked-text',
        },
        {
            key: 'PurchasePercentage',
            label: 'VWAP Purchase Percentage (not to exceed the default and subject to the Aggregate VWAP Purchase Percentage limitation)',
            kind: 'editable-percent',
        },
        {
            key: 'AggregatePurchasePercentage',
            label: 'Aggregate VWAP Purchase Percentage immediately prior to delivery of this VWAP Purchase Notice',
            kind: 'locked-text',
        },
        {
            key: 'AggregatePurchasePercentageAfter',
            label: 'Aggregate VWAP Purchase Percentage after giving effect to this VWAP Purchase Notice',
            kind: 'locked-text',
        },
        {
            key: 'VolumeThreshold',
            label: 'VWAP Purchase Volume Threshold (calculated as VWAP Purchase Share Amount divided by VWAP Purchase Percentage)',
            kind: 'locked-text',
        },
        {
            key: 'MinimumPriceThreshold',
            label: 'Minimum Price Threshold ($)',
            kind: 'editable-currency',
            note: 'If blank, the default Minimum Price Threshold shall apply. The VWAP Purchase Valuation Period will ' +
                  'auto-terminate immediately if the sale price of the Common Stock on the Trading Market falls below ' +
                  'the Minimum Price Threshold during the VWAP Purchase Valuation Period.',
        },
        {
            key: 'DollarAmountOfCommonStockAvailable',
            label: 'Dollar amount of Common Stock currently available under the Aggregate Limit',
            kind: 'locked-text',
        },
    ];

    // ---- Initialization ----

    function init() {
        console.log('[ParticipationPurchaseNotice] Initializing...');

        const url = new URLSearchParams(window.location.search);
        const symbol = (url.get('symbol') || 'CAPS').toUpperCase();

        loadPrefill(symbol);

        document.getElementById('ppn-back-btn').addEventListener('click', () => {
            window.location.href = 'dashboard.html';
        });
        document.getElementById('ppn-send-btn').addEventListener('click', submitNotice);
    }

    // ---- Data Loading ----

    async function loadPrefill(symbol) {
        try {
            const [data, staticCtx] = await Promise.all([
                API.getIntradayPrefill(symbol),
                getStaticTemplateContext(symbol),
            ]);
            console.log('[ParticipationPurchaseNotice] Prefill (real):', data);

            ctx = {
                symbol,
                maxShareAmount: data.maxShareAmount,
                defaultPurchasePercentagePct: data.defaultPurchasePercentage,
                // Reference price for the Minimum Price Threshold default/max: previous close during
                // the Pre-Market acceptance window, live last price during the Intraday-hours window
                // (see IntradayElocBase.ReferencePriceAsync in DTS) — referencePriceSource says which.
                referencePrice: data.referencePrice,
                referencePriceSource: data.referencePriceSource,
                defaultPriceThresholdPct: data.defaultPriceThresholdPercentage,
                commitmentRemaining: data.commitmentRemaining,
                // Which acceptance window is locking the Type of VWAP Purchase checkbox right now
                // ("Premarket" | "IntradayHours" | "Neither") — echoed back at submission so DTS can
                // detect a rollover between page-load and submit.
                acceptanceWindow: data.acceptanceWindow,
                ...staticCtx,
            };

            state = {
                shareAmount: ctx.maxShareAmount,
                percentagePct: ctx.defaultPurchasePercentagePct,
                minPriceThreshold: roundTo(ctx.referencePrice * (1 - ctx.defaultPriceThresholdPct / 100), 4),
            };

            renderNotice();

            document.getElementById('ppn-loading').style.display = 'none';
            document.getElementById('ppn-document').style.display = 'block';

            const sendBtn = document.getElementById('ppn-send-btn');
            if (ctx.acceptanceWindow === 'Neither') {
                sendBtn.disabled = true;
                sendBtn.title = 'Outside the acceptance window — this notice cannot be submitted right now.';
            } else {
                sendBtn.disabled = false;
                sendBtn.title = '';
            }
        } catch (err) {
            console.error('[ParticipationPurchaseNotice] Failed to load prefill:', err);
            showError(err.message || 'Failed to load purchase notice data.');
        }
    }

    // Document-text fields — static for now, no customer-facing template-fetch endpoint exists
    // yet (see PARTICIPATION_ELOC_HANDOFF.md). These match the CAPS Intraday Purchase Notice
    // participation template (Admin Dashboard ▸ ELOC ▸ Participation Templates) verbatim.
    async function getStaticTemplateContext(symbol) {
        return {
            companyName: 'Capstone Holding Corp.',
            toName: 'Tumim Stone Capital, LLC',
            toEmail: 'eloc@3ifund.com',
            agreedAcceptedEntity: 'TUMIM STONE CAPITAL, LLC',
            bodyText: 'Reference is made to the Amended and Restated Common Stock Purchase Agreement, dated as of ' +
                'June 11, 2026, between Capstone Holding Corp., a Delaware corporation (the “Company”), and ' +
                'Tumim Stone Capital, LLC, a Delaware limited liability company (the “Agreement”). Capitalized ' +
                'terms used and not otherwise defined herein shall have the meanings given such terms in Annex I to the ' +
                'Agreement. In accordance with and pursuant to Section 3.1 of the Agreement, the Company hereby issues ' +
                'this VWAP Purchase Notice to exercise a VWAP Purchase on the terms set forth below.',
        };
    }

    // ---- Rendering ----

    function renderNotice() {
        setText('ppn-to-name', ctx.toName);
        setText('ppn-to-email', ctx.toEmail);
        document.getElementById('ppn-body-text').textContent = ctx.bodyText || '';

        const companyName = sessionStorage.getItem('company_name') || ctx.companyName || '';
        setText('ppn-company-name-upper', companyName.toUpperCase());

        const entityEl = document.getElementById('ppn-agreed-entity');
        entityEl.textContent = ctx.agreedAcceptedEntity || '';
        entityEl.style.display = ctx.agreedAcceptedEntity ? '' : 'none';

        setText('ppn-dated', formatNyDate());

        renderFieldRows();
    }

    function renderFieldRows() {
        const tbody = document.getElementById('ppn-fields-tbody');
        tbody.innerHTML = '';

        FIELDS.forEach((f) => {
            const tr = document.createElement('tr');

            const labelTd = document.createElement('td');
            labelTd.className = 'pn-field-label';
            labelTd.textContent = f.label;
            tr.appendChild(labelTd);

            const valueTd = document.createElement('td');
            valueTd.className = 'pn-field-value';
            valueTd.appendChild(buildFieldControl(f));
            tr.appendChild(valueTd);

            tbody.appendChild(tr);

            if (f.note) {
                const noteTr = document.createElement('tr');
                const noteTd = document.createElement('td');
                noteTd.colSpan = 2;
                noteTd.className = 'ppn-field-note';
                noteTd.textContent = f.note;
                noteTr.appendChild(noteTd);
                tbody.appendChild(noteTr);
            }
        });
    }

    function buildFieldControl(f) {
        switch (f.kind) {
            case 'locked-checkbox':
                return buildLockedCheckboxGroup(f);
            case 'locked-text':
                return buildLockedText(computedText(f.key));
            case 'editable-integer':
                return buildIntegerInput();
            case 'editable-percent':
                return buildPercentInput();
            case 'editable-currency':
                return buildCurrencyInput();
            default:
                return buildLockedText('—');
        }
    }

    function buildLockedCheckboxGroup(f) {
        const wrap = document.createElement('div');
        wrap.className = 'ppn-checkbox-group ppn-locked';
        const checkedOption = f.key === 'PurchaseType' ? purchaseTypeLabel() : f.checked;
        f.options.forEach((opt) => {
            const label = document.createElement('label');
            label.className = 'ppn-checkbox-option';
            const input = document.createElement('input');
            input.type = 'checkbox';
            input.checked = opt === checkedOption;
            input.disabled = true;
            label.appendChild(input);
            label.appendChild(document.createTextNode(' ' + opt));
            wrap.appendChild(label);
        });
        return wrap;
    }

    // Locked to ctx.acceptanceWindow (computed by DTS, re-checked at submit time) — the customer
    // cannot override which option is checked.
    function purchaseTypeLabel() {
        return ctx.acceptanceWindow === 'Premarket' ? 'Pre-Market VWAP Purchase' : 'Intraday VWAP Purchase';
    }

    function buildLockedText(text) {
        const span = document.createElement('span');
        span.className = 'ppn-locked-value';
        span.id = 'ppn-locked-value-holder';
        span.textContent = text;
        return span;
    }

    function computedText(key) {
        switch (key) {
            case 'PurchaseDate':
                return formatNyDate();
            case 'AggregatePurchasePercentage':
                return '0.00%';
            case 'AggregatePurchasePercentageAfter':
                return formatPct(state.percentagePct);
            case 'VolumeThreshold':
                return formatVolumeThreshold();
            case 'DollarAmountOfCommonStockAvailable':
                return formatCurrency(ctx.commitmentRemaining);
            default:
                return '—';
        }
    }

    function formatVolumeThreshold() {
        if (!state.percentagePct || state.percentagePct <= 0) return '—';
        const threshold = Math.ceil(state.shareAmount / (state.percentagePct / 100));
        return formatNumber(threshold);
    }

    // ---- Editable inputs ----

    function buildIntegerInput() {
        const wrap = document.createElement('div');
        wrap.className = 'ppn-input-wrap';

        // type="text" (not "number") — a native number input can't render comma-grouped digits,
        // and this field is displayed with commas everywhere else on the notice.
        const input = document.createElement('input');
        input.type = 'text';
        input.inputMode = 'numeric';
        input.className = 'form-input ppn-input';
        input.id = 'ppn-input-shares';
        input.value = formatNumber(state.shareAmount);

        const hint = document.createElement('div');
        hint.className = 'ppn-hint';
        hint.id = 'ppn-hint-shares';
        hint.textContent = `Up to ${formatNumber(ctx.maxShareAmount)} shares available`;

        input.addEventListener('input', () => {
            const cursorFromEnd = input.value.length - input.selectionStart;
            const digitsOnly = input.value.replace(/[^\d]/g, '');
            let raw = digitsOnly === '' ? NaN : parseInt(digitsOnly, 10);
            if (!isNaN(raw) && raw > ctx.maxShareAmount) {
                // Hard cap — the Share Amount can never exceed the ownership/commitment ceiling,
                // not merely flag it invalid and let the out-of-range value stand.
                raw = ctx.maxShareAmount;
            }
            input.value = isNaN(raw) ? '' : formatNumber(raw);
            const newPos = Math.max(0, input.value.length - cursorFromEnd);
            input.setSelectionRange(newPos, newPos);

            const valid = !isNaN(raw) && raw >= 1 && raw <= ctx.maxShareAmount;
            state.shareAmount = isNaN(raw) ? 0 : raw;
            setInvalid(input, !valid);
            hint.textContent = valid
                ? `Up to ${formatNumber(ctx.maxShareAmount)} shares available`
                : `Enter a whole number of shares between 1 and ${formatNumber(ctx.maxShareAmount)}`;
            refreshDerivedFields();
        });

        wrap.appendChild(input);
        wrap.appendChild(hint);
        return wrap;
    }

    function buildPercentInput() {
        const wrap = document.createElement('div');
        wrap.className = 'ppn-input-wrap';

        const inputRow = document.createElement('div');
        inputRow.className = 'ppn-input-row';

        const input = document.createElement('input');
        input.type = 'number';
        input.className = 'form-input ppn-input ppn-input-narrow';
        input.id = 'ppn-input-pct';
        input.min = '0';
        input.max = String(ctx.defaultPurchasePercentagePct);
        input.step = '0.01';
        input.value = state.percentagePct;

        const suffix = document.createElement('span');
        suffix.className = 'ppn-input-suffix';
        suffix.textContent = '%';

        const hint = document.createElement('div');
        hint.className = 'ppn-hint';
        hint.id = 'ppn-hint-pct';
        hint.textContent = `0% – ${ctx.defaultPurchasePercentagePct}% (default cap)`;

        input.addEventListener('input', () => {
            let raw = parseFloat(input.value);
            if (!isNaN(raw) && raw > ctx.defaultPurchasePercentagePct) {
                // Hard cap — cannot exceed the default Purchase Percentage.
                raw = ctx.defaultPurchasePercentagePct;
                input.value = String(raw);
            }
            const valid = !isNaN(raw) && raw >= 0 && raw <= ctx.defaultPurchasePercentagePct;
            state.percentagePct = isNaN(raw) ? 0 : raw;
            setInvalid(input, !valid);
            hint.textContent = valid
                ? `0% – ${ctx.defaultPurchasePercentagePct}% (default cap)`
                : `Must be between 0% and ${ctx.defaultPurchasePercentagePct}% — cannot exceed the default`;
            refreshDerivedFields();
        });

        inputRow.appendChild(input);
        inputRow.appendChild(suffix);
        wrap.appendChild(inputRow);
        wrap.appendChild(hint);
        return wrap;
    }

    function buildCurrencyInput() {
        const wrap = document.createElement('div');
        wrap.className = 'ppn-input-wrap';

        const inputRow = document.createElement('div');
        inputRow.className = 'ppn-input-row';

        const prefix = document.createElement('span');
        prefix.className = 'ppn-input-prefix';
        prefix.textContent = '$';

        const input = document.createElement('input');
        input.type = 'number';
        input.className = 'form-input ppn-input';
        input.id = 'ppn-input-minprice';
        input.min = '0';
        input.max = String(ctx.referencePrice);
        input.step = '0.0001';
        input.value = state.minPriceThreshold;

        // "previous close" during the Pre-Market window, "last price" during Intraday-hours —
        // matches which reference price DTS actually used (referencePriceSource).
        const refLabel = ctx.referencePriceSource === 'LastPrice' ? 'last price' : 'previous close';

        const hint = document.createElement('div');
        hint.className = 'ppn-hint';
        hint.id = 'ppn-hint-minprice';
        hint.textContent = `Default: $${roundTo(ctx.referencePrice * (1 - ctx.defaultPriceThresholdPct / 100), 4)} ` +
            `(${refLabel} $${ctx.referencePrice} × (1 − ${ctx.defaultPriceThresholdPct}%)). Max $${ctx.referencePrice} (${refLabel}).`;

        input.addEventListener('input', () => {
            let raw = parseFloat(input.value);
            if (!isNaN(raw) && raw > ctx.referencePrice) {
                // Hard cap — cannot exceed the reference price (previous close / last price).
                raw = ctx.referencePrice;
                input.value = String(raw);
            }
            const valid = !isNaN(raw) && raw >= 0 && raw <= ctx.referencePrice;
            state.minPriceThreshold = isNaN(raw) ? 0 : raw;
            setInvalid(input, !valid);
            hint.textContent = valid
                ? `Default: $${roundTo(ctx.referencePrice * (1 - ctx.defaultPriceThresholdPct / 100), 4)} ` +
                  `(${refLabel} $${ctx.referencePrice} × (1 − ${ctx.defaultPriceThresholdPct}%)). Max $${ctx.referencePrice} (${refLabel}).`
                : `Must be between $0 and $${ctx.referencePrice} (cannot exceed the ${refLabel})`;
        });

        inputRow.appendChild(prefix);
        inputRow.appendChild(input);
        wrap.appendChild(inputRow);
        wrap.appendChild(hint);
        return wrap;
    }

    function setInvalid(input, isInvalid) {
        input.classList.toggle('ppn-input-invalid', isInvalid);
    }

    function refreshDerivedFields() {
        // Two locked fields depend on the editable inputs (AggregatePurchasePercentageAfter
        // mirrors PurchasePercentage; VolumeThreshold is derived from ShareAmount/Percentage).
        // Rebuilding the whole tbody is the simplest correct approach for this small, fixed
        // field set; preserve focus/caret so it doesn't interrupt whichever input the user
        // is actively typing in.
        const activeId = document.activeElement ? document.activeElement.id : null;
        const selStart = document.activeElement && 'selectionStart' in document.activeElement
            ? document.activeElement.selectionStart : null;
        renderFieldRows();
        if (activeId) {
            const toFocus = document.getElementById(activeId);
            if (toFocus) {
                toFocus.focus();
                if (selStart != null && 'setSelectionRange' in toFocus) {
                    try { toFocus.setSelectionRange(selStart, selStart); } catch (e) { /* ignore */ }
                }
            }
        }
    }

    // ---- Error State ----

    function showError(message) {
        document.getElementById('ppn-loading').style.display = 'none';
        document.getElementById('ppn-error-message').textContent = message;
        document.getElementById('ppn-error').style.display = 'block';
    }

    // ---- Submission ----

    async function submitNotice() {
        const sendBtn = document.getElementById('ppn-send-btn');
        hideBanner('ppn-window-changed-banner');
        hideBanner('ppn-submit-error-banner');
        hideBanner('ppn-submit-success-banner');
        sendBtn.disabled = true;
        const originalLabel = sendBtn.textContent;
        sendBtn.textContent = 'Submitting…';

        try {
            const payload = {
                symbol: ctx.symbol,
                purchaseShareAmount: state.shareAmount,
                purchasePercentage: state.percentagePct,
                minimumPriceThreshold: state.minPriceThreshold,
                assumedWindow: ctx.acceptanceWindow,
            };
            console.log('[ParticipationPurchaseNotice] Submitting:', payload);
            const result = await API.submitIntradayPurchaseNotice(payload);
            console.log('[ParticipationPurchaseNotice] Submitted:', result);

            sendBtn.textContent = 'Submitted';
            showBanner('ppn-submit-success-banner',
                `Purchase notice ${result.elocId} submitted successfully.`);
            startLiveProgress(result.elocId);
        } catch (err) {
            console.error('[ParticipationPurchaseNotice] Submit failed:', err);
            const code = err.detail && err.detail.code;

            if (code === 'WINDOW_CHANGED') {
                applyWindowChange(err.detail);
                showBanner('ppn-window-changed-banner',
                    'The pricing window changed while you were completing this notice. ' +
                    'The Type of VWAP Purchase and Minimum Price Threshold below have been updated ' +
                    'to match — please review and submit again.');
                sendBtn.textContent = originalLabel;
                sendBtn.disabled = false;
            } else if (code === 'ELOC_ALREADY_PRICING') {
                showBanner('ppn-submit-error-banner',
                    'An ELOC for this company is already in progress. Wait for it to complete before submitting another.');
                sendBtn.textContent = originalLabel;
                sendBtn.disabled = false;
            } else {
                showBanner('ppn-submit-error-banner', err.message || 'Failed to submit purchase notice.');
                sendBtn.textContent = originalLabel;
                sendBtn.disabled = false;
            }
        }
    }

    // Applies the corrected values DTS returned with a WINDOW_CHANGED rejection: the notice must be
    // reviewed and re-submitted by the customer, never silently resubmitted under the new window.
    // The Minimum Price Threshold is deliberately overridden with the fresh default — a value
    // computed against the old reference price has no valid meaning under the new one.
    function applyWindowChange(detail) {
        ctx.acceptanceWindow = detail.correctWindow;
        ctx.referencePrice = detail.referencePrice;
        ctx.referencePriceSource = detail.referencePriceSource;
        ctx.defaultPriceThresholdPct = detail.defaultPriceThresholdPercentage;
        ctx.maxShareAmount = detail.maxShareAmount;

        state.minPriceThreshold = roundTo(detail.minimumPriceThresholdDefault, 4);
        state.shareAmount = Math.min(state.shareAmount, ctx.maxShareAmount);

        renderNotice();
    }

    function showBanner(id, message) {
        const el = document.getElementById(id);
        el.textContent = message;
        el.hidden = false;
    }

    function hideBanner(id) {
        const el = document.getElementById(id);
        el.hidden = true;
    }

    // ---- Live progress (after submission, while the VWAP valuation window is pricing) ----
    //
    // Pushed in real time over the same /ws/workflows channel dashboard.js uses (company-scoped —
    // messages for any of this company's Intraday notices arrive here; only one can be active at a
    // time, so filtering by our own elocId is enough). Number of Shares = (currentVolume −
    // startingVolume) × VWAP Purchase Percentage — computed and pushed by DTS's
    // IntradayElocPricingManager, not polled.

    const LIVE_PROGRESS_STATUS_LABELS = {
        WaitingForTradingStart: 'Waiting for Intraday Trading Start Time…',
        Monitoring: 'Pricing in progress — live',
        TerminatedMaxShares: 'Complete — target share amount reached',
        TerminatedPriceBreach: 'Ended — price fell below the Minimum Price Threshold',
    };
    let liveProgressElocId = null;
    let liveProgressWs = null;
    let liveProgressReconnectTimer = null;

    async function startLiveProgress(elocId) {
        liveProgressElocId = elocId;
        document.getElementById('ppn-live-progress').hidden = false;

        // Initial paint from a one-time fetch — the WS may take a moment to (re)connect, and this
        // guarantees the display isn't blank the instant the success banner appears.
        try {
            const progress = await API.getIntradayLiveProgress(ctx.symbol);
            renderLiveProgress(progress.sharesAccumulated, progress.purchaseShareAmount, progress.status);
        } catch (err) {
            console.warn('[ParticipationPurchaseNotice] Initial live-progress fetch failed:', err);
        }

        connectLiveProgressWs();
    }

    function connectLiveProgressWs() {
        const token = sessionStorage.getItem('access_token');
        if (!token) {
            console.warn('[ParticipationPurchaseNotice] No access_token, skipping live-progress WS connect');
            return;
        }

        const baseUrl = window.PORTAL_CONFIG?.apiBaseUrl || `http://${window.location.hostname}:8000`;
        const wsUrl = baseUrl.replace(/^http/, 'ws') + `/ws/workflows?token=${encodeURIComponent(token)}`;
        console.log('[ParticipationPurchaseNotice] Connecting live-progress WS');

        liveProgressWs = new WebSocket(wsUrl);

        liveProgressWs.onopen = () => console.log('[ParticipationPurchaseNotice] Live-progress WS connected');

        liveProgressWs.onmessage = (event) => {
            let msg;
            try { msg = JSON.parse(event.data); } catch (e) { return; }
            if (msg.type !== 'intraday_progress' || msg.eloc_id !== liveProgressElocId) return;

            renderLiveProgress(msg.shares_accumulated, msg.purchase_share_amount, msg.status);

            if (msg.status === 'TerminatedMaxShares' || msg.status === 'TerminatedPriceBreach') {
                if (liveProgressWs) { liveProgressWs.onclose = null; liveProgressWs.close(); liveProgressWs = null; }
            }
        };

        liveProgressWs.onclose = (event) => {
            console.warn('[ParticipationPurchaseNotice] Live-progress WS closed: code=%d', event.code);
            if (liveProgressElocId) liveProgressReconnectTimer = setTimeout(connectLiveProgressWs, 5000);
        };

        liveProgressWs.onerror = (event) => {
            console.error('[ParticipationPurchaseNotice] Live-progress WS error:', event);
        };
    }

    function renderLiveProgress(sharesAccumulated, purchaseShareAmount, status) {
        document.getElementById('ppn-live-progress-value').textContent =
            `${formatNumber(sharesAccumulated)} of ${formatNumber(purchaseShareAmount)} shares`;
        document.getElementById('ppn-live-progress-status').textContent =
            LIVE_PROGRESS_STATUS_LABELS[status] || status;
    }

    // ---- Formatting Utilities ----

    function setText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    function formatNyDate() {
        return new Intl.DateTimeFormat('en-US', {
            timeZone: 'America/New_York',
            year: 'numeric',
            month: 'long',
            day: 'numeric',
        }).format(new Date());
    }

    function formatNumber(n) {
        if (n == null || isNaN(n)) return '—';
        return new Intl.NumberFormat('en-US').format(n);
    }

    function formatCurrency(n) {
        if (n == null || isNaN(n)) return '—';
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            minimumFractionDigits: 2,
        }).format(n);
    }

    function formatPct(n) {
        if (n == null || isNaN(n)) return '—';
        return Number(n).toFixed(2) + '%';
    }

    function roundTo(n, decimals) {
        const factor = Math.pow(10, decimals);
        return Math.round(n * factor) / factor;
    }

    // ---- Bootstrap ----

    document.addEventListener('DOMContentLoaded', init);

    return { init };
})();
