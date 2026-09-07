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
            checked: 'Intraday VWAP Purchase',
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
                previousClose: data.previousClose,
                defaultPriceThresholdPct: data.defaultPriceThresholdPercentage,
                commitmentRemaining: data.commitmentRemaining,
                ...staticCtx,
            };

            state = {
                shareAmount: ctx.maxShareAmount,
                percentagePct: ctx.defaultPurchasePercentagePct,
                minPriceThreshold: roundTo(ctx.previousClose * (1 - ctx.defaultPriceThresholdPct / 100), 4),
            };

            renderNotice();

            document.getElementById('ppn-loading').style.display = 'none';
            document.getElementById('ppn-document').style.display = 'block';
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
        f.options.forEach((opt) => {
            const label = document.createElement('label');
            label.className = 'ppn-checkbox-option';
            const input = document.createElement('input');
            input.type = 'checkbox';
            input.checked = opt === f.checked;
            input.disabled = true;
            label.appendChild(input);
            label.appendChild(document.createTextNode(' ' + opt));
            wrap.appendChild(label);
        });
        return wrap;
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

        const input = document.createElement('input');
        input.type = 'number';
        input.className = 'form-input ppn-input';
        input.id = 'ppn-input-shares';
        input.min = '1';
        input.max = String(ctx.maxShareAmount);
        input.step = '1';
        input.value = state.shareAmount;

        const hint = document.createElement('div');
        hint.className = 'ppn-hint';
        hint.id = 'ppn-hint-shares';
        hint.textContent = `Up to ${formatNumber(ctx.maxShareAmount)} shares available`;

        input.addEventListener('input', () => {
            const raw = parseInt(input.value, 10);
            const clamped = isNaN(raw) ? 0 : Math.max(0, Math.min(raw, ctx.maxShareAmount));
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
            const raw = parseFloat(input.value);
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
        input.max = String(ctx.previousClose);
        input.step = '0.0001';
        input.value = state.minPriceThreshold;

        const hint = document.createElement('div');
        hint.className = 'ppn-hint';
        hint.id = 'ppn-hint-minprice';
        hint.textContent = `Default: $${roundTo(ctx.previousClose * (1 - ctx.defaultPriceThresholdPct / 100), 4)} ` +
            `(previous close $${ctx.previousClose} × (1 − ${ctx.defaultPriceThresholdPct}%)). Max $${ctx.previousClose} (previous close).`;

        input.addEventListener('input', () => {
            const raw = parseFloat(input.value);
            const valid = !isNaN(raw) && raw >= 0 && raw <= ctx.previousClose;
            state.minPriceThreshold = isNaN(raw) ? 0 : raw;
            setInvalid(input, !valid);
            hint.textContent = valid
                ? `Default: $${roundTo(ctx.previousClose * (1 - ctx.defaultPriceThresholdPct / 100), 4)} ` +
                  `(previous close $${ctx.previousClose} × (1 − ${ctx.defaultPriceThresholdPct}%)). Max $${ctx.previousClose} (previous close).`
                : `Must be between $0 and $${ctx.previousClose} (cannot exceed the previous close)`;
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
