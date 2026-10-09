"""Local sync checks matching the original shared-package workflow."""
from __future__ import annotations
import os
import platform
import subprocess
from pathlib import Path
from PySide6.QtWidgets import QMessageBox

class SharedFolderActions:
    def _get_occs_shared_workspace_dir(self):
        return str(self.comms.settings.shared_dir)

    @staticmethod
    def _path_is_within(path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except (OSError, ValueError):
            return False

    def _onedrive_roots(self) -> list[Path]:
        """Return known local OneDrive roots without assuming a specific tenant name."""
        roots: list[Path] = []
        system_name = platform.system()
        if system_name == "Windows":
            for variable in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
                value = os.environ.get(variable, "").strip()
                if value:
                    roots.append(Path(value))
            user_profile = os.environ.get("USERPROFILE", "").strip()
            if user_profile:
                roots.extend(Path(user_profile).glob("OneDrive*"))
        elif system_name == "Darwin":
            roots.extend((Path.home() / "Library" / "CloudStorage").glob("OneDrive*"))
            roots.append(Path.home() / "OneDrive")
        return [root for root in roots if root.exists()]

    @staticmethod
    def _onedrive_process_running() -> bool | None:
        """Best-effort local process check; this does not prove cloud sync succeeded."""
        system_name = platform.system()
        try:
            if system_name == "Windows":
                result = subprocess.run(
                    ["tasklist", "/FI", "IMAGENAME eq OneDrive.exe", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                return "onedrive.exe" in result.stdout.lower()
            if system_name == "Darwin":
                result = subprocess.run(
                    ["pgrep", "-x", "OneDrive"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return None
        return None

    def _shared_folder_sync_state(self) -> dict[str, object]:
        workspace = Path(self._get_occs_shared_workspace_dir())
        one_drive_root = next(
            (root for root in self._onedrive_roots() if self._path_is_within(workspace, root)),
            None,
        )
        return {
            "workspace": workspace,
            "one_drive_root": one_drive_root,
            "onedrive_running": self._onedrive_process_running() if one_drive_root else None,
        }

    def require_shared_sync(self, action):
        state = self._shared_folder_sync_state()
        if state['one_drive_root'] and state['onedrive_running'] is True:
            return True
        if state['one_drive_root'] and state['onedrive_running'] is False:
            QMessageBox.critical(self, 'Shared Folder Sync', f'OneDrive is not running. Start OneDrive and wait for it to become healthy before you {action}.')
            return False
        return QMessageBox.question(self, 'Shared Folder Sync Not Confirmed',
            f"ATool cannot confirm that {state['workspace']} is syncing through OneDrive.\n\n{action.capitalize()} may not be visible to other users. Continue anyway?") == QMessageBox.StandardButton.Yes

    def check_shared_sync(self):
        state = self._shared_folder_sync_state()
        if state['one_drive_root'] and state['onedrive_running'] is True:
            QMessageBox.information(self, 'Shared Folder Sync', 'OneDrive appears to be running and this folder is inside its local sync folder. This local check cannot confirm that a specific lock has reached another user.')
        else:
            QMessageBox.warning(self, 'Shared Folder Sync', f"Sync is not confirmed for {state['workspace']}. Check the folder location and OneDrive before changing shared locks.")
