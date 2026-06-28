# Participation-ELOC Work — Handoff / "Start Here"

> Cross-machine handoff note. An **identical copy lives in both repos**:
> `DealTermsServer/PARTICIPATION_ELOC_HANDOFF.md` and
> `3i-Portal/PARTICIPATION_ELOC_HANDOFF.md`.
> This work spans **three** repos: **DealTermsServer** (DTS), **3i-Portal**, and
> conceptually the participation pricing engine that is **not yet built**.

## What this is

A new **participation-based ELOC** flow for two purchase types — **Pre-Market (1-day)**
and **Intraday** — that is fundamentally different from the existing ELOC workflow. The
core divergence: **Deemed-to-Own (DTO) shares are an _output_, not an _input_**. The client
specifies only a **target (max shares) + participation %**; the realized share count emerges
path-dependently from market volume and termination triggers (and may partially fill).

Because of that, this needs **new workflow + new pricing services** — not a branch in the
existing ones. We are building it additively; the legacy ELOC workflow, templates, and PDF
stack are **left untouched**.

The full design (both field enums, price chain, n-lowest rule, termination logic, open items)
is in **`DealTermsServer/docs/participation-eloc-field-catalog.md`** — read that first.

## Status — what is DONE (all committed + pushed)

### DealTermsServer (C#)
- **Field catalog enums + descriptors** — `DealTermsServer/Models/Templates/`
  (`PurchaseNoticeField`, `PurchaseConfirmationField`, option enums, `FieldDescriptor`,
  `TemplateFieldCatalog`).
- **Catalog API** — `Controllers/TemplateFieldCatalogController.cs`:
  `GET /api/template-field-catalog` and `/{documentType}`.
- **Fresh PDF renderer (Option B)** — `Services/Eloc/ParticipationPdf/`
  (`ParticipationPdfRenderer`, `ParticipationDocumentModel`) using iText (already referenced).
  Preview endpoint: `Controllers/ParticipationPdfController.cs` →
  `POST /api/participation-pdf/preview`.
- **Design doc** — `docs/participation-eloc-field-catalog.md`.
- **Workflow routing read** — `Services/Eloc/Participation/ParticipationTemplateReader.cs` +
  `PortalPurchaseNoticeController`: at PN submission, resolves the mapped participation template's
  `allocation_type` from the portal Mongo and records the route on `eloc_data` (`Unknown` ⇒
  participation, `Known`/absent ⇒ legacy; absent mapping ⇒ legacy, so existing traffic is
  unaffected). `GetMappedTemplateAsync` also returns full template content for PDF construction.
- **PN PDF construction service** — `Services/Eloc/ParticipationPdf/ParticipationPurchaseNoticePdfService.cs`:
  resolves the mapped template + merges supplied field values + signatories, rendered in the
  **existing PN layout** (title/header/body/dynamic field rows/company + Agreed-and-Accepted
  signature blocks with images) by the enriched `ParticipationPdfRenderer`. Endpoint:
  `POST /api/participation-pdf/purchase-notice` (construct from stored template).
- **Shared `ElocContractDeliveryService`** — `Services/Eloc/ElocContractDeliveryService.cs`:
  the contract-step actions (SharePoint upload + broker/company/admin notifications) extracted
  from `PortalElocController` so legacy and participation run **identical** step logic (option A —
  no duplication). The controller's step methods now delegate to it.
- **`ParticipationWorkflowManager` (first 3 steps)** — `Services/Eloc/Participation/ParticipationWorkflowManager.cs`:
  runs Save-to-SharePoint → Send-to-Prime-Broker (+ company + admin) via the shared service,
  advancing `eloc_state` to `SignedContractToPrimeBroker` and stopping (pricing engine is a later
  phase). Has a duplicate-run guard.
- **Unknown branch WIRED end-to-end** — submission builds the participation PN PDF (best-effort
  field values; full set awaits the entry form) and the **accept** endpoint
  (`PortalElocController`, from `SignedContractToCompany`) runs the manager instead of the legacy
  auto-process chain for `allocation_type=Unknown`. Legacy (Known) unchanged.

### 3i-Portal (Python FastAPI backend + vanilla JS frontend)
- **Template backend** — `3i-portal-backend/app/participation_templates/`
  (named, company-specific templates + a **separate** `(company, pricing_period, document_type)
  → template` mapping). Mongo collections: `participation_templates`,
  `participation_template_mappings`. Unique indexes ensured at startup.
- **Catalog + PDF proxies** — admin endpoints under `/admin`:
  `participation-templates` (CRUD), `participation-template-mappings` (CRUD + resolve),
  `participation-field-catalog/{documentType}` (proxies DTS), `participation-pdf/preview`
  (proxies DTS renderer). DTS calls go through `app/onprem/client.py`.
- **Admin editor UI** — new "Participation Templates" tab in
  `3i-portal-frontend/admin.html` + `js/admin.js` + `js/api.js`: pick document type + company,
  create/edit/delete named templates, build fields from the catalog dropdown (per-field label
  text + visible toggle), manage pricing-period mappings, and **Preview PDF** (renders the
  current unsaved template via DTS).
- **Share Allocation discriminator** — the editor has a "Share Allocation" radio (Known /
  Unknown) stored as `allocation_type` on the template doc; **absent ⇒ legacy/Known**. This is
  the workflow router DTS reads at submission.

## Status — what is NOT done

1. **The participation pricing/workflow engine** — the live, tick-driven engine that:
   - consumes DTS tick data (last price + cumulative tape volume),
   - tracks the three termination triggers (price < the COALESCE floor `effectivefloorprice`
     [see design doc §10], EOD 16:00 ET, cumulative volume ≥ `V0 + shares/participation`),
   - accrues emergent DTO shares (`participation × period volume`, capped at target; partial
     fills allowed),
   - computes the period base price (VWAP / Low / avg of n **distinct** lowest) and applies
     `AgreedDiscountPercentage`,
   - maintains the running n-lowest-distinct-prices list (see design doc §8),
   - enforces concurrency (Pre-Market + Intraday under an aggregate participation cap; no
     overlapping intradays).
   (The first 3 contract steps — Send to Company / SharePoint / Prime Broker — are DONE; the engine
   is the divergence after them.)
2. **A bespoke Portal entry form + live monitor** for the client. The entry form is what supplies
   the full participation field VALUES (PurchaseType, PurchasePercentage, MinimumPriceThreshold /
   statedfloorprice, etc.). Until it exists, the submission maps only best-effort values
   (PurchaseShareAmount, PurchaseDate) + signatories, so other fields render blank on the PN PDF.
3. **New persistence + workflow states** for live participation pricing sessions.
4. **Runtime verification** — the workflow refactor + Unknown wiring compile but are NOT yet
   exercised live (needs a mapped Unknown template, a submission, and an accept against a running
   DTS with SharePoint/email configured). The extraction moved outward-facing email code verbatim;
   smoke-test the legacy flow too.

## Open decisions

- **OPEN ITEM #1 — Minimum Price Threshold — RESOLVED: COALESCE (not max).**
  `effectivefloorprice = COALESCE(statedfloorprice, referenceprice × defaulttriggerpercentage)`.
  A Company-stated dollar price **controls even below the default**; the percentage only derives
  the default when none is stated. Reference per type: pre-market = prior RTH close; intraday =
  last sale at notice delivery. The per-period default % reuses the existing
  `default_minimum_price_percentage` / `use_default_minimum_price_percentage` columns on
  `eloc_pricing_period` (already wired in data-management-ui). **WATCH:** an amendment saying
  "the higher of the stated price and 75% of [reference]" would flip this back to `max`. See
  design doc §10.
- **OPEN ITEM #2 — concurrency rules (still open).** Whether the aggregate participation cap is
  enforced only at creation or re-checked live; the no-overlapping-intraday lock scope (symbol vs
  deal).

## Settled design points (from the design sessions)

- Two separate enums (PN client-input vs PC computed); shared names differ in meaning
  (`PurchaseShareAmount`: PN = target, PC = final fill).
- Price chain: `PeriodBasePrice × AgreedDiscountPercentage = PurchasePrice`;
  `× PurchaseShareAmount = AggregatePurchasePrice`.
- Pricing methods: VWAP, Low Price, Average of n **distinct** lowest prices (tick-level samples).
- n-lowest list: bounded size n, evict-the-max on a lower distinct price, equal reprints are
  no-ops, breaching tick excluded; truncated period → average over however many exist (default).
- Volume trigger absolute level = tape volume at notice time + `shares / participation`.
- PDF generation = "Option B" (fresh renderer, existing Python PDF stack untouched).

## Verification status

- DTS builds clean (0 errors). Portal backend `py_compile` clean. Frontend `node --check` clean.
- **NOT yet runtime-verified end-to-end.** Needs DTS + Portal running together to exercise:
  editor → save template → map to a pricing period → Preview PDF (editor button → Portal proxy
  → DTS renderer → PDF opens in a new tab).

## How to resume on another machine

Claude Code conversations do **not** sync across machines (local transcripts only). You are not
resuming the chat — you re-orient a fresh session from these repos (everything is committed).

**1. Clone (or `git pull` if you already have them):**

```bash
git clone https://github.com/3ifund/DealTermsServer.git
git clone https://github.com/3ifund/3i-Portal.git
git clone https://github.com/3ifund/PositionRiskManagement.git   # separate, allocation-dialog fix
```

**2. Start Claude Code in a repo:**

```bash
cd 3i-Portal
claude        # run /login if prompted
```

**3. Paste this as your first message (the primer):**

> Continue the participation-ELOC work. Read `PARTICIPATION_ELOC_HANDOFF.md` here and
> `DealTermsServer/docs/participation-eloc-field-catalog.md`, plus the recent `git log` in this
> repo and in DealTermsServer. Then tell me where we left off and what's next.

The next step it should land on: **resolve OPEN ITEM #1** (Minimum Price Threshold: either/or vs
`max(explicit, implicit)`), then build the pricing/workflow engine.

### Won't transfer (machine-local), set these up at work:
- The chat transcript and Claude memory (don't sync — that's why this note exists).
- `%APPDATA%\TradingPlatform\database-config.json` — **re-set the DB host** (or use the app's DB
  settings dialog).
- To actually run DTS + Portal for the end-to-end editor/preview test, install their local deps
  (Python env for the Portal, etc.) on that machine.

## Suggested next step

Resolve **OPEN ITEM #1**, then spec + build the participation pricing engine (the live
tick-driven session), followed by the template→values merge that feeds the existing renderer.
