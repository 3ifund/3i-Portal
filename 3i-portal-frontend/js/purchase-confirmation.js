/**
 * 3i Fund Portal — Purchase Confirmation Countersign Page
 * Displays the VWAP Purchase Confirmation with firm signature (already signed)
 * and allows the company user to countersign.
 */
(function () {
    'use strict';

    let prefillData = null;

    // ---- Init ----

    async function init() {
        console.log('[PurchaseConfirmation] Initializing...');

        // Auth check
        const token = sessionStorage.getItem('token');
        if (!token) {
            window.location.href = 'index.html';
            return;
        }

        // Set company name in navbar
        const companyName = sessionStorage.getItem('company_name');
        const companyEl = document.getElementById('company-name');
        if (companyEl && companyName) companyEl.textContent = companyName;

        // Logout
        document.getElementById('logout-btn').addEventListener('click', () => {
            sessionStorage.clear();
            window.location.href = 'index.html';
        });

        // Back button
        document.getElementById('pc-back-btn').addEventListener('click', () => {
            window.location.href = 'dashboard.html';
        });

        // Get eloc_id from URL
        const params = new URLSearchParams(window.location.search);
        const elocId = params.get('eloc_id');
        if (!elocId) {
            showError('No ELOC ID provided.');
            return;
        }

        console.log('[PurchaseConfirmation] Loading prefill for', elocId);
        await loadPrefill(elocId);
    }

    // ---- Load Prefill Data ----

    async function loadPrefill(elocId) {
        try {
            prefillData = await API.getPurchaseConfirmationPrefill(elocId);
            console.log('[PurchaseConfirmation] Prefill data:', prefillData);

            if (!prefillData) {
                showError('No confirmation data found for this ELOC.');
                return;
            }

            renderConfirmation(prefillData);
        } catch (err) {
            console.error('[PurchaseConfirmation] Prefill error:', err);
            showError(err.message || 'Failed to load purchase confirmation data.');
        }
    }

    // ---- Render ----

    function renderConfirmation(data) {
        // Hide loading, show document
        document.getElementById('pc-loading').style.display = 'none';
        document.getElementById('pc-document').style.display = 'block';

        // Header
        const firmSig = data.firm_signature || {};
        document.getElementById('pc-to-name').textContent = firmSig.email || '';
        document.getElementById('pc-to-email').textContent = firmSig.email || '';

        // Body text
        const bodyEl = document.getElementById('pc-body-text');
        if (data.body_text) {
            bodyEl.innerHTML = data.body_text.replace(/\n/g, '<br>');
        } else {
            bodyEl.innerHTML = '<em style="color:var(--text-secondary);">No template body text configured for this company/period type.</em>';
        }

        // VWAP pricing fields
        document.getElementById('pc-shares').textContent = Number(data.shares || 0).toLocaleString();
        document.getElementById('pc-exercise-date').textContent = data.exercise_date || '';
        document.getElementById('pc-period-start').textContent = data.valuation_period_start || '';
        document.getElementById('pc-period-end').textContent = data.valuation_period_end || '';
        document.getElementById('pc-settlement-date').textContent = data.settlement_date || '';

        const vwapPrice = data.vwap_purchase_price || data.vwap_used;
        if (vwapPrice) {
            document.getElementById('pc-vwap-price').textContent = '$' + Number(vwapPrice).toFixed(6);
        } else {
            document.getElementById('pc-vwap-price').textContent = 'Pending';
        }

        const totalPrice = data.dollar_amount_calculated;
        if (totalPrice) {
            document.getElementById('pc-total-price').textContent = '$' + Number(totalPrice).toFixed(2);
        } else if (vwapPrice && data.shares) {
            document.getElementById('pc-total-price').textContent = '$' + (Number(vwapPrice) * Number(data.shares)).toFixed(2);
        } else {
            document.getElementById('pc-total-price').textContent = 'Pending';
        }

        // Dated
        document.getElementById('pc-dated').textContent = new Date().toLocaleDateString('en-US', {
            month: 'numeric', day: 'numeric', year: '2-digit'
        });

        // Firm signature block (already signed)
        document.getElementById('pc-firm-entity').textContent = data.agreed_accepted_entity || 'TUMIM STONE CAPITAL, LLC';
        document.getElementById('pc-firm-name').textContent = firmSig.name || '';
        document.getElementById('pc-firm-title').textContent = firmSig.title || '';
        document.getElementById('pc-firm-address').textContent = firmSig.address || '';
        document.getElementById('pc-firm-email').textContent = firmSig.email || '';

        if (firmSig.signature_image) {
            const sigImg = document.getElementById('pc-firm-signature');
            sigImg.src = firmSig.signature_image;
            sigImg.style.display = 'inline-block';
            document.getElementById('pc-firm-signature-line').style.display = 'none';
        }

        // Company entity name
        document.getElementById('pc-company-entity').textContent = data.company_name || '';

        // Populate signatory dropdown
        populateSignatoryDropdown(data.signatories || []);

        // Wire up events
        document.getElementById('pc-signatory-select').addEventListener('change', onSignatoryChange);
        document.getElementById('pc-submit-btn').addEventListener('click', openConfirmDialog);
    }

    // ---- Signatory Selection ----

    function populateSignatoryDropdown(signatories) {
        const select = document.getElementById('pc-signatory-select');
        select.innerHTML = '<option value="">-- Select signatory --</option>';
        signatories.forEach((s, idx) => {
            const opt = document.createElement('option');
            opt.value = idx;
            opt.textContent = s.name || `Signatory ${idx + 1}`;
            opt.dataset.name = s.name || '';
            opt.dataset.title = s.title || '';
            opt.dataset.address = s.address || '';
            opt.dataset.signature = s.signature_image || '';
            select.appendChild(opt);
        });
    }

    function onSignatoryChange() {
        const select = document.getElementById('pc-signatory-select');
        const opt = select.options[select.selectedIndex];
        const submitBtn = document.getElementById('pc-submit-btn');

        if (!opt || !opt.value) {
            // No selection
            document.getElementById('pc-signatory-name').style.display = 'none';
            document.getElementById('pc-signatory-name-line').style.display = '';
            document.getElementById('pc-signatory-title').style.display = 'none';
            document.getElementById('pc-signatory-title-line').style.display = '';
            document.getElementById('pc-signatory-signature').style.display = 'none';
            document.getElementById('pc-signature-line-co').style.display = '';
            submitBtn.disabled = true;
            return;
        }

        // Show signatory values
        const nameEl = document.getElementById('pc-signatory-name');
        const titleEl = document.getElementById('pc-signatory-title');
        nameEl.textContent = opt.dataset.name;
        nameEl.style.display = opt.dataset.name ? 'inline' : 'none';
        document.getElementById('pc-signatory-name-line').style.display = opt.dataset.name ? 'none' : '';

        titleEl.textContent = opt.dataset.title;
        titleEl.style.display = opt.dataset.title ? 'inline' : 'none';
        document.getElementById('pc-signatory-title-line').style.display = opt.dataset.title ? 'none' : '';

        // Signature image
        if (opt.dataset.signature) {
            const sigImg = document.getElementById('pc-signatory-signature');
            sigImg.src = opt.dataset.signature;
            sigImg.style.display = 'inline-block';
            document.getElementById('pc-signature-line-co').style.display = 'none';
        } else {
            document.getElementById('pc-signatory-signature').style.display = 'none';
            document.getElementById('pc-signature-line-co').style.display = '';
        }

        submitBtn.disabled = false;
    }

    // ---- Confirm Dialog ----

    function openConfirmDialog() {
        const overlay = document.getElementById('pc-confirm-overlay');
        overlay.style.display = 'flex';

        const companyName = prefillData.company_name || '';
        document.getElementById('pc-confirm-company').textContent = companyName;
        document.getElementById('pc-confirm-company2').textContent = companyName;
        document.getElementById('pc-confirm-shares').textContent = Number(prefillData.shares || 0).toLocaleString();

        const vwapPrice = prefillData.vwap_purchase_price || prefillData.vwap_used;
        document.getElementById('pc-confirm-price').textContent = vwapPrice ? '$' + Number(vwapPrice).toFixed(6) : 'Pending';

        const totalPrice = prefillData.dollar_amount_calculated || (vwapPrice ? vwapPrice * prefillData.shares : null);
        document.getElementById('pc-confirm-total').textContent = totalPrice ? '$' + Number(totalPrice).toFixed(2) : 'Pending';

        document.getElementById('pc-confirm-settlement').textContent = prefillData.settlement_date || '';

        const checkbox = document.getElementById('pc-confirm-checkbox');
        const acceptBtn = document.getElementById('pc-confirm-accept');
        checkbox.checked = false;
        acceptBtn.disabled = true;

        checkbox.addEventListener('change', () => {
            acceptBtn.disabled = !checkbox.checked;
        });

        document.getElementById('pc-confirm-cancel').addEventListener('click', () => {
            overlay.style.display = 'none';
        });

        acceptBtn.addEventListener('click', handleCountersign);
    }

    // ---- Submit Countersign ----

    async function handleCountersign() {
        const acceptBtn = document.getElementById('pc-confirm-accept');
        acceptBtn.disabled = true;
        acceptBtn.textContent = 'Submitting...';

        const select = document.getElementById('pc-signatory-select');
        const opt = select.options[select.selectedIndex];

        const payload = {
            eloc_id: prefillData.eloc_id,
            signatory_name: opt.dataset.name || '',
            signatory_title: opt.dataset.title || '',
            signatory_signature_image: opt.dataset.signature || null,
        };

        try {
            const result = await API.submitCountersign(payload);
            console.log('[PurchaseConfirmation] Countersign result:', result);

            // Success — redirect to dashboard
            alert('Purchase Confirmation countersigned successfully.');
            window.location.href = 'dashboard.html';
        } catch (err) {
            console.error('[PurchaseConfirmation] Countersign error:', err);
            acceptBtn.disabled = false;
            acceptBtn.textContent = 'Accept and Submit';
            alert('Error: ' + (err.message || 'Failed to submit countersign.'));
        }
    }

    // ---- Helpers ----

    function showError(message) {
        document.getElementById('pc-loading').style.display = 'none';
        document.getElementById('pc-error').style.display = 'block';
        document.getElementById('pc-error-message').textContent = message;
    }

    // ---- Start ----
    document.addEventListener('DOMContentLoaded', init);
})();
