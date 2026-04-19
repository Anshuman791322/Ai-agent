from __future__ import annotations

import asyncio
from pathlib import Path

from actions.system_actions import SystemActions
from security.approvals import ApprovalManager
from security.models import (
    ActionRequest,
    ActionSource,
    ActionType,
    PolicyDecisionType,
    RiskTier,
    TrustZone,
)
from security.policy import PolicyEngine
from security.workspace import WorkspaceJail
from actions.registry import ActionRegistry
from security.handoff import HandoffManager
from security.context_manager import ContextManager
from memory.store import MemoryStore


def test_workspace_jail_normalizes_paths_and_keeps_them_in_scope(security_workspace_factory):
    settings, workspace, _, sensitive, forbidden = security_workspace_factory()
    jail = WorkspaceJail(settings)

    nested = workspace / "src"
    nested.mkdir()
    notes = workspace / "notes.txt"
    notes.write_text("ok", encoding="utf-8")

    resolved = jail.resolve_path(Path("src") / ".." / "notes.txt", base=workspace)
    assert resolved == notes

    allowed = jail.classify(Path("src") / ".." / "notes.txt", base=workspace)
    assert allowed.zone == TrustZone.ALLOWED_WORKSPACE
    assert allowed.workspace_root == workspace

    escaped = jail.classify(r"..\outside.txt", base=workspace)
    assert escaped.zone == TrustZone.UNKNOWN
    assert escaped.workspace_root is None
    assert escaped.resolved_path == workspace.parent / "outside.txt"

    assert jail.classify(sensitive / "creds.txt").zone == TrustZone.SENSITIVE
    assert jail.classify(forbidden / "win.ini").zone == TrustZone.FORBIDDEN


def test_policy_escalates_sensitive_reads_to_approval(security_workspace_factory):
    settings, _, _, sensitive, _ = security_workspace_factory()
    jail = WorkspaceJail(settings)
    policy = PolicyEngine(settings, jail)
    approvals = ApprovalManager()

    secret_file = sensitive / "plan.txt"
    secret_file.write_text("alpha", encoding="utf-8")

    request = ActionRequest(
        action_type=ActionType.PREVIEW_FILE,
        source=ActionSource.TYPED,
        description="Preview secret plan",
        target_path=secret_file,
        read_access=True,
    )

    decision = policy.evaluate(request)
    assert decision.trust_zone == TrustZone.SENSITIVE
    assert decision.risk == RiskTier.HIGH
    assert decision.decision == PolicyDecisionType.REQUIRE_APPROVAL

    pending = approvals.submit(request, decision, lambda: asyncio.sleep(0, result="approved"))
    assert pending.summary == "Preview secret plan"
    assert approvals.snapshot()["count"] == 1
    assert approvals.snapshot()["first"]["approval_id"] == pending.approval_id
    assert approvals.approve() is pending
    assert approvals.snapshot()["count"] == 0


def test_policy_blocks_sensitive_and_forbidden_paths_when_high_risk_is_denied(security_workspace_factory):
    settings, _, _, sensitive, forbidden = security_workspace_factory()
    jail = WorkspaceJail(settings)
    policy = PolicyEngine(settings, jail)
    policy.set_deny_high_risk(True)

    sensitive_file = sensitive / "tokens.txt"
    sensitive_file.write_text("alpha", encoding="utf-8")
    sensitive_decision = policy.evaluate(
        ActionRequest(
            action_type=ActionType.PREVIEW_FILE,
            source=ActionSource.TYPED,
            description="Preview sensitive file",
            target_path=sensitive_file,
            read_access=True,
        )
    )
    assert sensitive_decision.decision == PolicyDecisionType.BLOCK
    assert sensitive_decision.risk == RiskTier.HIGH
    assert "high-risk actions are currently denied by policy" in sensitive_decision.reasons

    forbidden_file = forbidden / "boot.ini"
    forbidden_file.write_text("alpha", encoding="utf-8")
    forbidden_decision = policy.evaluate(
        ActionRequest(
            action_type=ActionType.PREVIEW_FILE,
            source=ActionSource.TYPED,
            description="Preview forbidden file",
            target_path=forbidden_file,
            read_access=True,
        )
    )
    assert forbidden_decision.decision == PolicyDecisionType.BLOCK
    assert forbidden_decision.risk == RiskTier.CRITICAL
    assert "path is inside a forbidden system zone" in forbidden_decision.reasons


def test_advanced_shell_execution_is_blocked_in_normal_mode(security_workspace_factory):
    settings, workspace, _, _, _ = security_workspace_factory()
    actions = SystemActions(settings)
    jail = WorkspaceJail(settings)
    policy = PolicyEngine(settings, jail)
    registry = ActionRegistry(settings, actions, jail, HandoffManager(settings, jail, ContextManager(settings, MemoryStore(settings.app_dir / "memory.sqlite"))))

    request = registry.advanced_shell_request("Get-ChildItem", ActionSource.TYPED)
    decision = policy.evaluate(request)

    assert decision.decision == PolicyDecisionType.BLOCK
    assert decision.risk == RiskTier.CRITICAL
    assert decision.reasons == ("advanced shell execution is not available in this build",)
    assert request.workspace == workspace
    result = asyncio.run(actions.run_advanced_shell("Get-ChildItem"))
    assert not result.success
    assert result.message == "Advanced shell access is not available in this build."


def test_uncurated_workspace_commands_are_blocked_by_policy(security_workspace_factory):
    settings, *_ = security_workspace_factory()
    settings.allowed_workspace_commands = ["pytest"]
    jail = WorkspaceJail(settings)
    policy = PolicyEngine(settings, jail)
    memory = MemoryStore(settings.app_dir / "memory.sqlite")
    registry = ActionRegistry(settings, SystemActions(settings), jail, HandoffManager(settings, jail, ContextManager(settings, memory)))

    request = registry.workspace_command_request("ruff-format", ActionSource.TYPED)
    decision = policy.evaluate(request)

    assert decision.decision == PolicyDecisionType.BLOCK
    assert decision.risk == RiskTier.CRITICAL
    assert decision.reasons == ("workspace command is not in the curated allowlist",)
