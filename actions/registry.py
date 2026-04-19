from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from actions.system_actions import ActionResult, SystemActions
from config.settings import AppSettings
from security.handoff import HandoffManager
from security.models import ActionRequest, ActionSource, ActionType, ContextSelection, DataSensitivity
from security.workspace import WorkspaceJail


@dataclass(slots=True)
class ActionRegistry:
    settings: AppSettings
    actions: SystemActions
    jail: WorkspaceJail
    handoff_manager: HandoffManager

    def open_app_request(self, alias: str, source: ActionSource) -> ActionRequest:
        canonical = self.actions.canonicalize_launch_target(alias) or alias.strip().lower()
        return ActionRequest(
            action_type=ActionType.OPEN_APP,
            source=source,
            description=f"Open {canonical}.",
            target=canonical,
            unknown_executable=canonical not in self.actions.allowlisted_app_targets(),
        )

    def open_url_request(self, target: str, browser: str, source: ActionSource, *, approved_network: bool | None = None) -> ActionRequest:
        resolved = self.actions.resolve_site_target(target) or target
        metadata = {
            "browser": browser,
            "approved_network": self.actions.is_approved_url(resolved) if approved_network is None else approved_network,
        }
        return ActionRequest(
            action_type=ActionType.OPEN_URL,
            source=source,
            description=f"Open {resolved} in {browser}.",
            target=resolved,
            external_network=True,
            metadata=metadata,
        )

    def open_explorer_request(self, target_path: Path, source: ActionSource) -> ActionRequest:
        return ActionRequest(
            action_type=ActionType.OPEN_EXPLORER,
            source=source,
            description=f"Open File Explorer at {target_path}.",
            target=str(target_path),
            target_path=target_path,
            read_access=True,
        )

    def list_files_request(self, target_path: Path, source: ActionSource) -> ActionRequest:
        return ActionRequest(
            action_type=ActionType.LIST_FILES,
            source=source,
            description=f"List files in {target_path}.",
            target=str(target_path),
            target_path=target_path,
            read_access=True,
        )

    def preview_file_request(self, target_path: Path, source: ActionSource) -> ActionRequest:
        return ActionRequest(
            action_type=ActionType.PREVIEW_FILE,
            source=source,
            description=f"Preview {target_path.name}.",
            target=str(target_path),
            target_path=target_path,
            read_access=True,
            budget=self.actions.preview_budget(),
        )

    def workspace_command_request(self, command_id: str, source: ActionSource) -> ActionRequest:
        workspace = self.jail.default_workspace()
        command_allowed = command_id in self.settings.allowed_workspace_commands
        return ActionRequest(
            action_type=ActionType.RUN_WORKSPACE_COMMAND,
            source=source,
            description=f"Run workspace command {command_id}.",
            target=command_id,
            workspace=workspace,
            read_access=True,
            write_access=command_id.endswith("format"),
            budget=self.actions.workspace_command_budget(),
            metadata={"command_id": command_id, "command_allowed": command_allowed},
        )

    def claude_task_request(self, task: str, source: ActionSource, context: ContextSelection) -> ActionRequest:
        workspace = self.jail.default_workspace()
        return ActionRequest(
            action_type=ActionType.CLAUDE_TASK,
            source=source,
            description=f"Run Claude Code task: {task}",
            target=task,
            workspace=workspace,
            allowed_paths=(workspace,) if workspace is not None else (),
            read_access=True,
            write_access=True,
            external_network=True,
            external_handoff=True,
            data_sensitivity=DataSensitivity.GENERAL,
            context=context,
            budget=self.actions.claude_task_budget(),
            metadata={"approved_network": True},
        )

    def advanced_shell_request(self, command: str, source: ActionSource) -> ActionRequest:
        workspace = self.jail.default_workspace()
        return ActionRequest(
            action_type=ActionType.ADVANCED_SHELL,
            source=source,
            description=f"Run advanced shell command: {command}",
            target=command,
            workspace=workspace,
            read_access=True,
            write_access=True,
            external_network=True,
            budget=self.actions.advanced_shell_budget(),
        )

    async def execute(self, request: ActionRequest, desktop_context) -> ActionResult:
        if request.action_type == ActionType.OPEN_APP:
            return await self.actions.launch_named_app(request.target)
        if request.action_type == ActionType.OPEN_URL:
            browser = str(request.metadata.get("browser", "chrome"))
            return await self.actions.open_in_browser(request.target, browser)
        if request.action_type == ActionType.OPEN_EXPLORER:
            return await self.actions.open_explorer(request.target_path or Path(request.target))
        if request.action_type == ActionType.OPEN_PATH:
            return await self.actions.open_target(request.target)
        if request.action_type == ActionType.LIST_FILES:
            return await self.actions.list_workspace_files(request.target_path or Path(request.target))
        if request.action_type == ActionType.PREVIEW_FILE:
            return await self.actions.preview_file(request.target_path or Path(request.target))
        if request.action_type == ActionType.RUN_WORKSPACE_COMMAND:
            return await self.actions.run_workspace_command(str(request.metadata.get("command_id", "")))
        if request.action_type == ActionType.LAUNCH_CLAUDE_INTERACTIVE:
            return await self.actions.launch_claude_interactive()
        if request.action_type == ActionType.CLAUDE_TASK:
            envelope = self.handoff_manager.build_claude_envelope(
                request,
                request.target,
                request.context,
                desktop_context,
            )
            validation_error = self.handoff_manager.validate_claude_envelope(request, envelope)
            if validation_error is not None:
                return ActionResult(False, f"Claude Code handoff blocked: {validation_error}")
            return await self.actions.execute_secured_claude_handoff(envelope, timeout=self.settings.max_task_runtime_seconds)
        if request.action_type == ActionType.ADVANCED_SHELL:
            return await self.actions.run_advanced_shell(request.target, timeout=self.settings.max_task_runtime_seconds)
        if request.action_type == ActionType.MEMORY_WRITE:
            return ActionResult(True, "Stored in local memory.")
        return ActionResult(False, f"No action handler is registered for {request.action_type.value}.")
