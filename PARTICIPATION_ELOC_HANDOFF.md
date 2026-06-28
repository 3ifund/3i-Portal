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

## Status — what is NOT done

1. **The participation pricing/workflow engine** — the live, tick-driven engine that:
   - consumes DTS tick data (last price + cumulative tape volume),
   - tracks the three termination triggers (price < `max(explicit, implicit)` floor [SEE OPEN
     ITEM #1], EOD 16:00 ET, cumulative volume ≥ `V0 + shares/participation`),
   - accrues emergent DTO shares (`participation × period volume`, capped at target; partial
     fills allowed),
   - computes the period base price (VWAP / Low / avg of n **distinct** lowest) and applies
     `AgreedDiscountPercentage`,
   - maintains the running n-lowest-distinct-prices list (see design doc §8),
   - enforces concurrency (Pre-Market + Intraday under an aggregate participation cap; no
     overlapping intradays).
2. **The template→values merge** — the workflow code that builds a `ParticipationDocumentModel`
   by merging a Portal-authored template (labels/order/visibility) with **computed** field
   values, then calls the renderer. (The renderer itself is done; only the merge/feeder is not.)
3. **New persistence + workflow states** for live sessions.
4. **A bespoke Portal entry form + live monitor** for the client.

## Open decisions (BLOCKING the engine)

- **OPEN ITEM #1 — Minimum Price Threshold: either/or vs `max(explicit, implicit)`.**
  The PN form reads as *either/or* (designate `$X`, or blank → default % of reference). An
  earlier decision set the engine floor = `max(explicit, implicit)` (both always live). These
  conflict and determine when the period terminates. **Unresolved — decide before the engine.**
- **OPEN ITEM #2 — concurrency rules.** Whether the aggregate participation cap is enforced
  only at creation or re-checked live; the no-overlapping-intraday lock scope (symbol vs deal).

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

Claude Code conversations do **not** sync across machines (local transcripts only). To continue:

1. Clone/pull the repos:
   - `https://github.com/3ifund/DealTermsServer.git`
   - `https://github.com/3ifund/3i-Portal.git`
   - `https://github.com/3ifund/PositionRiskManagement.git` (separate, allocation-dialog fix)
2. Read this file + `DealTermsServer/docs/participation-eloc-field-catalog.md` + recent
   `git log` in DTS and 3i-Portal (commit messages narrate each step).
3. Start a fresh Claude Code session and prime it: *"Continue the participation-ELOC work — read
   PARTICIPATION_ELOC_HANDOFF.md and the participation-eloc-field-catalog.md design doc. Next:
   resolve OPEN ITEM #1, then build the pricing/workflow engine."*

### Won't transfer (machine-local): the chat transcript, Claude memory, and
`%APPDATA%\TradingPlatform\database-config.json` (re-set the DB host at work).

## Suggested next step

Resolve **OPEN ITEM #1**, then spec + build the participation pricing engine (the live
tick-driven session), followed by the template→values merge that feeds the existing renderer.
