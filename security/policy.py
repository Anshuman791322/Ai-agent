from __future__ import annotations

import threading

from config.settings import AppSettings
from security.models import (
    ActionRequest,
    ActionType,
    AutonomyMode,
    PolicyDecision,
    PolicyDecisionType,
    RiskTier,
    TrustZone,
)
from security.workspace import WorkspaceJail


_RISK_ORDER = {
    RiskTier.LOW: 0,
    RiskTier.MEDIUM: 1,
    RiskTier.HIGH: 2,
    RiskTier.CRITICAL: 3,
}


def _max_risk(left: RiskTier, right: RiskTier) -> RiskTier:
    return left if _RISK_ORDER[left] >= _RISK_ORDER[right] else right


class PolicyEngine:
    def __init__(self, settings: AppSettings, jail: WorkspaceJail) -> None:
        self.settings = settings
        self.jail = jail
        self._lock = threading.RLock()
        self._mode = settings.autonomy_mode
        self._autonomy_paused = False
        self._deny_high_risk = False

    def mode(self) -> AutonomyMode:
        with self._lock:
            return self._mode

    def set_mode(self, mode: AutonomyMode) -> None:
        with self._lock:
            self._mode = mode

    def set_autonomy_paused(self, paused: bool) -> None:
        with self._lock:
            self._autonomy_paused = paused

    def set_deny_high_risk(self, enabled: bool) -> None:
        with self._lock:
            self._deny_high_risk = enabled

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "mode": self._mode.value,
                "autonomy_paused": self._autonomy_paused,
                "deny_high_risk": self._deny_high_risk,
            }

    def evaluate(self, request: ActionRequest) -> PolicyDecision:
        reasons: list[str] = []
        risk = RiskTier.LOW
        trust_zone = TrustZone.UNKNOWN
        balanced_auto = False

        target_path = request.target_path or request.workspace or (request.allowed_paths[0] if request.allowed_paths else None)
        if target_path is not None:
            assessment = self.jail.classify(target_path)
            trust_zone = assessment.zone
            reasons.append(assessment.reason)
        else:
            assessment = None

        if request.action_type == ActionType.ADVANCED_SHELL:
            return PolicyDecision(
                decision=PolicyDecisionType.BLOCK,
                risk=RiskTier.CRITICAL,
                reasons=("advanced shell execution is not available in this build",),
                trust_zone=trust_zone,
            )

        if request.action_type == ActionType.RUN_WORKSPACE_COMMAND and not request.metadata.get("command_allowed", False):
            return PolicyDecision(
                decision=PolicyDecisionType.BLOCK,
                risk=RiskTier.CRITICAL,
                reasons=("workspace command is not in the curated allowlist",),
                trust_zone=trust_zone,
            )

        if request.action_type == ActionType.SETTINGS_CHANGE:
            risk = _max_risk(risk, RiskTier.HIGH)
            reasons.append("guardrail-affecting settings changes require explicit approval")

        if request.privilege_escalation:
            risk = _max_risk(risk, RiskTier.CRITICAL)
            reasons.append("privilege escalation potential detected")

        if request.unknown_executable:
            risk = _max_risk(risk, RiskTier.HIGH)
            reasons.append("target executable is not allowlisted")

        if assessment is not None:
            if assessment.zone == TrustZone.FORBIDDEN:
                risk = _max_risk(risk, RiskTier.CRITICAL)
            elif assessment.zone == TrustZone.SENSITIVE:
                risk = _max_risk(risk, RiskTier.HIGH if request.read_access else RiskTier.CRITICAL)
            elif assessment.zone == TrustZone.USER_DOCUMENTS:
                risk = _max_risk(risk, RiskTier.MEDIUM if request.read_access else RiskTier.HIGH)
            elif assessment.zone == TrustZone.UNKNOWN and (request.read_access or request.write_access):
                risk = _max_risk(risk, RiskTier.HIGH)
            elif assessment.zone == TrustZone.ALLOWED_WORKSPACE:
                if request.write_access:
                    risk = _max_risk(risk, RiskTier.MEDIUM)
                elif request.read_access:
                    risk = _max_risk(risk, RiskTier.LOW)

        if request.destructive:
            risk = _max_risk(risk, RiskTier.HIGH)
            reasons.append("destructive potential detected")

        if request.external_network and not request.metadata.get("approved_network", False):
            risk = _max_risk(risk, RiskTier.HIGH)
            reasons.append("external network use is not approved for this action")

        if request.external_handoff:
            if request.data_sensitivity.value == "sensitive":
                risk = _max_risk(risk, RiskTier.HIGH)
                reasons.append("sensitive data cannot be handed off automatically")
            else:
                risk = _max_risk(risk, RiskTier.MEDIUM)
                reasons.append("external model handoff is bounded and audited")

        if request.budget.files_read > self.settings.max_files_read_per_task:
            risk = _max_risk(risk, RiskTier.HIGH)
            reasons.append("requested file reads exceed policy budget")
        if request.budget.files_modified > self.settings.max_files_modified_per_task:
            risk = _max_risk(risk, RiskTier.HIGH)
            reasons.append("requested file modifications exceed policy budget")
        if request.budget.runtime_seconds > self.settings.max_task_runtime_seconds:
            risk = _max_risk(risk, RiskTier.HIGH)
            reasons.append("requested runtime exceeds policy budget")
        if request.budget.subprocess_count > self.settings.max_subprocess_count:
            risk = _max_risk(risk, RiskTier.HIGH)
            reasons.append("requested subprocess count exceeds policy budget")
        if request.budget.context_chars > self.settings.max_context_chars:
            risk = _max_risk(risk, RiskTier.HIGH)
            reasons.append("requested context payload exceeds policy budget")
        if request.budget.memory_items > self.settings.max_memory_items_injected:
            risk = _max_risk(risk, RiskTier.HIGH)
            reasons.append("requested memory payload exceeds policy budget")

        if request.action_type in {
            ActionType.OPEN_APP,
            ActionType.OPEN_URL,
            ActionType.OPEN_EXPLORER,
            ActionType.LIST_FILES,
            ActionType.PREVIEW_FILE,
            ActionType.MEMORY_WRITE,
        } and trust_zone in {TrustZone.ALLOWED_WORKSPACE, TrustZone.UNKNOWN}:
            balanced_auto = True

        if request.action_type == ActionType.RUN_WORKSPACE_COMMAND and trust_zone == TrustZone.ALLOWED_WORKSPACE:
            balanced_auto = True
            risk = _max_risk(risk, RiskTier.MEDIUM)

        if request.action_type == ActionType.CLAUDE_TASK and trust_zone == TrustZone.ALLOWED_WORKSPACE:
            balanced_auto = True
            risk = _max_risk(risk, RiskTier.MEDIUM)

        with self._lock:
            mode = self._mode
            autonomy_paused = self._autonomy_paused
            deny_high_risk = self._deny_high_risk

        if deny_high_risk and risk in {RiskTier.HIGH, RiskTier.CRITICAL}:
            return PolicyDecision(
                decision=PolicyDecisionType.BLOCK,
                risk=risk,
                reasons=tuple(reasons + ["high-risk actions are currently denied by policy"]),
                trust_zone=trust_zone,
                balanced_auto=balanced_auto,
            )

        if autonomy_paused and risk != RiskTier.CRITICAL:
            return PolicyDecision(
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                risk=risk,
                reasons=tuple(reasons + ["autonomy is paused"]),
                trust_zone=trust_zone,
                balanced_auto=balanced_auto,
            )

        if mode == AutonomyMode.HANDS_FREE:
            if risk in {RiskTier.LOW, RiskTier.MEDIUM}:
                decision = PolicyDecisionType.ALLOW
            elif risk == RiskTier.HIGH:
                decision = PolicyDecisionType.REQUIRE_APPROVAL
            else:
                decision = PolicyDecisionType.BLOCK
        elif mode == AutonomyMode.STRICT:
            if risk == RiskTier.LOW:
                decision = PolicyDecisionType.ALLOW
            elif risk == RiskTier.CRITICAL:
                decision = PolicyDecisionType.BLOCK
            else:
                decision = PolicyDecisionType.REQUIRE_APPROVAL
        else:
            if risk == RiskTier.LOW:
                decision = PolicyDecisionType.ALLOW
            elif risk == RiskTier.MEDIUM and balanced_auto:
                decision = PolicyDecisionType.ALLOW
            elif risk == RiskTier.CRITICAL:
                decision = PolicyDecisionType.BLOCK
            else:
                decision = PolicyDecisionType.REQUIRE_APPROVAL

        return PolicyDecision(
            decision=decision,
            risk=risk,
            reasons=tuple(reasons or ("policy evaluation completed",)),
            trust_zone=trust_zone,
            balanced_auto=balanced_auto,
        )
