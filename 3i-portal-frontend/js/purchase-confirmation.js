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
        const token = sessionStorage.getItem('access_token');
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

        // Header.
        //   "To:"     ← data.to_name  (live: eloc_deal.to via DTS WPF ELOC Deal Mgmt)
        //   "E-mail:" ← data.to_email (live: company.email_addresses[0] via data-management-ui)
        // Both come from the DTS /document-recipients endpoint, resolved live each
        // page load — see backend confirmation-prefill. Empty string if the DB
        // value is missing or DTS was unreachable (page still renders).
        const firmSig = data.firm_signature || {};
        document.getElementById('pc-to-name').textContent = data.to_name || '';
        document.getElementById('pc-to-email').textContent = data.to_email || '';
        console.log('[PurchaseConfirmation] header recipients:',
            'to_name=', data.to_name, '[' + (data.to_name_source || '?') + ']',
            'to_email=', data.to_email, '[' + (data.to_email_source || '?') + ']',
            'firm.email=', firmSig.email, '[block_source=' + (data.firm_signature_source || '?') + ']');

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
        displaySignatory(data.signatory);

        // Wire up events
        // Signatory dropdown removed — user's signatory auto-displayed from profile
        document.getElementById('pc-submit-btn').addEventListener('click', openConfirmDialog);
    }

    // ---- Signatory Display (auto from user profile) ----

    function displaySignatory(sig) {
        const submitBtn = document.getElementById('pc-submit-btn');

        // Hide the dropdown if it exists
        const selectEl = document.getElementById('pc-signatory-select');
        if (selectEl) selectEl.style.display = 'none';

        if (sig && sig.signatory_name) {
            const nameEl = document.getElementById('pc-signatory-name');
            const titleEl = document.getElementById('pc-signatory-title');

            nameEl.textContent = sig.signatory_name;
            nameEl.style.display = 'inline';
            document.getElementById('pc-signatory-name-line').style.display = 'none';

            titleEl.textContent = sig.signatory_title || '';
            titleEl.style.display = sig.signatory_title ? 'inline' : 'none';
            document.getElementById('pc-signatory-title-line').style.display = sig.signatory_title ? 'none' : '';

            if (sig.signatory_signature_image) {
                const sigImg = document.getElementById('pc-signatory-signature');
                sigImg.src = sig.signatory_signature_image;
                sigImg.style.display = 'inline-block';
                document.getElementById('pc-signature-line-co').style.display = 'none';
            } else {
                document.getElementById('pc-signatory-signature').style.display = 'none';
                document.getElementById('pc-signature-line-co').style.display = '';
            }

            submitBtn.disabled = !(sig.signatory_title && sig.signatory_signature_image);
        } else {
            document.getElementById('pc-signatory-name').style.display = 'none';
            document.getElementById('pc-signatory-name-line').style.display = '';
            document.getElementById('pc-signatory-title').style.display = 'none';
            document.getElementById('pc-signatory-title-line').style.display = '';
            document.getElementById('pc-signatory-signature').style.display = 'none';
            document.getElementById('pc-signature-line-co').style.display = '';
            submitBtn.disabled = true;
        }
    }

    // ---- Confirm Dialog ----

    function _onPcDisclaimerScroll(e) {
        const el = e.target;
        const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 10;
        if (atBottom) {
            const checkbox = document.getElementById('pc-confirm-checkbox');
            const checkboxLabel = document.getElementById('pc-confirm-checkbox-label');
            checkbox.disabled = false;
            checkboxLabel.style.opacity = '1';
            checkboxLabel.style.pointerEvents = 'auto';
            console.log('[PurchaseConfirmation] Disclaimer scrolled to bottom — checkbox enabled');
        }
    }

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
        const checkboxLabel = document.getElementById('pc-confirm-checkbox-label');
        const acceptBtn = document.getElementById('pc-confirm-accept');
        checkbox.checked = false;
        checkbox.disabled = true;
        checkboxLabel.style.opacity = '0.5';
        checkboxLabel.style.pointerEvents = 'none';
        acceptBtn.disabled = true;

        // Scroll disclaimer back to top and require full scroll
        const scrollArea = overlay.querySelector('.pn-confirm-scroll');
        if (scrollArea) {
            scrollArea.scrollTop = 0;
            scrollArea.removeEventListener('scroll', _onPcDisclaimerScroll);
            scrollArea.addEventListener('scroll', _onPcDisclaimerScroll);
        }

        // Replace elements to remove old event listeners
        const newAcceptBtn = acceptBtn.cloneNode(true);
        acceptBtn.parentNode.replaceChild(newAcceptBtn, acceptBtn);
        newAcceptBtn.addEventListener('click', handleCountersign);

        const newCheckbox = checkbox.cloneNode(true);
        newCheckbox.disabled = true;
        checkbox.parentNode.replaceChild(newCheckbox, checkbox);
        newCheckbox.addEventListener('change', () => {
            newAcceptBtn.disabled = !newCheckbox.checked;
        });

        const cancelBtn = document.getElementById('pc-confirm-cancel');
        const newCancelBtn = cancelBtn.cloneNode(true);
        cancelBtn.parentNode.replaceChild(newCancelBtn, cancelBtn);
        newCancelBtn.addEventListener('click', () => {
            overlay.style.display = 'none';
        });
    }

    // ---- Submit Countersign ----

    async function handleCountersign() {
        const acceptBtn = document.getElementById('pc-confirm-accept');
        acceptBtn.disabled = true;
        acceptBtn.textContent = 'Submitting...';

        // Signatory is pulled from user's profile on the backend
        const payload = {
            eloc_id: prefillData.eloc_id,
        };

        try {
            const result = await API.submitCountersign(payload);
            console.log('[PurchaseConfirmation] Countersign result:', result);

            // Hide confirm dialog
            document.getElementById('pc-confirm-overlay').style.display = 'none';

            // Show success with download option
            showSuccessWithDownload(prefillData.eloc_id);
        } catch (err) {
            console.error('[PurchaseConfirmation] Countersign error:', err);
            acceptBtn.disabled = false;
            acceptBtn.textContent = 'Accept and Submit';
            alert('Error: ' + (err.message || 'Failed to submit countersign.'));
        }
    }

    // ---- Success + Download ----

    function showSuccessWithDownload(elocId) {
        // Replace the document content with a success message + download button
        const doc = document.getElementById('pc-document');
        doc.innerHTML = `
            <div style="text-align:center; padding:3rem 1rem;">
                <h2 style="color:var(--badge-green); margin-bottom:1rem;">Purchase Confirmation Countersigned Successfully</h2>
                <p style="color:var(--text-secondary); margin-bottom:2rem;">
                    The countersigned Purchase Confirmation has been submitted and emailed to the relevant parties.
                </p>
                <div style="display:flex; gap:1rem; justify-content:center;">
                    <button class="btn btn-primary" id="pc-download-btn">Download Countersigned PDF</button>
                    <button class="btn btn-secondary" id="pc-return-btn">Return to Dashboard</button>
                </div>
                <p id="pc-download-status" style="color:var(--text-secondary); margin-top:1rem; font-size:0.9rem;"></p>
            </div>
        `;

        document.getElementById('pc-return-btn').addEventListener('click', () => {
            window.location.href = 'dashboard.html';
        });

        document.getElementById('pc-download-btn').addEventListener('click', async () => {
            const statusEl = document.getElementById('pc-download-status');
            statusEl.textContent = 'Downloading...';
            try {
                const docData = await API.getPortalElocDocument(elocId, 'CountersignedPurchaseConfirmation');
                if (docData && docData.pdf_base64) {
                    // Convert base64 to blob and trigger download
                    const byteCharacters = atob(docData.pdf_base64);
                    const byteNumbers = new Array(byteCharacters.length);
                    for (let i = 0; i < byteCharacters.length; i++) {
                        byteNumbers[i] = byteCharacters.charCodeAt(i);
                    }
                    const byteArray = new Uint8Array(byteNumbers);
                    const blob = new Blob([byteArray], { type: 'application/pdf' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = docData.filename || elocId + '-CountersignedPurchaseConfirmation.pdf';
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                    statusEl.textContent = 'Download complete.';
                } else {
                    statusEl.textContent = 'PDF not yet available. Please try again in a moment.';
                }
            } catch (err) {
                console.error('[PurchaseConfirmation] Download error:', err);
                statusEl.textContent = 'Download failed: ' + (err.message || 'Unknown error');
            }
        });
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
