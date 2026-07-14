
import logging
from enum import Enum

from pydantic import BaseModel
from datetime import date, time

logger = logging.getLogger("portal.elocs.models")



class WorkflowStepEnum(str, Enum):
    """Sequential steps of the Portal ELOC workflow."""
    SignedContractToCompany = "SignedContractToCompany"
    SavedContractToSharePoint = "SavedContractToSharePoint"
    FinalVwapPricingCalculated = "FinalVwapPricingCalculated"
    VwapNotificationToCompany = "VwapNotificationToCompany"
    VwapCountersignedToCompany = "VwapCountersignedToCompany"
    ReceivedCountersignedVwapNotification = "ReceivedCountersignedVwapNotification"
    SavedVwapToSharePoint = "SavedVwapToSharePoint"
    VwapNotificationToPrimeBroker = "VwapNotificationToPrimeBroker"


class WorkflowStepState(str, Enum):
    """Status of the current workflow step — matches C# WorkflowStepState enum."""
    Pending = "Pending"
    InProgress = "InProgress"
    Completed = "Completed"
    Rejected = "Rejected"
    Failed = "Failed"


WORKFLOW_STEPS_ORDERED = list(WorkflowStepEnum)

WORKFLOW_STEP_LABELS = {
    WorkflowStepEnum.SignedContractToCompany: "Signed Contract to Company",
    WorkflowStepEnum.SavedContractToSharePoint: "Saved Contract to SharePoint",
    WorkflowStepEnum.FinalVwapPricingCalculated: "Final VWAP Pricing Calculated",
    WorkflowStepEnum.VwapNotificationToCompany: "VWAP Notification to Company",
    WorkflowStepEnum.VwapCountersignedToCompany: "VWAP Countersigned to Company",
    WorkflowStepEnum.ReceivedCountersignedVwapNotification: "Received Countersigned VWAP Notification",
    WorkflowStepEnum.SavedVwapToSharePoint: "Saved VWAP to SharePoint",
    WorkflowStepEnum.VwapNotificationToPrimeBroker: "VWAP Notification to Prime Broker",
}

CLIENT_VISIBLE_STEPS = {
    WorkflowStepEnum.SignedContractToCompany,
    WorkflowStepEnum.FinalVwapPricingCalculated,
    WorkflowStepEnum.VwapNotificationToCompany,
    WorkflowStepEnum.ReceivedCountersignedVwapNotification,
}


def build_workflow_steps(
    current_step: str,
    step_status: str,
    pricing_direction: str = "Forward",
    workflow_complete: bool = False,
) -> tuple[list[dict], bool]:
    logger.debug("build_workflow_steps: current=%s/%s, pricing_direction=%s, workflow_complete=%s",
                 current_step, step_status, pricing_direction, workflow_complete)

    if pricing_direction == "Backward":
        if not workflow_complete and current_step == "DeemedToOwnPosition" and step_status == WorkflowStepState.Completed.value:
            logger.info("build_workflow_steps: backward fallback — DeemedToOwnPosition/Completed → treating as workflow_complete")
            workflow_complete = True

        if workflow_complete:
            effective_status = WorkflowStepState.Completed.value
        else:
            effective_status = step_status
        steps = [{
            "key": WorkflowStepEnum.SignedContractToCompany.value,
            "label": "Purchase Notice",
            "status": effective_status,
        }]
        can_remove = (
            workflow_complete
            or step_status in (WorkflowStepState.Rejected.value, WorkflowStepState.Failed.value)
        )
        logger.debug("build_workflow_steps: backward → 1 step, status=%s, can_remove=%s, workflow_complete=%s",
                     effective_status, can_remove, workflow_complete)
        return steps, can_remove

    try:
        current_idx = WORKFLOW_STEPS_ORDERED.index(WorkflowStepEnum(current_step))
    except (ValueError, KeyError):
        current_idx = -1

    last_idx = len(WORKFLOW_STEPS_ORDERED) - 1

    all_steps = []
    for i, step in enumerate(WORKFLOW_STEPS_ORDERED):
        if i < current_idx:
            status = WorkflowStepState.Completed.value
        elif i == current_idx:
            status = step_status
        else:
            status = "Awaiting"
        all_steps.append((step, status))

    steps = []
    for i, (step, status) in enumerate(all_steps):
        if step not in CLIENT_VISIBLE_STEPS:
            continue

        effective_status = status
        for j in range(i + 1, len(all_steps)):
            next_step, next_status = all_steps[j]
            if next_step in CLIENT_VISIBLE_STEPS:
                break
            if effective_status == WorkflowStepState.Completed.value and next_status != WorkflowStepState.Completed.value:
                logger.debug("build_workflow_steps: %s inherits status %s from hidden step %s",
                             step.value, next_status, next_step.value)
                effective_status = next_status

        steps.append({
            "key": step.value,
            "label": WORKFLOW_STEP_LABELS[step],
            "status": effective_status,
        })

    can_remove = (
        workflow_complete
        or step_status in (WorkflowStepState.Rejected.value, WorkflowStepState.Failed.value)
        or (current_idx == last_idx and step_status == WorkflowStepState.Completed.value)
    )

    logger.debug("build_workflow_steps: forward → %d visible steps, can_remove=%s",
                 len(steps), can_remove)

    return steps, can_remove


class PricingPeriod(BaseModel):
    pricing_period_id: int
    period_type: str
    dollar_cap_per_notice: float
    discount_multiplier: float
    volume_pct_cap: float | None = None
    acceptance_window_start: time | None = None
    acceptance_window_end: time | None = None
    use_half_days: bool = False


class ElocSummary(BaseModel):
    eloc_id: str
    company_id: int
    company_symbol: str | None = None
    company_name: str | None = None
    total_commitment: float
    total_commitment_remaining: float
    registered_shares_available: int
    expiration_date: date | None = None
    status: str
    pricing_period_types: list[str] = []
    pricing_periods_count: int = 0


class ElocDetail(BaseModel):
    eloc_id: int
    company_id: int
    company_symbol: str | None = None
    company_name: str | None = None
    total_commitment: float
    total_commitment_used: float
    total_commitment_remaining: float
    registered_shares: int
    registered_shares_used: int
    registered_shares_available: int
    expiration_date: date | None = None
    min_trading_days_between_notices: int = 1
    threshold_price: float | None = None
    beneficial_ownership_limit_pct: float | None = None
    current_shares_outstanding: int | None = None
    status: str
    pricing_periods: list[PricingPeriod] = []


class WorkflowResponse(BaseModel):
    eloc_id: str
    steps: dict[str, str]
    events: dict[str, dict] = {}


class PricingWorkflowState(BaseModel):
    """Workflow state for an ELOC currently pricing."""
    eloc_id: str
    company_id: int
    current_step: str
    step_status: str
    updated_at: str | None = None
    can_remove: bool = False
    steps: list[dict] = []
