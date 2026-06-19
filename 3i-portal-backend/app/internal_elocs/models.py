"""
3i Fund Portal — Internal (PRM-replica) ELOC schemas.

The client-facing `app.elocs.models` filters the workflow down to 4 visible
steps for forward / 1 for backward — what a company user needs to see. This
module is the internal/admin counterpart that mirrors PRM-WPF and shows the
FULL workflow: 10 steps for forward, 4 for backward, no filtering.

We deliberately keep this separate from `app.elocs.models` so the two views
can evolve independently without one accidentally widening or narrowing the
other.
"""

import logging
from enum import Enum

from pydantic import BaseModel

logger = logging.getLogger("portal.internal_elocs.models")


class InternalWorkflowStep(str, Enum):
    """
    All Portal-flow workflow steps PRM-WPF surfaces.

    Wire values match the C# DTS enum (DealTermsServer.Models.Eloc.ElocWorkflowStep).
    Order matches PRM's PortalForwardWorkflowStepOrder in
    PositionRiskManagement\\Models\\Eloc\\Eloc.cs.
    """
    SignedContractToCompany = "SignedContractToCompany"
    SavedContractToSharePoint = "SavedContractToSharePoint"
    SignedContractToPrimeBroker = "SignedContractToPrimeBroker"
    DeemedToOwnPosition = "DeemedToOwnPosition"
    FinalVwapPricingCalculated = "FinalVwapPricingCalculated"
    VwapNotificationToCompany = "VwapNotificationToCompany"
    VwapCountersignedToCompany = "VwapCountersignedToCompany"
    ReceivedCountersignedVwapNotification = "ReceivedCountersignedVwapNotification"
    SavedVwapToSharePoint = "SavedVwapToSharePoint"
    VwapNotificationToPrimeBroker = "VwapNotificationToPrimeBroker"


class InternalWorkflowStepState(str, Enum):
    """Matches the C# WorkflowStepState enum DTS broadcasts on the wire."""
    Pending = "Pending"
    InProgress = "InProgress"
    Completed = "Completed"
    Rejected = "Rejected"
    Failed = "Failed"


# Short labels (mirrors WorkflowStepToLabelConverter.cs in PRM).
# Used by REST initial-state responses; the web app keeps its own copy too,
# but emitting both makes the API self-describing.
INTERNAL_STEP_LABELS: dict[InternalWorkflowStep, str] = {
    InternalWorkflowStep.SignedContractToCompany: "To Co",
    InternalWorkflowStep.SavedContractToSharePoint: "Save Doc",
    InternalWorkflowStep.SignedContractToPrimeBroker: "To PB",
    InternalWorkflowStep.DeemedToOwnPosition: "Deemed",
    InternalWorkflowStep.FinalVwapPricingCalculated: "Final $",
    InternalWorkflowStep.VwapNotificationToCompany: "Notify Co",
    InternalWorkflowStep.VwapCountersignedToCompany: "Co Sign",
    InternalWorkflowStep.ReceivedCountersignedVwapNotification: "Recv VWAP",
    InternalWorkflowStep.SavedVwapToSharePoint: "Save VWAP",
    InternalWorkflowStep.VwapNotificationToPrimeBroker: "Notify PB",
}


# Forward pricing: full 10-step order. Mirrors PortalForwardWorkflowStepOrder
# in PositionRiskManagement\Models\Eloc\Eloc.cs (line 168).
PORTAL_FORWARD_STEPS: list[InternalWorkflowStep] = [
    InternalWorkflowStep.SignedContractToCompany,
    InternalWorkflowStep.SavedContractToSharePoint,
    InternalWorkflowStep.SignedContractToPrimeBroker,
    InternalWorkflowStep.DeemedToOwnPosition,
    InternalWorkflowStep.FinalVwapPricingCalculated,
    InternalWorkflowStep.VwapNotificationToCompany,
    InternalWorkflowStep.VwapCountersignedToCompany,
    InternalWorkflowStep.ReceivedCountersignedVwapNotification,
    InternalWorkflowStep.SavedVwapToSharePoint,
    InternalWorkflowStep.VwapNotificationToPrimeBroker,
]


# Backward pricing: abbreviated 4-step order. Mirrors PortalBackwardWorkflowStepOrder
# in PositionRiskManagement\Models\Eloc\Eloc.cs (line 186). Price is
# pre-calculated; workflow ends at DeemedToOwnPosition.
PORTAL_BACKWARD_STEPS: list[InternalWorkflowStep] = [
    InternalWorkflowStep.SignedContractToCompany,
    InternalWorkflowStep.SavedContractToSharePoint,
    InternalWorkflowStep.VwapNotificationToPrimeBroker,
    InternalWorkflowStep.DeemedToOwnPosition,
]


def derive_workflow_steps(
    current_step: str,
    current_status: str,
    pricing_direction: str = "Forward",
) -> list[dict]:
    """
    Port of PRM's `Eloc.DerivePortalWorkflowSteps`. Returns one entry per
    step (10 forward / 4 backward), each `{key, label, state}`.

    Rules:
      - When current_step isn't in the order list (or unknown), all steps
        get state="Pending" — matches PRM's behavior when currentIndex < 0.
      - Steps before current → "Completed".
      - The current step → carries the passed status (verbatim).
      - Steps after current → "Pending".

    This is intentionally identical to the PRM-WPF derivation so the web
    UI can render the exact same grid as the desktop app.
    """
    is_backward = (
        pricing_direction is not None
        and str(pricing_direction).strip().lower() == "backward"
    )
    step_order = PORTAL_BACKWARD_STEPS if is_backward else PORTAL_FORWARD_STEPS

    try:
        current_enum = InternalWorkflowStep(current_step)
        current_idx = step_order.index(current_enum)
    except (ValueError, KeyError):
        current_enum = None
        current_idx = -1

    logger.debug(
        "derive_workflow_steps: current=%s/%s direction=%s idx=%s",
        current_step, current_status, pricing_direction, current_idx,
    )

    steps: list[dict] = []
    for i, step in enumerate(step_order):
        if current_idx < 0:
            state = InternalWorkflowStepState.Pending.value
        elif i < current_idx:
            state = InternalWorkflowStepState.Completed.value
        elif i == current_idx:
            state = current_status
        else:
            state = InternalWorkflowStepState.Pending.value

        steps.append({
            "key": step.value,
            "label": INTERNAL_STEP_LABELS[step],
            "state": state,
        })

    return steps


# ---- Response/payload schemas ----------------------------------------------


class InternalElocWorkflowStep(BaseModel):
    """One cell of the workflow grid in the internal UI."""
    key: str
    label: str
    state: str


class InternalElocState(BaseModel):
    """
    Shape returned by GET /api/internal/elocs/states/included and also pushed
    as the body of workflow_update WebSocket frames. Carries the raw DTS
    enums (workflow_step, status, pricing_direction) PLUS a pre-derived
    steps list so the frontend can render without re-running the derivation
    on first paint.
    """
    eloc_id: str
    company_id: int
    company_symbol: str | None = None
    workflow_step: str
    status: str
    pricing_direction: str
    workflow_complete: bool = False
    modified_at: str | None = None
    steps: list[InternalElocWorkflowStep] = []


class InternalDeleteResponse(BaseModel):
    """
    Forwarded body of the DTS DELETE response (see PortalElocController.DeleteState).
    Carries the delta-reversal outcomes so the web UI can show the operator
    exactly what hit eloc_deal.
    """
    status: str
    eloc_id: str
    deleted_count: int = 0
    shares_reversed: bool = False
    commitment_reversed: bool = False
    shares_outcome: str | None = None
    commitment_outcome: str | None = None
