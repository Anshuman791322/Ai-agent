from __future__ import annotations

from pathlib import Path

from config.settings import AppSettings
from security.models import PathAssessment, TrustZone


class WorkspaceJail:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.allowed_workspaces = self._resolve_roots(settings.allowed_workspace_roots)
        self.documents_roots = self._resolve_roots(settings.user_documents_roots)
        self.sensitive_roots = self._resolve_roots(settings.sensitive_roots)
        self.forbidden_roots = self._resolve_roots(settings.forbidden_roots)

    def resolve_path(self, raw_path: str | Path, base: Path | None = None) -> Path:
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            anchor = base or self.default_workspace() or Path.home()
            candidate = anchor / candidate
        return candidate.resolve(strict=False)

    def classify(self, raw_path: str | Path, base: Path | None = None) -> PathAssessment:
        resolved = self.resolve_path(raw_path, base=base)
        workspace_root = self.workspace_for_path(resolved)
        zone = TrustZone.UNKNOWN
        reason = "outside trusted roots"

        if self._match_root(resolved, self.forbidden_roots) is not None:
            zone = TrustZone.FORBIDDEN
            reason = "path is inside a forbidden system zone"
        elif self._match_root(resolved, self.sensitive_roots) is not None:
            zone = TrustZone.SENSITIVE
            reason = "path is inside a sensitive local zone"
        elif workspace_root is not None:
            zone = TrustZone.ALLOWED_WORKSPACE
            reason = f"path is inside allowlisted workspace {workspace_root}"
        elif self._match_root(resolved, self.documents_roots) is not None:
            zone = TrustZone.USER_DOCUMENTS
            reason = "path is inside the user documents zone"

        return PathAssessment(
            raw_target=str(raw_path),
            resolved_path=resolved,
            zone=zone,
            workspace_root=workspace_root,
            exists=resolved.exists(),
            reason=reason,
        )

    def workspace_for_path(self, path: Path) -> Path | None:
        for root in self.allowed_workspaces:
            if self._is_relative_to(path, root):
                return root
        return None

    def default_workspace(self) -> Path | None:
        return self.allowed_workspaces[0] if self.allowed_workspaces else None

    def is_allowed_workspace(self, path: Path) -> bool:
        return self.workspace_for_path(path) is not None

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _match_root(self, path: Path, roots: list[Path]) -> Path | None:
        for root in roots:
            if self._is_relative_to(path, root):
                return root
        return None

    @staticmethod
    def _resolve_roots(values: list[str]) -> list[Path]:
        roots: list[Path] = []
        for value in values:
            candidate = Path(value).expanduser()
            try:
                resolved = candidate.resolve(strict=False)
            except OSError:
                continue
            if resolved not in roots:
                roots.append(resolved)
        return roots

