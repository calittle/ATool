import hashlib
import getpass
import json
import os
import platform
import re
import copy
import shutil
import socket
import subprocess
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from xml.etree import ElementTree


class AToolApp:
    APP_NAME = "Assembly Template Tool (ATool)"
    CONTACT_EMAIL = "andy.little@oracle.com"
    DEFAULT_WIDTH = 1000
    DEFAULT_HEIGHT = 640
    MACOS_PANEL_BACKGROUND = "#f0f0f0"
    MACOS_CONTENT_BACKGROUND = "#ffffff"
    MACOS_TEXT_FOREGROUND = "#1f1f1f"
    MACOS_SELECTION_BACKGROUND = "#0a84ff"
    OCCS_SPECIFIC_VERSION_TIMEOUT_MS = 60000
    OCCS_LATEST_VERSION_TIMEOUT_MS = 120000
    OCCS_CONVERT_XML_TIMEOUT_MS = 180000
    OCCS_PREVIEW_RENDER_TYPES = ("PDF", "HTML", "TEXT", "CSV", "JSON", "METADATA")
    OCCS_PREVIEW_TIMEOUT_SECONDS = {
        "PDF": 60,
        "HTML": 30,
        "TEXT": 20,
        "CSV": 20,
        "JSON": 20,
        "METADATA": 20,
    }
    OCCS_PREVIEW_MAX_TIMEOUT_SECONDS = 180
    OCCS_LOGIN_TIMEOUT_SECONDS = 120
    OCCS_LOCAL_CLEANUP_DEFAULT_DAYS = 14
    DEFAULT_SETTINGS = {
        "document_display": {
            "collapse": False,
        },
        "diagnostics": {
            "debug_logging": False,
        },
        "occs": {
            "cli_path": "",
            "work_dir": "",
            "session_alias": "",
            "last_config_id": "",
            "shared_workspace_dir": "",
            "user_name": "",
            "package_mru": [],
            "preview_open_programs": {
                "PDF": "",
                "HTML": "",
                "TEXT": "",
                "CSV": "",
                "JSON": "",
                "METADATA": "",
            },
        },
    }

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._geometry_write_job: str | None = None
        self._status_note_job: str | None = None
        self._field_node_details: dict[str, dict[str, object]] = {}
        self._document_node_details: dict[str, dict[str, object]] = {}
        self._layout_node_details: dict[str, dict[str, object]] = {}
        self._triggered_document_names: set[str] = set()
        self.documents_panel_width = self._load_saved_documents_panel_width()
        self.layouts_panel_width = self._load_saved_layouts_panel_width()
        self.document_condition_collapsed = self._load_document_details_section_collapsed("condition")
        self.document_match_details_collapsed = self._load_document_details_section_collapsed("match_details")
        self.fields_window: tk.Toplevel | None = None
        self._fields_window_geometry_job: str | None = None
        self.condition_library_window: tk.Toplevel | None = None
        self.clause_trigger_update_window: tk.Toplevel | None = None
        self.condition_usage_window: tk.Toplevel | None = None
        self._condition_library_window_geometry_job: str | None = None
        self._condition_library_entries: list[dict[str, str]] = []
        self._active_condition_library_index: int | None = None
        self._condition_library_node_to_index: dict[str, int] = {}
        self._clause_trigger_update_proposals: list[dict[str, object]] = []
        self._clause_trigger_update_index = 0
        self._condition_usage_all_results: list[dict[str, object]] = []
        self._condition_usage_results: list[dict[str, object]] = []
        self._condition_usage_index = 0
        self._condition_usage_summary_text = ""
        self._condition_usage_type_filter = ""
        self._condition_usage_sort_column = ""
        self._condition_usage_sort_desc = False
        self._document_controls_layout_job: str | None = None
        self._document_controls_layout_signature: tuple[object, ...] | None = None
        self._tooltip_window: tk.Toplevel | None = None
        self.clause_manager_list_width = self._load_saved_clause_manager_list_width()
        self.compose_entry_widget: tk.Text | None = None
        self.compose_autocomplete_popup: tk.Toplevel | None = None
        self.compose_autocomplete_listbox: tk.Listbox | None = None
        self.user_settings = self._load_user_settings()
        self.document_view_mode = self._load_document_view_mode()
        self.current_file_path: str | None = None
        self.current_source_file_path: str | None = None
        self.current_package_name: str = "(none)"
        self.current_occs_bundle_dir: str | None = None
        self.current_occs_manifest: dict[str, object] | None = None
        self.current_occs_shared_package_dir: Path | None = None
        self.current_occs_shared_mode = "local"
        self._occs_operation_in_progress = False
        self.current_payload: dict | None = None
        self.current_data_payload: object | None = None
        self.current_data_file_path: str | None = None
        self._mapping_in_progress = False
        self._mapping_dialog_in_progress = False
        self._show_triggered_documents_only = False
        self._mapping_job_id = 0
        self.is_dirty = False
        self._updating_field_form = False
        self._active_field_node_id: str | None = None
        self._updating_document_form = False
        self._active_document_node_id: str | None = None
        self._updating_layout_form = False
        self._active_layout_node_id: str | None = None
        self.root.title("ATool")
        self._restore_window_geometry()

        self.status_text = tk.StringVar(value="File: (none) | Package: (none)")
        self.data_status_text = tk.StringVar(value="Data: (none)")
        self.mapping_status_text = tk.StringVar(value="Mapping: Idle")
        self.document_count_text = tk.StringVar(value="Documents: 0")
        self.field_count_text = tk.StringVar(value="Fields: 0")
        self.condition_compose_status_var = tk.StringVar(value="")
        self.condition_compose_target_var = tk.StringVar(value="Target: (none selected)")
        self.condition_clause_filter_var = tk.StringVar(value="")
        self.document_name_text = tk.StringVar(value="(no document selected)")
        self.document_triggered_text = tk.StringVar(value="-")
        self.document_condition_text = tk.StringVar(value="")
        self.document_descr_edit_text = tk.StringVar(value="")
        self.document_updated_text = tk.StringVar(value="-")
        self.edit_document_name_var = tk.StringVar(value="")
        self.layout_item_kind_text = tk.StringVar(value="-")
        self.layout_name_edit_var = tk.StringVar(value="")
        self.layout_condition_edit_var = tk.StringVar(value="")
        self.layout_iteration_edit_var = tk.StringVar(value="")
        self.layout_path_edit_var = tk.StringVar(value="")
        self.layout_type_edit_var = tk.StringVar(value="")
        self.layout_mandatory_var = tk.BooleanVar(value=False)
        self.layout_summary_text = tk.StringVar(value="-")
        self.layout_mapped_text = tk.StringVar(value="-")
        self.documents_filter_var = tk.StringVar(value="")
        self.field_name_text = tk.StringVar(value="(no field selected)")
        self.field_mandatory_text = tk.StringVar(value="-")
        self.field_path_text = tk.StringVar(value="-")
        self.field_true_path_text = tk.StringVar(value="-")
        self.field_hierarchy_text = tk.StringVar(value="-")
        self.field_updated_text = tk.StringVar(value="-")
        self.field_descr_text = tk.StringVar(value="")
        self.field_mapped_value_text = tk.StringVar(value="-")
        self.edit_field_name_var = tk.StringVar(value="")
        self.edit_field_mandatory_var = tk.BooleanVar(value=False)
        self.edit_field_path_var = tk.StringVar(value="")
        self.fields_filter_var = tk.StringVar(value="")
        self.field_view_mode = "name"
        self._loaded_documents: list[dict[str, object]] = []
        self._loaded_fields: list[dict[str, object]] = []

        self._configure_platform_appearance()
        self._create_menu()
        self._create_main_layout()
        self.documents_filter_var.trace_add("write", self._on_documents_filter_changed)
        self.fields_filter_var.trace_add("write", self._on_fields_filter_changed)
        self.condition_clause_filter_var.trace_add("write", self._on_condition_library_filter_changed)
        self._bind_shortcuts()
        self.root.bind("<Configure>", self._on_window_configure)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(0, self._open_startup_windows)

    def _open_startup_windows(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self._show_fields_window()
        self._show_condition_library_window()
        self.root.after(200, self._focus_main_window)

    def _focus_main_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _configure_platform_appearance(self) -> None:
        if not self._is_macos():
            return

        self._style_window_background(self.root)
        style = ttk.Style(self.root)
        panel_background = self.MACOS_PANEL_BACKGROUND
        content_background = self.MACOS_CONTENT_BACKGROUND
        foreground = self.MACOS_TEXT_FOREGROUND

        self.root.option_add("*Text.background", content_background)
        self.root.option_add("*Text.foreground", foreground)
        self.root.option_add("*Text.insertBackground", foreground)
        self.root.option_add("*Text.selectBackground", self.MACOS_SELECTION_BACKGROUND)
        self.root.option_add("*Text.selectForeground", content_background)
        self.root.option_add("*Text.highlightBackground", panel_background)
        self.root.option_add("*Listbox.background", content_background)
        self.root.option_add("*Listbox.foreground", foreground)
        self.root.option_add("*Listbox.selectBackground", self.MACOS_SELECTION_BACKGROUND)
        self.root.option_add("*Listbox.selectForeground", content_background)
        self.root.option_add("*Listbox.highlightBackground", panel_background)

        style.configure("TFrame", background=panel_background)
        style.configure("TLabelframe", background=panel_background)
        style.configure("TLabelframe.Label", background=panel_background)
        style.configure("TLabel", background=panel_background)
        style.configure("TCheckbutton", background=panel_background)
        style.configure("TRadiobutton", background=panel_background)
        style.configure("TPanedwindow", background=panel_background)
        style.configure("TEntry", fieldbackground=content_background)
        style.configure("TCombobox", fieldbackground=content_background)
        style.configure("Treeview", background=content_background, fieldbackground=content_background, foreground=foreground)
        style.map(
            "Treeview",
            background=[("selected", self.MACOS_SELECTION_BACKGROUND)],
            foreground=[("selected", content_background)],
        )

    def _style_window_background(self, window: tk.Misc) -> None:
        if not self._is_macos():
            return
        try:
            window.configure(background=self.MACOS_PANEL_BACKGROUND)
        except tk.TclError:
            pass

    def _create_toplevel(self, parent: tk.Misc | None = None) -> tk.Toplevel:
        window = tk.Toplevel(parent if parent is not None else self.root)
        self._style_window_background(window)
        return window

    def _create_menu(self) -> None:
        self._attach_app_menu(self.root)

    def _attach_app_menu(self, window: tk.Misc) -> None:
        window.config(menu=self._build_app_menu(window))

    def _build_app_menu(self, window: tk.Misc) -> tk.Menu:
        menu_bar = tk.Menu(window)

        file_menu = tk.Menu(menu_bar, tearoff=0)
        save_accelerator = "Cmd+S" if self._is_macos() else "Alt+S"
        file_menu.add_command(
            label="Save",
            accelerator=save_accelerator,
            command=self.save_assembly_template,
        )
        file_menu.add_separator()
        file_menu.add_command(label="About ATool", command=self._show_about_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)

        data_menu = tk.Menu(menu_bar, tearoff=0)
        map_accelerator = "Cmd+M" if self._is_macos() else "Alt+M"
        convert_and_map_accelerator = "Shift+Cmd+M" if self._is_macos() else "Shift+Ctrl+M"
        data_menu.add_command(
            label="Map...",
            accelerator=map_accelerator,
            command=self.map_data_file,
        )
        data_menu.add_command(
            label="Convert...",
            command=self.convert_xml_data_file,
        )
        data_menu.add_command(
            label="Convert and Map...",
            accelerator=convert_and_map_accelerator,
            command=self.convert_and_map_data_file,
        )

        settings_menu = tk.Menu(menu_bar, tearoff=0)
        settings_menu.add_command(label="User Settings...", command=self._open_user_settings_dialog)

        package_menu = tk.Menu(menu_bar, tearoff=0)
        open_accelerator = "Cmd+O" if self._is_macos() else "Alt+O"
        preview_accelerator = "Cmd+P" if self._is_macos() else "Ctrl+P"
        update_shared_accelerator = "Cmd+U" if self._is_macos() else "Ctrl+U"
        publish_accelerator = "Shift+Cmd+U" if self._is_macos() else "Shift+Ctrl+U"
        package_menu.add_command(
            label="Open Shared Package...",
            accelerator=open_accelerator,
            command=self.open_occs_package,
        )
        package_menu.add_command(label="Open Local Package...", command=self.open_occs_package_bundle)
        package_menu.add_command(label="Clean Local Packages...", command=self.clean_local_occs_packages)
        package_menu.add_command(label="Open Raw AT...", command=self.open_assembly_template)
        package_menu.add_separator()
        package_menu.add_command(
            label="Get Packages from Comms...",
            command=self.list_occs_packages_from_comms,
        )
        package_menu.add_separator()
        package_menu.add_command(
            label="Update Shared Package",
            accelerator=update_shared_accelerator,
            command=self.update_shared_occs_package,
        )
        package_menu.add_command(
            label="Publish Package to Comms...",
            accelerator=publish_accelerator,
            command=self.publish_occs_package_to_comms,
        )
        package_menu.add_command(label="Release Shared Package Lock", command=self.release_shared_occs_lock)
        package_menu.add_separator()
        package_menu.add_command(
            label="Preview...",
            accelerator=preview_accelerator,
            command=self.preview_occs_package,
        )

        window_menu = tk.Menu(menu_bar, tearoff=0)
        window_menu.add_command(label="Show Field Manager", command=self._show_fields_window)
        window_menu.add_command(label="Show Clause Manager", command=self._show_condition_library_window)

        menu_bar.add_cascade(label="File", menu=file_menu)
        menu_bar.add_cascade(label="Package", menu=package_menu)
        menu_bar.add_cascade(label="Data", menu=data_menu)
        menu_bar.add_cascade(label="Settings", menu=settings_menu)
        menu_bar.add_cascade(label="Window", menu=window_menu)
        return menu_bar

    def _show_about_dialog(self) -> None:
        build_info = self._get_app_build_info()
        build_label = build_info.get("build_label", "local")
        source_label = build_info.get("source", "local")
        built_at = build_info.get("built_at", "")
        artifact = build_info.get("artifact", "")

        lines = [
            self.APP_NAME,
            f"Build: {build_label}",
        ]
        if source_label:
            lines.append(f"Source: {source_label}")
        if built_at:
            lines.append(f"Built: {built_at}")
        if artifact:
            lines.append(f"Artifact: {artifact}")
        lines.extend(
            [
                "",
                f"Contact: {self.CONTACT_EMAIL}",
            ]
        )
        messagebox.showinfo("About ATool", "\n".join(lines), parent=self.root)

    @classmethod
    def _get_app_build_info(cls) -> dict[str, str]:
        build_info = cls._read_packaged_build_info()
        if not build_info:
            build_info = {
                "source": "local worktree",
                "commit": cls._local_git_value("rev-parse", "--short", "HEAD", default="local"),
            }
            if cls._local_git_value("status", "--short", default=""):
                build_info["dirty"] = "true"

        commit = build_info.get("commit", "").strip()
        short_commit = commit[:7] if commit and commit != "local" else commit or "local"
        if build_info.get("dirty") == "true" and short_commit != "local":
            short_commit = f"{short_commit}-dirty"
        build_info["build_label"] = short_commit or "local"
        return build_info

    @staticmethod
    def _read_packaged_build_info() -> dict[str, str]:
        build_info_path = Path(__file__).resolve().with_name("BUILD_INFO.txt")
        if not build_info_path.exists():
            return {}

        values: dict[str, str] = {}
        try:
            for line in build_info_path.read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition("=")
                if separator and key:
                    values[key.strip()] = value.strip()
        except OSError:
            return {}
        return values

    @staticmethod
    def _local_git_value(*args: str, default: str = "") -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(Path(__file__).resolve().parent), *args],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return default
        if result.returncode != 0:
            return default
        return result.stdout.strip() or default

    def _create_main_layout(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        title_row = ttk.Frame(frame)
        title_row.pack(fill=tk.X)
        title_row.columnconfigure(0, weight=1)

        title = ttk.Label(
            title_row,
            text="Assembly Template Tool (ATool)",
            font=("TkDefaultFont", 16, "bold"),
        )
        title.grid(row=0, column=0, sticky="w")

        content_frame = ttk.Frame(frame)
        content_frame.pack(fill=tk.BOTH, expand=True, pady=(16, 0))
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=1)

        self.docs_layouts_pane = ttk.Panedwindow(content_frame, orient=tk.HORIZONTAL)
        self.docs_layouts_pane.grid(row=0, column=0, sticky="nsew")

        self.left_column_frame = ttk.Frame(self.docs_layouts_pane)
        self.left_column_frame.columnconfigure(0, weight=1)
        self.left_column_frame.rowconfigure(0, weight=1)

        self.left_vertical_pane = ttk.Panedwindow(self.left_column_frame, orient=tk.VERTICAL)
        self.left_vertical_pane.grid(row=0, column=0, sticky="nsew")

        self.documents_panel, self.documents_tree = self._create_documents_panel(self.left_vertical_pane)
        self.documents_tree.bind("<<TreeviewSelect>>", self._on_document_tree_select)
        self.document_details_panel = self._create_document_details_panel(self.left_vertical_pane)
        self.left_vertical_pane.add(self.documents_panel, weight=3)
        self.left_vertical_pane.add(self.document_details_panel, weight=2)

        self.layouts_right_frame = ttk.Frame(self.docs_layouts_pane)
        self.layouts_right_frame.columnconfigure(0, weight=1)
        self.layouts_right_frame.rowconfigure(0, weight=1)
        self.layouts_panel = self._create_layouts_panel(self.layouts_right_frame)
        self.layouts_panel.grid(row=0, column=0, sticky="nsew")

        self.docs_layouts_pane.add(self.left_column_frame, weight=3)
        self.docs_layouts_pane.add(self.layouts_right_frame, weight=2)

        self.root.after(0, self._apply_saved_documents_panel_width)
        self.root.after(0, self._apply_saved_layouts_panel_width)
        self.left_vertical_pane.bind("<ButtonRelease-1>", self._on_main_pane_release)
        self.docs_layouts_pane.bind("<ButtonRelease-1>", self._on_docs_layouts_pane_release)
        self._create_fields_window()

        self._set_empty_documents_tree("No documents loaded")
        self._set_empty_layouts_tree("No layouts loaded")
        self._set_empty_fields_tree("No fields loaded")

        status_bar = ttk.Frame(self.root, relief=tk.SUNKEN, borderwidth=1, padding=(8, 4))
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        status_bar.columnconfigure(0, weight=1)

        status_label = ttk.Label(status_bar, textvariable=self.status_text, anchor=tk.W)
        status_label.grid(row=0, column=0, sticky="ew")

        data_label = ttk.Label(status_bar, textvariable=self.data_status_text, anchor=tk.W)
        data_label.grid(row=0, column=1, sticky="w", padx=(12, 0))

        docs_label = ttk.Label(status_bar, textvariable=self.document_count_text, anchor=tk.CENTER)
        docs_label.grid(row=0, column=2, sticky="e", padx=(12, 0))

        fields_label = ttk.Label(status_bar, textvariable=self.field_count_text, anchor=tk.CENTER)
        fields_label.grid(row=0, column=3, sticky="e", padx=(12, 0))

    def _create_documents_panel(self, parent: ttk.Frame) -> tuple[ttk.Frame, ttk.Treeview]:
        panel = ttk.Frame(parent, padding=(0, 0, 12, 0))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(3, weight=1)

        header = ttk.Frame(panel)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        header.columnconfigure(0, weight=1)

        label = ttk.Label(header, text="Documents", font=("TkDefaultFont", 12, "bold"))
        label.grid(row=0, column=0, sticky="w")

        controls = ttk.Frame(panel)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        controls.bind("<Configure>", self._on_documents_controls_configure)
        self.documents_controls_frame = controls

        self.documents_view_toggle_button = ttk.Button(
            controls,
            text="View",
            command=self._toggle_document_view_mode,
        )
        self._attach_tooltip(self.documents_view_toggle_button, "Toggle document view mode (Flat/Hierarchy).")

        self.clear_mapping_button = ttk.Button(
            controls,
            text="Map",
            command=self._toggle_mapping_file,
        )
        self._attach_tooltip(self.clear_mapping_button, "Map a data file or clear the current map.")

        self.document_mapping_filter_button = ttk.Button(
            controls,
            text="Show Triggered",
            command=self._toggle_triggered_document_filter,
        )
        self._attach_tooltip(
            self.document_mapping_filter_button,
            "Toggle between all mapped documents and triggered documents only.",
        )

        self.add_document_button = ttk.Button(
            controls,
            text="+Document",
            command=self.add_document,
        )
        self._attach_tooltip(self.add_document_button, "Add a document to the assembly template.")

        self.move_document_up_button = ttk.Button(
            controls,
            text="Up",
            command=lambda: self._run_document_move_button_command(
                self.move_document_up_button,
                lambda: self.move_selected_document(-1),
            ),
        )
        self._attach_tooltip(self.move_document_up_button, "Move selected document up (Flat view only).")

        self.move_document_down_button = ttk.Button(
            controls,
            text="Down",
            command=lambda: self._run_document_move_button_command(
                self.move_document_down_button,
                lambda: self.move_selected_document(1),
            ),
        )
        self._attach_tooltip(self.move_document_down_button, "Move selected document down (Flat view only).")

        self.move_document_top_button = ttk.Button(
            controls,
            text="Top",
            command=lambda: self._run_document_move_button_command(
                self.move_document_top_button,
                self.move_selected_document_to_top,
            ),
        )
        self._attach_tooltip(self.move_document_top_button, "Move selected document to the top (Flat view only).")

        self.move_document_bottom_button = ttk.Button(
            controls,
            text="Bottom",
            command=lambda: self._run_document_move_button_command(
                self.move_document_bottom_button,
                self.move_selected_document_to_bottom,
            ),
        )
        self._attach_tooltip(self.move_document_bottom_button, "Move selected document to the bottom (Flat view only).")

        self.auto_move_document_button = ttk.Button(
            controls,
            text="Auto Move",
            command=lambda: self._run_document_move_button_command(
                self.auto_move_document_button,
                self.auto_move_selected_document,
            ),
        )
        self._attach_tooltip(
            self.auto_move_document_button,
            "Move selected document near similarly named documents.",
        )

        self.generate_sample_input_button = ttk.Button(
            controls,
            text="Sample",
            command=self.generate_sample_input_for_selected_document,
        )
        self._attach_tooltip(
            self.generate_sample_input_button,
            "Generate a sample input JSON that satisfies the selected document.",
        )
        self._document_toolbar_buttons = [
            self.documents_view_toggle_button,
            self.clear_mapping_button,
            self.document_mapping_filter_button,
            self.add_document_button,
            self.move_document_top_button,
            self.move_document_up_button,
            self.move_document_down_button,
            self.move_document_bottom_button,
            self.auto_move_document_button,
            self.generate_sample_input_button,
        ]
        self._relayout_documents_controls()

        filter_row = ttk.Frame(panel)
        filter_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        filter_row.columnconfigure(0, weight=1)

        documents_filter = ttk.Entry(filter_row, textvariable=self.documents_filter_var)
        documents_filter.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        documents_filter_clear = ttk.Button(
            filter_row,
            text="Clear",
            command=self._clear_documents_filter,
        )
        documents_filter_clear.grid(row=0, column=1)

        tree = ttk.Treeview(panel, show="tree", selectmode="extended")
        tree.grid(row=3, column=0, sticky="nsew")
        tree.tag_configure("triggered_doc", foreground="blue")
        tree.tag_configure("untriggered_doc", foreground="red")

        scrollbar = ttk.Scrollbar(panel, orient=tk.VERTICAL, command=tree.yview)
        scrollbar.grid(row=3, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)
        self._update_document_view_buttons()
        self._update_mapping_controls()
        self._update_document_context_buttons()
        return panel, tree

    def _create_layouts_panel(self, parent: ttk.Frame) -> ttk.Frame:
        panel = ttk.Frame(parent, padding=(8, 0, 0, 0))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        header = ttk.Frame(panel)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        heading = ttk.Label(header, text="Layouts", font=("TkDefaultFont", 12, "bold"))
        heading.grid(row=0, column=0, sticky="w")

        controls = ttk.Frame(header)
        controls.grid(row=0, column=1, sticky="e")
        self.add_layout_button = ttk.Button(
            controls,
            text="+Layout",
            command=self.add_layout_to_selected_document,
        )
        self.add_layout_button.grid(row=0, column=0, padx=(0, 6))
        self._attach_tooltip(self.add_layout_button, "Add a layout to the selected document.")
        self.add_content_button = ttk.Button(
            controls,
            text="+Content",
            command=self.add_content_to_selected_layout,
        )
        self.add_content_button.grid(row=0, column=1, padx=(0, 6))
        self.move_layout_up_button = ttk.Button(
            controls,
            text="Up",
            command=lambda: self.move_selected_layout(-1),
        )
        self.move_layout_up_button.grid(row=0, column=2, padx=(0, 6))
        self.move_layout_down_button = ttk.Button(
            controls,
            text="Down",
            command=lambda: self.move_selected_layout(1),
        )
        self.move_layout_down_button.grid(row=0, column=3, padx=(0, 6))
        self.add_iteration_button = ttk.Button(
            controls,
            text="+Iteration",
            command=self.add_iteration_to_selected_content,
        )
        self.add_iteration_button.grid(row=0, column=4, padx=(0, 6))
        self.add_iteration_field_button = ttk.Button(
            controls,
            text="+Field",
            command=self.add_field_to_selected_iteration,
        )
        self.add_iteration_field_button.grid(row=0, column=5, padx=(0, 6))
        self.remove_layout_item_button = ttk.Button(
            controls,
            text="Remove",
            command=self.remove_selected_layout_item,
        )
        self.remove_layout_item_button.grid(row=0, column=6)

        self.layouts_vertical_pane = ttk.Panedwindow(panel, orient=tk.VERTICAL)
        self.layouts_vertical_pane.grid(row=1, column=0, sticky="nsew")

        self.layouts_tree_panel = ttk.Frame(self.layouts_vertical_pane)
        self.layouts_tree_panel.columnconfigure(0, weight=1)
        self.layouts_tree_panel.rowconfigure(0, weight=1)
        self.layouts_tree = ttk.Treeview(self.layouts_tree_panel, show="tree")
        self.layouts_tree.grid(row=0, column=0, sticky="nsew")
        self.layouts_tree.bind("<<TreeviewSelect>>", self._on_layout_tree_select)
        self.layouts_tree.bind("<Delete>", self._remove_selected_layout_item_event)
        self.layouts_tree.bind("<BackSpace>", self._remove_selected_layout_item_event)
        self.layouts_tree.tag_configure("layout_triggered", foreground="blue")
        self.layouts_tree.tag_configure("layout_untriggered", foreground="red")
        layouts_scroll = ttk.Scrollbar(self.layouts_tree_panel, orient=tk.VERTICAL, command=self.layouts_tree.yview)
        layouts_scroll.grid(row=0, column=1, sticky="ns")
        self.layouts_tree.configure(yscrollcommand=layouts_scroll.set)

        self.layout_properties_panel = ttk.Frame(self.layouts_vertical_pane, relief=tk.GROOVE, borderwidth=1, padding=10)
        self.layout_properties_panel.columnconfigure(0, weight=1)
        self.layout_properties_panel.bind("<Configure>", self._on_layout_properties_configure)
        self._layout_wrapped_labels: list[ttk.Label] = []

        row = 0
        title = ttk.Label(self.layout_properties_panel, text="Properties", font=("TkDefaultFont", 11, "bold"))
        title.grid(row=row, column=0, sticky="w", pady=(0, 8))
        row += 1

        ttk.Label(self.layout_properties_panel, text="Item Kind:").grid(row=row, column=0, sticky="w")
        row += 1
        kind_value = ttk.Label(self.layout_properties_panel, textvariable=self.layout_item_kind_text, justify=tk.LEFT)
        kind_value.grid(row=row, column=0, sticky="w", pady=(0, 8))
        self._layout_wrapped_labels.append(kind_value)
        row += 1

        self.layout_name_title = ttk.Label(self.layout_properties_panel, text="Name:")
        self.layout_name_title.grid(row=row, column=0, sticky="w")
        row += 1
        self.layout_name_entry = ttk.Entry(self.layout_properties_panel, textvariable=self.layout_name_edit_var)
        self.layout_name_entry.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        self.layout_name_edit_var.trace_add("write", self._on_layout_name_changed)
        row += 1

        condition_row = ttk.Frame(self.layout_properties_panel)
        condition_row.grid(row=row, column=0, sticky="ew")
        condition_row.columnconfigure(0, weight=1)
        self.layout_condition_title = ttk.Label(condition_row, text="Condition:")
        self.layout_condition_title.grid(row=0, column=0, sticky="w")
        self.layout_condition_tool_button = ttk.Button(
            condition_row,
            text="...",
            width=3,
            command=self.open_conditions_tool_from_layout,
        )
        self.layout_condition_tool_button.grid(row=0, column=1, sticky="e")
        row += 1
        self.layout_condition_entry = ttk.Entry(self.layout_properties_panel, textvariable=self.layout_condition_edit_var)
        self.layout_condition_entry.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        self.layout_condition_edit_var.trace_add("write", self._on_layout_condition_changed)
        row += 1

        self.layout_iteration_title = ttk.Label(self.layout_properties_panel, text="Iteration:")
        self.layout_iteration_title.grid(row=row, column=0, sticky="w")
        row += 1
        self.layout_iteration_entry = ttk.Entry(self.layout_properties_panel, textvariable=self.layout_iteration_edit_var)
        self.layout_iteration_entry.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        self.layout_iteration_edit_var.trace_add("write", self._on_layout_iteration_changed)
        row += 1

        self.layout_path_title = ttk.Label(self.layout_properties_panel, text="Path:")
        self.layout_path_title.grid(row=row, column=0, sticky="w")
        row += 1
        self.layout_path_entry = ttk.Entry(self.layout_properties_panel, textvariable=self.layout_path_edit_var)
        self.layout_path_entry.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        self.layout_path_edit_var.trace_add("write", self._on_layout_path_changed)
        row += 1

        self.layout_type_title = ttk.Label(self.layout_properties_panel, text="Type:")
        self.layout_type_title.grid(row=row, column=0, sticky="w")
        row += 1
        self.layout_type_entry = ttk.Combobox(
            self.layout_properties_panel,
            textvariable=self.layout_type_edit_var,
            values=("Iterator", "Spliterator"),
            state="readonly",
        )
        self.layout_type_entry.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        self.layout_type_edit_var.trace_add("write", self._on_layout_type_changed)
        row += 1

        self.layout_mandatory_title = ttk.Label(self.layout_properties_panel, text="Mandatory:")
        self.layout_mandatory_title.grid(row=row, column=0, sticky="w")
        row += 1
        self.layout_mandatory_check = ttk.Checkbutton(self.layout_properties_panel, variable=self.layout_mandatory_var)
        self.layout_mandatory_check.grid(row=row, column=0, sticky="w", pady=(0, 8))
        self.layout_mandatory_var.trace_add("write", self._on_layout_mandatory_changed)
        row += 1

        ttk.Label(self.layout_properties_panel, text="Summary:").grid(row=row, column=0, sticky="w")
        row += 1
        summary_label = ttk.Label(
            self.layout_properties_panel,
            textvariable=self.layout_summary_text,
            wraplength=260,
            justify=tk.LEFT,
        )
        summary_label.grid(row=row, column=0, sticky="w", pady=(0, 8))
        self._layout_wrapped_labels.append(summary_label)
        row += 1

        ttk.Label(self.layout_properties_panel, text="Mapped:").grid(row=row, column=0, sticky="w")
        row += 1
        mapped_label = ttk.Label(
            self.layout_properties_panel,
            textvariable=self.layout_mapped_text,
            wraplength=260,
            justify=tk.LEFT,
        )
        mapped_label.grid(row=row, column=0, sticky="w")
        self._layout_wrapped_labels.append(mapped_label)

        self.layouts_vertical_pane.add(self.layouts_tree_panel, weight=3)
        self.layouts_vertical_pane.add(self.layout_properties_panel, weight=2)
        self._layout_property_widget_pairs = {
            "name": (self.layout_name_title, self.layout_name_entry),
            "condition": (self.layout_condition_title, self.layout_condition_entry),
            "iteration": (self.layout_iteration_title, self.layout_iteration_entry),
            "path": (self.layout_path_title, self.layout_path_entry),
            "type": (self.layout_type_title, self.layout_type_entry),
            "mandatory": (self.layout_mandatory_title, self.layout_mandatory_check),
        }
        self._update_layout_context_buttons()
        self._update_document_context_buttons()
        return panel

    def _create_tree_panel(self, parent: ttk.Frame, heading: str) -> tuple[ttk.Frame, ttk.Treeview]:
        panel = ttk.Frame(parent)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)

        header = ttk.Frame(panel)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)

        label = ttk.Label(header, text=heading, font=("TkDefaultFont", 12, "bold"))
        label.grid(row=0, column=0, sticky="w")

        controls = ttk.Frame(header)
        controls.grid(row=0, column=1, sticky="e")

        collapse_button = ttk.Button(controls, text="Collapse All", command=self._collapse_all_fields)
        collapse_button.grid(row=0, column=0, padx=(0, 6))

        expand_button = ttk.Button(controls, text="Expand All", command=self._expand_all_fields)
        expand_button.grid(row=0, column=1, padx=(0, 6))

        self.view_toggle_button = ttk.Button(
            controls,
            text="View: Path",
            command=self._toggle_field_view,
        )
        self.view_toggle_button.grid(row=0, column=2)

        self.add_field_button = ttk.Button(
            controls,
            text="Add Field",
            command=self.add_field,
        )
        self.add_field_button.grid(row=0, column=3, padx=(6, 0))

        filter_row = ttk.Frame(panel)
        filter_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        filter_row.columnconfigure(0, weight=1)

        fields_filter = ttk.Entry(filter_row, textvariable=self.fields_filter_var)
        fields_filter.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        fields_filter_clear = ttk.Button(
            filter_row,
            text="Clear",
            command=self._clear_fields_filter,
        )
        fields_filter_clear.grid(row=0, column=1)

        tree = ttk.Treeview(panel, show="tree")
        tree.grid(row=2, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(panel, orient=tk.VERTICAL, command=tree.yview)
        scrollbar.grid(row=2, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        tree.tag_configure("mandatory_true", foreground="green4")
        tree.tag_configure("mandatory_false", foreground="blue4")
        return panel, tree

    def _create_field_details_panel(self, parent: ttk.Frame) -> ttk.Frame:
        panel = ttk.Frame(
            parent,
            relief=tk.GROOVE,
            borderwidth=1,
            padding=10,
        )
        panel.columnconfigure(0, weight=1)
        panel.bind("<Configure>", self._on_field_details_configure)
        self._field_details_wrapped_labels: list[ttk.Label] = []

        heading = ttk.Label(panel, text="Field Details", font=("TkDefaultFont", 12, "bold"))
        heading.grid(row=0, column=0, sticky="w", pady=(0, 8))

        name_title = ttk.Label(panel, text="Name:")
        name_title.grid(row=1, column=0, sticky="w")
        name_value = ttk.Entry(panel, textvariable=self.edit_field_name_var)
        name_value.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.edit_field_name_var.trace_add("write", self._on_field_name_changed)

        mandatory_title = ttk.Label(panel, text="Mandatory:")
        mandatory_title.grid(row=3, column=0, sticky="w")
        mandatory_value = ttk.Checkbutton(panel, variable=self.edit_field_mandatory_var)
        mandatory_value.grid(row=4, column=0, sticky="w", pady=(0, 8))
        self.edit_field_mandatory_var.trace_add("write", self._on_field_mandatory_changed)

        path_title = ttk.Label(panel, text="Path:")
        path_title.grid(row=5, column=0, sticky="w")
        path_value = ttk.Entry(panel, textvariable=self.edit_field_path_var)
        path_value.grid(row=6, column=0, sticky="ew", pady=(0, 8))
        path_value.bind("<FocusOut>", self._on_field_path_commit)
        path_value.bind("<Return>", self._on_field_path_commit)

        true_path_title = ttk.Label(panel, text="True Path:")
        true_path_title.grid(row=7, column=0, sticky="w")
        true_path_value = ttk.Label(
            panel,
            textvariable=self.field_true_path_text,
            wraplength=280,
            justify=tk.LEFT,
        )
        true_path_value.grid(row=8, column=0, sticky="w", pady=(0, 8))
        self._field_details_wrapped_labels.append(true_path_value)

        mapped_title = ttk.Label(panel, text="Mapped Value:")
        mapped_title.grid(row=9, column=0, sticky="w")
        mapped_value = ttk.Label(
            panel,
            textvariable=self.field_mapped_value_text,
            wraplength=280,
            justify=tk.LEFT,
        )
        mapped_value.grid(row=10, column=0, sticky="w", pady=(0, 8))
        self._field_details_wrapped_labels.append(mapped_value)

        updated_title = ttk.Label(panel, text="Updated:")
        updated_title.grid(row=11, column=0, sticky="w")
        updated_value = ttk.Label(
            panel,
            textvariable=self.field_updated_text,
            wraplength=280,
            justify=tk.LEFT,
        )
        updated_value.grid(row=12, column=0, sticky="w", pady=(0, 8))
        self._field_details_wrapped_labels.append(updated_value)

        descr_title = ttk.Label(panel, text="Descr:")
        descr_title.grid(row=13, column=0, sticky="w")
        descr_value = ttk.Entry(panel, textvariable=self.field_descr_text)
        descr_value.grid(row=14, column=0, sticky="ew", pady=(0, 8))
        self.field_descr_text.trace_add("write", self._on_field_descr_changed)

        hierarchy_title = ttk.Label(panel, text="Hierarchy:")
        hierarchy_title.grid(row=15, column=0, sticky="w")
        hierarchy_value = ttk.Label(
            panel,
            textvariable=self.field_hierarchy_text,
            wraplength=280,
            justify=tk.LEFT,
        )
        hierarchy_value.grid(row=16, column=0, sticky="w")
        self._field_details_wrapped_labels.append(hierarchy_value)

        self.root.after(0, self._update_field_details_wraplength)
        return panel

    def _create_document_details_panel(self, parent: ttk.Frame) -> ttk.Frame:
        panel = ttk.Frame(parent, relief=tk.GROOVE, borderwidth=1, padding=10)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(0, weight=1)
        panel.bind("<Configure>", self._on_document_details_configure)
        self._document_details_wrapped_labels: list[ttk.Label] = []

        editor_frame = ttk.Frame(panel)
        editor_frame.grid(row=0, column=0, sticky="nsew")
        editor_frame.columnconfigure(0, weight=1)
        editor_frame.rowconfigure(10, weight=3)
        editor_frame.rowconfigure(12, weight=2)
        self.document_details_editor_frame = editor_frame

        heading = ttk.Label(editor_frame, text="Document Details", font=("TkDefaultFont", 12, "bold"))
        heading.grid(row=0, column=0, sticky="w", pady=(0, 8))

        name_title = ttk.Label(editor_frame, text="Name:")
        name_title.grid(row=1, column=0, sticky="w")
        name_value = ttk.Entry(editor_frame, textvariable=self.edit_document_name_var)
        name_value.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        name_value.bind("<KeyRelease>", self._on_document_name_changed)
        name_value.bind("<FocusOut>", self._on_document_name_commit)
        name_value.bind("<Return>", self._on_document_name_commit)

        descr_title = ttk.Label(editor_frame, text="Description:")
        descr_title.grid(row=3, column=0, sticky="w")
        descr_value = ttk.Entry(editor_frame, textvariable=self.document_descr_edit_text)
        descr_value.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        self.document_descr_edit_text.trace_add("write", self._on_document_descr_changed)

        updated_title = ttk.Label(editor_frame, text="Updated:")
        updated_title.grid(row=5, column=0, sticky="w")
        updated_value = ttk.Label(editor_frame, textvariable=self.document_updated_text, wraplength=280, justify=tk.LEFT)
        updated_value.grid(row=6, column=0, sticky="w", pady=(0, 8))
        self._document_details_wrapped_labels.append(updated_value)

        self.document_triggered_title = ttk.Label(editor_frame, text="Triggered:")
        self.document_triggered_title.grid(row=7, column=0, sticky="w")
        self.document_triggered_value = ttk.Label(
            editor_frame,
            textvariable=self.document_triggered_text,
            wraplength=280,
            justify=tk.LEFT,
        )
        self.document_triggered_value.grid(row=8, column=0, sticky="w", pady=(0, 8))
        self._document_details_wrapped_labels.append(self.document_triggered_value)

        self.document_condition_toggle_button = ttk.Button(
            editor_frame,
            command=self._toggle_document_condition_collapsed,
        )
        self.document_condition_toggle_button.grid(row=9, column=0, sticky="ew", pady=(0, 2))
        condition_value = tk.Text(editor_frame, height=10, wrap="word", undo=True)
        condition_value.grid(row=10, column=0, sticky="nsew", pady=(0, 8))
        condition_value.bind("<KeyRelease>", self._on_document_condition_changed)
        self.document_condition_widget = condition_value

        self.document_match_details_toggle_button = ttk.Button(
            editor_frame,
            command=self._toggle_document_match_details_collapsed,
        )
        self.document_match_details_toggle_button.grid(row=11, column=0, sticky="ew", pady=(0, 2))
        match_details_frame = ttk.Frame(editor_frame)
        match_details_frame.grid(row=12, column=0, sticky="nsew")
        match_details_frame.columnconfigure(0, weight=1)
        match_details_frame.rowconfigure(0, weight=1)
        match_details_value = tk.Text(match_details_frame, height=6, wrap="word", undo=False)
        match_details_value.grid(row=0, column=0, sticky="nsew")
        match_details_scroll = ttk.Scrollbar(match_details_frame, orient=tk.VERTICAL, command=match_details_value.yview)
        match_details_scroll.grid(row=0, column=1, sticky="ns")
        match_details_value.configure(yscrollcommand=match_details_scroll.set, state=tk.DISABLED)
        match_details_value.tag_configure("match_pass", foreground="blue")
        match_details_value.tag_configure("match_fail", foreground="red")
        match_details_value.tag_configure("match_info", foreground=self.MACOS_TEXT_FOREGROUND)
        self.document_match_details_frame = match_details_frame
        self.document_match_details_widget = match_details_value

        self._update_document_triggered_visibility()
        self._apply_document_details_section_visibility()
        self.root.after(0, self._update_document_details_wraplength)
        return panel

    def _on_main_pane_release(self, _event: tk.Event) -> None:
        self._persist_documents_panel_width()

    def _on_docs_layouts_pane_release(self, _event: tk.Event) -> None:
        self._persist_layouts_panel_width()

    def _on_field_details_configure(self, _event: tk.Event) -> None:
        self._update_field_details_wraplength()

    def _on_document_details_configure(self, _event: tk.Event) -> None:
        self._update_document_details_wraplength()

    def _on_layout_properties_configure(self, _event: tk.Event) -> None:
        self._update_layout_properties_wraplength()

    def _update_field_details_wraplength(self) -> None:
        if not hasattr(self, "field_details_panel"):
            return
        panel_width = self.field_details_panel.winfo_width()
        if panel_width <= 1:
            return
        wrap_length = max(panel_width - 28, 120)
        for label in self._field_details_wrapped_labels:
            label.configure(wraplength=wrap_length)

    def _update_document_details_wraplength(self) -> None:
        if not hasattr(self, "document_details_panel"):
            return
        panel_width = self.document_details_panel.winfo_width()
        if panel_width <= 1:
            return
        wrap_length = max(panel_width - 28, 120)
        for label in self._document_details_wrapped_labels:
            label.configure(wraplength=wrap_length)

    def _toggle_document_condition_collapsed(self) -> None:
        self.document_condition_collapsed = not self.document_condition_collapsed
        self._persist_document_details_section_state()
        self._apply_document_details_section_visibility()

    def _toggle_document_match_details_collapsed(self) -> None:
        self.document_match_details_collapsed = not self.document_match_details_collapsed
        self._persist_document_details_section_state()
        self._apply_document_details_section_visibility()

    def _apply_document_details_section_visibility(self) -> None:
        if hasattr(self, "document_condition_toggle_button"):
            prefix = "[+]" if self.document_condition_collapsed else "[-]"
            self.document_condition_toggle_button.config(text=f"{prefix} Condition")
        if hasattr(self, "document_condition_widget"):
            if self.document_condition_collapsed:
                self.document_condition_widget.grid_remove()
            else:
                self.document_condition_widget.grid()

        if hasattr(self, "document_match_details_toggle_button"):
            prefix = "[+]" if self.document_match_details_collapsed else "[-]"
            self.document_match_details_toggle_button.config(text=f"{prefix} Match Details")
        if hasattr(self, "document_match_details_frame"):
            if self.document_match_details_collapsed:
                self.document_match_details_frame.grid_remove()
            else:
                self.document_match_details_frame.grid()
        self._update_document_details_section_weights()

    def _update_document_details_section_weights(self) -> None:
        editor_frame = getattr(self, "document_details_editor_frame", None)
        if editor_frame is None:
            return

        condition_visible = not self.document_condition_collapsed
        match_details_visible = not self.document_match_details_collapsed
        if condition_visible and match_details_visible:
            condition_weight = 3
            match_details_weight = 2
        elif condition_visible:
            condition_weight = 5
            match_details_weight = 0
        elif match_details_visible:
            condition_weight = 0
            match_details_weight = 5
        else:
            condition_weight = 0
            match_details_weight = 0

        editor_frame.rowconfigure(10, weight=condition_weight)
        editor_frame.rowconfigure(12, weight=match_details_weight)

    def _update_document_triggered_visibility(self) -> None:
        if not hasattr(self, "document_triggered_title") or not hasattr(self, "document_triggered_value"):
            return
        if self.current_data_payload is None:
            self.document_triggered_title.grid_remove()
            self.document_triggered_value.grid_remove()
            return
        self.document_triggered_title.grid()
        self.document_triggered_value.grid()

    def _update_layout_properties_wraplength(self) -> None:
        if not hasattr(self, "layout_properties_panel"):
            return
        panel_width = self.layout_properties_panel.winfo_width()
        if panel_width <= 1:
            return
        wrap_length = max(panel_width - 28, 120)
        for label in self._layout_wrapped_labels:
            label.configure(wraplength=wrap_length)

    def _apply_saved_documents_panel_width(self) -> None:
        self.root.update_idletasks()
        total_height = self.left_vertical_pane.winfo_height()
        if total_height <= 1:
            return
        docs_height = max(180, min(self.documents_panel_width, total_height - 160))
        self.documents_panel_width = docs_height
        self.left_vertical_pane.sashpos(0, docs_height)

    def _persist_documents_panel_width(self) -> None:
        height = self.documents_panel.winfo_height()
        if height < 120:
            return
        self.documents_panel_width = height
        self._update_app_state({"documents_panel_width": height})

    def _load_saved_documents_panel_width(self) -> int:
        state = self._read_app_state()
        width = self._safe_int(state.get("documents_panel_width"))
        if width is None or width < 120:
            return 320
        return width

    def _apply_saved_layouts_panel_width(self) -> None:
        self.root.update_idletasks()
        total_width = self.docs_layouts_pane.winfo_width()
        if total_width <= 1:
            return
        left_width = max(360, min(self.layouts_panel_width, total_width - 260))
        self.layouts_panel_width = left_width
        self.docs_layouts_pane.sashpos(0, left_width)

    def _persist_layouts_panel_width(self) -> None:
        width = self.left_column_frame.winfo_width()
        if width < 220:
            return
        self.layouts_panel_width = width
        self._update_app_state({"layouts_panel_width": width})

    def _load_saved_layouts_panel_width(self) -> int:
        state = self._read_app_state()
        width = self._safe_int(state.get("layouts_panel_width"))
        if width is None or width < 220:
            return 620
        return width

    def _on_clause_manager_pane_release(self, _event: tk.Event) -> None:
        self._persist_clause_manager_split()

    def _apply_saved_clause_manager_split(self) -> None:
        if not hasattr(self, "clause_manager_pane"):
            return
        pane = self.clause_manager_pane
        if pane is None or not pane.winfo_exists():
            return
        if not hasattr(self, "clause_manager_list_frame"):
            return
        self.root.update_idletasks()
        total_width = pane.winfo_width()
        if total_width <= 1:
            return
        list_width = max(220, min(self.clause_manager_list_width, total_width - 300))
        self.clause_manager_list_width = list_width
        pane.sashpos(0, list_width)

    def _persist_clause_manager_split(self) -> None:
        if not hasattr(self, "clause_manager_list_frame"):
            return
        frame = self.clause_manager_list_frame
        if frame is None or not frame.winfo_exists():
            return
        width = frame.winfo_width()
        if width < 160:
            return
        self.clause_manager_list_width = width
        self._update_app_state({"clause_manager_list_width": width})

    def _load_saved_clause_manager_list_width(self) -> int:
        state = self._read_app_state()
        width = self._safe_int(state.get("clause_manager_list_width"))
        if width is None or width < 160:
            return 360
        return width

    def _load_document_details_section_collapsed(self, section: str) -> bool:
        state = self._read_app_state()
        value = state.get(f"document_details_{section}_collapsed")
        return bool(value) if isinstance(value, bool) else False

    def _persist_document_details_section_state(self) -> None:
        self._update_app_state(
            {
                "document_details_condition_collapsed": self.document_condition_collapsed,
                "document_details_match_details_collapsed": self.document_match_details_collapsed,
            }
        )

    def _create_fields_window(self) -> None:
        if self.fields_window is not None and self.fields_window.winfo_exists():
            return
        self.fields_window = self._create_toplevel(self.root)
        self.fields_window.title("ATool - Field Manager")
        self.fields_window.minsize(480, 360)
        self._attach_app_menu(self.fields_window)
        self.fields_window.protocol("WM_DELETE_WINDOW", self._hide_fields_window)
        self.fields_window.bind("<Configure>", self._on_fields_window_configure)

        container = ttk.Frame(self.fields_window, padding=12)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        fields_vertical_pane = ttk.Panedwindow(container, orient=tk.VERTICAL)
        fields_vertical_pane.grid(row=0, column=0, sticky="nsew")

        self.fields_panel, self.fields_tree = self._create_tree_panel(fields_vertical_pane, "Field Manager")
        self.fields_tree.bind("<<TreeviewSelect>>", self._on_field_tree_select)
        self.field_details_panel = self._create_field_details_panel(fields_vertical_pane)
        fields_vertical_pane.add(self.fields_panel, weight=3)
        fields_vertical_pane.add(self.field_details_panel, weight=2)

        self._restore_fields_window_geometry()
        self.root.after(0, self._position_fields_window_if_needed)

    def _position_fields_window_if_needed(self) -> None:
        if self.fields_window is None or not self.fields_window.winfo_exists():
            return
        state = self._read_app_state()
        geometry = state.get("fields_window_geometry")
        if isinstance(geometry, dict):
            return
        self.root.update_idletasks()
        self.fields_window.update_idletasks()
        x_pos = self.root.winfo_x() + self.root.winfo_width() + 14
        y_pos = self.root.winfo_y()
        width = max(560, self.fields_window.winfo_width())
        height = max(520, self.root.winfo_height())
        self.fields_window.geometry(f"{width}x{height}+{x_pos}+{y_pos}")

    def _show_fields_window(self) -> None:
        self._create_fields_window()
        assert self.fields_window is not None
        self.fields_window.deiconify()
        self.fields_window.lift()
        self.fields_window.focus_force()

    def _hide_fields_window(self) -> None:
        if self.fields_window is None or not self.fields_window.winfo_exists():
            return
        self.fields_window.withdraw()

    def _on_fields_window_configure(self, event: tk.Event) -> None:
        if self.fields_window is None or event.widget is not self.fields_window:
            return
        if self._fields_window_geometry_job:
            self.root.after_cancel(self._fields_window_geometry_job)
        self._fields_window_geometry_job = self.root.after(300, self._persist_fields_window_geometry)

    def _restore_fields_window_geometry(self) -> None:
        if self.fields_window is None or not self.fields_window.winfo_exists():
            return
        state = self._read_app_state()
        geometry = state.get("fields_window_geometry")
        if not isinstance(geometry, dict):
            return
        width = self._safe_int(geometry.get("width"))
        height = self._safe_int(geometry.get("height"))
        x_pos = self._safe_int(geometry.get("x"))
        y_pos = self._safe_int(geometry.get("y"))
        if all(value is not None for value in [width, height, x_pos, y_pos]):
            self.fields_window.geometry(f"{width}x{height}+{x_pos}+{y_pos}")

    def _persist_fields_window_geometry(self) -> None:
        self._fields_window_geometry_job = None
        if self.fields_window is None or not self.fields_window.winfo_exists():
            return
        if self.fields_window.state() == "withdrawn":
            return
        width = self.fields_window.winfo_width()
        height = self.fields_window.winfo_height()
        x_pos = self.fields_window.winfo_x()
        y_pos = self.fields_window.winfo_y()
        if width <= 1 or height <= 1:
            return
        self._update_app_state(
            {
                "fields_window_geometry": {
                    "width": width,
                    "height": height,
                    "x": x_pos,
                    "y": y_pos,
                }
            }
        )

    def _show_condition_library_window(self) -> None:
        self._create_condition_library_window()
        assert self.condition_library_window is not None
        self.condition_library_window.deiconify()
        self.condition_library_window.lift()
        self.condition_library_window.focus_force()
        self._render_condition_library_list()
        self._autofill_compose_from_current_target()
        self._update_clause_manager_target_label()

    def _create_condition_library_window(self) -> None:
        if self.condition_library_window is not None and self.condition_library_window.winfo_exists():
            return
        self.condition_library_window = self._create_toplevel(self.root)
        self.condition_library_window.title("ATool - Clause Manager")
        self.condition_library_window.minsize(560, 420)
        self._attach_app_menu(self.condition_library_window)
        self.condition_library_window.protocol("WM_DELETE_WINDOW", self._hide_condition_library_window)
        self.condition_library_window.bind("<Configure>", self._on_condition_library_window_configure)

        container = ttk.Frame(self.condition_library_window, padding=12)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        heading = ttk.Label(container, text="Clause Manager", font=("TkDefaultFont", 12, "bold"))
        heading.grid(row=0, column=0, sticky="w", pady=(0, 8))

        manager_vertical_pane = ttk.Panedwindow(container, orient=tk.VERTICAL)
        manager_vertical_pane.grid(row=1, column=0, sticky="nsew")

        top_container = ttk.Frame(manager_vertical_pane)
        top_container.columnconfigure(0, weight=1)
        top_container.rowconfigure(0, weight=1)

        manager_pane = ttk.Panedwindow(top_container, orient=tk.HORIZONTAL)
        manager_pane.grid(row=0, column=0, sticky="nsew")
        manager_pane.bind("<ButtonRelease-1>", self._on_clause_manager_pane_release)
        self.clause_manager_pane = manager_pane

        list_container = ttk.Frame(top_container)
        list_container.columnconfigure(0, weight=1)
        list_container.rowconfigure(1, weight=1)

        list_filter_row = ttk.Frame(list_container)
        list_filter_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        list_filter_row.columnconfigure(0, weight=1)
        self.condition_library_filter_entry = ttk.Entry(
            list_filter_row,
            textvariable=self.condition_clause_filter_var,
        )
        self.condition_library_filter_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(
            list_filter_row,
            text="Clear",
            command=self._clear_condition_library_filter,
        ).grid(row=0, column=1, padx=(6, 0))

        self.condition_library_list = ttk.Treeview(list_container, columns=("description",), show="tree headings")
        self.condition_library_list.heading("#0", text="Name")
        self.condition_library_list.heading("description", text="Description")
        self.condition_library_list.column("#0", width=180, anchor=tk.W)
        self.condition_library_list.column("description", width=220, anchor=tk.W)
        self.condition_library_list.grid(row=1, column=0, sticky="nsew")
        self.condition_library_list_vscroll = ttk.Scrollbar(
            list_container,
            orient=tk.VERTICAL,
            command=self.condition_library_list.yview,
        )
        self.condition_library_list_vscroll.grid(row=1, column=1, sticky="ns")
        self.condition_library_list_hscroll = ttk.Scrollbar(
            list_container,
            orient=tk.HORIZONTAL,
            command=self.condition_library_list.xview,
        )
        self.condition_library_list_hscroll.grid(row=2, column=0, sticky="ew")
        self.condition_library_list.configure(
            yscrollcommand=self.condition_library_list_vscroll.set,
            xscrollcommand=self.condition_library_list_hscroll.set,
        )
        self.condition_library_list.bind("<<TreeviewSelect>>", self._on_condition_library_select)
        self.clause_manager_list_frame = list_container

        form = ttk.Frame(manager_pane)
        form.columnconfigure(0, weight=1)
        form.rowconfigure(6, weight=1)
        self.clause_manager_form_frame = form

        ttk.Label(form, text="Clause Editor", font=("TkDefaultFont", 11, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        ttk.Label(form, text="Name:").grid(row=1, column=0, sticky="w")
        self.condition_library_name_var = tk.StringVar(value="")
        self.condition_library_name_entry = ttk.Entry(form, textvariable=self.condition_library_name_var)
        self.condition_library_name_entry.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(form, text="Description:").grid(row=3, column=0, sticky="w")
        self.condition_library_descr_var = tk.StringVar(value="")
        self.condition_library_descr_entry = ttk.Entry(form, textvariable=self.condition_library_descr_var)
        self.condition_library_descr_entry.grid(row=4, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(form, text="Clause Expression:").grid(row=5, column=0, sticky="w")
        self.condition_library_expr = tk.Text(form, height=10, wrap="word", undo=True)
        self.condition_library_expr.grid(row=6, column=0, sticky="nsew")

        actions = ttk.Frame(form)
        actions.grid(row=7, column=0, sticky="e", pady=(10, 0))
        ttk.Button(actions, text="Add", command=self._add_condition_library_entry).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(actions, text="Delete", command=self._delete_condition_library_entry).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(actions, text="Save", command=self._save_condition_library_entry).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(actions, text="Find Usage...", command=self._show_selected_clause_usage).grid(
            row=0, column=3, padx=(0, 6)
        )
        ttk.Button(actions, text="Find Raw...", command=self._show_raw_condition_usage).grid(
            row=0, column=4, padx=(0, 6)
        )
        ttk.Button(
            actions,
            text="Update Triggers...",
            command=self._update_document_triggers_from_clause_entry,
        ).grid(row=0, column=5)

        compose_group = ttk.LabelFrame(manager_vertical_pane, text="")
        compose_group.columnconfigure(0, weight=1)
        compose_group.columnconfigure(1, weight=0)
        compose_group.rowconfigure(1, weight=1)
        ttk.Label(
            compose_group,
            text="Compose Condition",
            font=("TkDefaultFont", 11, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=8, pady=(6, 0))
        ttk.Button(
            compose_group,
            text="(i)",
            width=3,
            command=self._show_compose_help,
        ).grid(row=0, column=1, sticky="ne", padx=(0, 8), pady=(6, 2))
        compose_text_frame = ttk.Frame(compose_group)
        compose_text_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=8, pady=(6, 8))
        compose_text_frame.columnconfigure(0, weight=1)
        compose_text_frame.rowconfigure(0, weight=1)
        compose_entry = tk.Text(compose_text_frame, height=8, wrap="word", undo=True)
        compose_entry.grid(row=0, column=0, sticky="nsew")
        compose_scroll = ttk.Scrollbar(compose_text_frame, orient=tk.VERTICAL, command=compose_entry.yview)
        compose_scroll.grid(row=0, column=1, sticky="ns")
        compose_entry.configure(yscrollcommand=compose_scroll.set)
        self.compose_entry_widget = compose_entry
        compose_entry.bind("<KeyRelease>", self._on_compose_entry_keyrelease)
        compose_entry.bind("<Down>", self._on_compose_entry_down)
        compose_entry.bind("<Up>", self._on_compose_entry_up)
        compose_entry.bind("<Tab>", self._on_compose_entry_tab)
        compose_entry.bind("<Return>", self._on_compose_entry_return)
        compose_entry.bind("<Escape>", self._on_compose_entry_escape)
        compose_entry.bind("<FocusOut>", self._on_compose_entry_focus_out)
        picker_row = ttk.Frame(compose_group)
        picker_row.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        picker_row.columnconfigure(1, weight=1)
        ttk.Label(picker_row, text="Clause:").grid(row=0, column=0, sticky="w")
        self.condition_clause_name_var = tk.StringVar(value="")
        self.condition_clause_name_combo = ttk.Combobox(
            picker_row,
            textvariable=self.condition_clause_name_var,
            state="readonly",
            values=[],
        )
        self.condition_clause_name_combo.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        compose_actions = ttk.Frame(compose_group)
        compose_actions.grid(row=3, column=0, columnspan=2, sticky="e", padx=8, pady=(0, 6))
        ttk.Button(compose_actions, text="Insert Name", command=self._insert_selected_clause_name).grid(
            row=0, column=0, padx=(0, 6)
        )
        ttk.Button(compose_actions, text="Apply Composed", command=self._apply_composed_condition).grid(
            row=0, column=1
        )
        ttk.Label(compose_group, textvariable=self.condition_compose_status_var).grid(
            row=4, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4)
        )
        ttk.Label(
            compose_group,
            textvariable=self.condition_compose_target_var,
            font=("TkDefaultFont", 10, "bold"),
        ).grid(
            row=5, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8)
        )

        self._restore_condition_library_window_geometry()
        self.root.after(0, self._position_condition_library_window_if_needed)
        self._refresh_clause_name_dropdown()
        manager_vertical_pane.add(top_container, weight=3)
        manager_vertical_pane.add(compose_group, weight=2)
        manager_pane.add(list_container, weight=2)
        manager_pane.add(form, weight=3)
        self.root.after(0, self._apply_saved_clause_manager_split)

    def _hide_condition_library_window(self) -> None:
        if self.condition_library_window is None or not self.condition_library_window.winfo_exists():
            return
        self._hide_compose_autocomplete()
        self.condition_library_window.withdraw()

    def _on_condition_library_window_configure(self, event: tk.Event) -> None:
        if self.condition_library_window is None or event.widget is not self.condition_library_window:
            return
        if self._condition_library_window_geometry_job:
            self.root.after_cancel(self._condition_library_window_geometry_job)
        self._condition_library_window_geometry_job = self.root.after(300, self._persist_condition_library_window_geometry)

    def _restore_condition_library_window_geometry(self) -> None:
        if self.condition_library_window is None or not self.condition_library_window.winfo_exists():
            return
        state = self._read_app_state()
        geometry = state.get("condition_library_window_geometry")
        if not isinstance(geometry, dict):
            return
        width = self._safe_int(geometry.get("width"))
        height = self._safe_int(geometry.get("height"))
        x_pos = self._safe_int(geometry.get("x"))
        y_pos = self._safe_int(geometry.get("y"))
        if all(value is not None for value in [width, height, x_pos, y_pos]):
            self.condition_library_window.geometry(f"{width}x{height}+{x_pos}+{y_pos}")

    def _persist_condition_library_window_geometry(self) -> None:
        self._condition_library_window_geometry_job = None
        if self.condition_library_window is None or not self.condition_library_window.winfo_exists():
            return
        if self.condition_library_window.state() == "withdrawn":
            return
        width = self.condition_library_window.winfo_width()
        height = self.condition_library_window.winfo_height()
        x_pos = self.condition_library_window.winfo_x()
        y_pos = self.condition_library_window.winfo_y()
        if width <= 1 or height <= 1:
            return
        self._update_app_state(
            {
                "condition_library_window_geometry": {
                    "width": width,
                    "height": height,
                    "x": x_pos,
                    "y": y_pos,
                }
            }
        )

    def _position_condition_library_window_if_needed(self) -> None:
        if self.condition_library_window is None or not self.condition_library_window.winfo_exists():
            return
        state = self._read_app_state()
        geometry = state.get("condition_library_window_geometry")
        if isinstance(geometry, dict):
            return
        self.root.update_idletasks()
        self.condition_library_window.update_idletasks()
        x_pos = self.root.winfo_x() + 80
        y_pos = self.root.winfo_y() + 80
        width = max(760, self.condition_library_window.winfo_width())
        height = max(520, self.condition_library_window.winfo_height())
        self.condition_library_window.geometry(f"{width}x{height}+{x_pos}+{y_pos}")

    def _render_condition_library_list(self) -> None:
        if not hasattr(self, "condition_library_list"):
            return
        self._sort_condition_library_entries()
        self._refresh_clause_name_dropdown()
        self.condition_library_list.delete(*self.condition_library_list.get_children())
        self._condition_library_node_to_index = {}
        filter_text = self.condition_clause_filter_var.get().strip().casefold()
        for index, item in enumerate(self._condition_library_entries):
            name = str(item.get("name", "")).strip() or f"Condition {index + 1}"
            descr = str(item.get("description", "")).strip()
            expression = str(item.get("expression", "")).strip()
            if filter_text:
                haystack = f"{name}\n{descr}\n{expression}".casefold()
                if filter_text not in haystack:
                    continue
            node_id = self.condition_library_list.insert("", "end", text=name, values=(descr,))
            self.condition_library_list.set(node_id, "description", descr)
            self._condition_library_node_to_index[node_id] = index
        if self._active_condition_library_index is not None and 0 <= self._active_condition_library_index < len(self._condition_library_entries):
            for node_id, entry_index in self._condition_library_node_to_index.items():
                if entry_index != self._active_condition_library_index:
                    continue
                self.condition_library_list.selection_set(node_id)
                self.condition_library_list.focus(node_id)
                self.condition_library_list.see(node_id)
                break

    def _on_condition_library_select(self, _event: tk.Event) -> None:
        if not hasattr(self, "condition_library_list"):
            return
        selected = self.condition_library_list.selection()
        if not selected:
            self._active_condition_library_index = None
            self._populate_condition_library_form(None)
            if hasattr(self, "condition_clause_name_var"):
                self.condition_clause_name_var.set("")
            return
        node_id = selected[0]
        index = self._condition_library_node_to_index.get(node_id)
        if index is None:
            return
        self._active_condition_library_index = index
        if 0 <= index < len(self._condition_library_entries):
            selected_item = self._condition_library_entries[index]
            self._populate_condition_library_form(selected_item)
            if hasattr(self, "condition_clause_name_var"):
                self.condition_clause_name_var.set(str(selected_item.get("name", "")).strip())

    def _populate_condition_library_form(self, item: dict[str, str] | None) -> None:
        if not hasattr(self, "condition_library_name_var"):
            return
        if item is None:
            self.condition_library_name_var.set("")
            self.condition_library_descr_var.set("")
            self.condition_library_expr.delete("1.0", tk.END)
            return
        self.condition_library_name_var.set(str(item.get("name", "")))
        self.condition_library_descr_var.set(str(item.get("description", "")))
        self.condition_library_expr.delete("1.0", tk.END)
        self.condition_library_expr.insert("1.0", str(item.get("expression", "")))

    def _add_condition_library_entry(self) -> None:
        base = "Clause"
        existing = {str(item.get("name", "")).strip() for item in self._condition_library_entries}
        counter = 1
        while True:
            candidate = f"{base}{counter}"
            if candidate not in existing:
                break
            counter += 1
        item = {
            "name": candidate,
            "description": "",
            "expression": "",
            "updated_at": self._current_timestamp(),
        }
        self._condition_library_entries.append(item)
        self._sort_condition_library_entries(active_name=item["name"])
        self._render_condition_library_list()
        self._populate_condition_library_form(item)
        self._persist_condition_library()

    def _save_condition_library_entry(self) -> bool:
        if self._active_condition_library_index is None:
            return False
        index = self._active_condition_library_index
        if not (0 <= index < len(self._condition_library_entries)):
            return False
        item = self._condition_library_form_item()
        if item is None:
            return False
        previous_item = copy.deepcopy(self._condition_library_entries[index])
        if self._clause_entry_base_signature(previous_item) == self._clause_entry_base_signature(item):
            item["updated_at"] = str(previous_item.get("updated_at", "")).strip()
            item["expression_hash"] = str(previous_item.get("expression_hash", "")).strip()
        else:
            item["updated_at"] = self._current_timestamp()
        self._condition_library_entries[index] = item
        self._sort_condition_library_entries(active_name=item["name"])
        self._render_condition_library_list()
        self._persist_condition_library()
        return True

    def _condition_library_form_item(self) -> dict[str, str] | None:
        name = self.condition_library_name_var.get().strip()
        if not name:
            messagebox.showerror("Clause Manager", "Name is required.")
            return None
        expression = self.condition_library_expr.get("1.0", tk.END).rstrip("\n")
        return {
            "name": name,
            "description": self.condition_library_descr_var.get().strip(),
            "expression": expression.strip(),
        }

    def _update_document_triggers_from_clause_entry(self) -> None:
        if self._active_condition_library_index is None:
            return
        index = self._active_condition_library_index
        if not (0 <= index < len(self._condition_library_entries)):
            return
        self._sync_active_document_form_to_model()

        old_item = copy.deepcopy(self._condition_library_entries[index])
        old_name = str(old_item.get("name", "")).strip()
        old_expression = str(old_item.get("expression", "")).strip()
        new_item = self._condition_library_form_item()
        if new_item is None:
            return
        new_name = str(new_item.get("name", "")).strip()
        new_expression = str(new_item.get("expression", "")).strip()
        if new_name != old_name:
            messagebox.showerror(
                "Update Document Triggers",
                "Update Triggers can only propagate expression changes.\n\n"
                "Save clause renames separately, then update document triggers.",
            )
            return
        if not old_expression:
            messagebox.showinfo(
                "Update Document Triggers",
                "The saved clause has no existing expression to find in document triggers.",
            )
            return
        if not new_expression:
            messagebox.showerror(
                "Update Document Triggers",
                "Clause expression is required before document triggers can be updated.",
            )
            return

        old_entries = self._serialize_condition_library_entries(copy.deepcopy(self._condition_library_entries))
        new_entries = copy.deepcopy(self._condition_library_entries)
        new_entries[index] = new_item
        new_entries = self._serialize_condition_library_entries(new_entries)

        try:
            proposals = self._build_clause_trigger_update_proposals(
                old_entries,
                new_entries,
                changed_clause_name=old_name,
            )
        except ValueError as error:
            messagebox.showerror("Update Document Triggers", str(error))
            return

        if not self._save_condition_library_entry():
            return

        if old_expression == new_expression:
            messagebox.showinfo("Update Document Triggers", "Clause saved. The expression did not change.")
            return
        if not proposals:
            messagebox.showinfo(
                "Update Document Triggers",
                "Clause saved. No document triggers currently match the old clause expression.",
            )
            return
        self._show_clause_trigger_update_window(proposals, old_name)

    def _build_clause_trigger_update_proposals(
        self,
        old_entries: list[dict[str, str]],
        new_entries: list[dict[str, str]],
        *,
        changed_clause_name: str,
    ) -> list[dict[str, object]]:
        impacted_names = self._find_impacted_clause_names(
            old_entries,
            new_entries,
            changed_clause_name=changed_clause_name,
        )
        if not impacted_names:
            return []

        proposals: list[dict[str, object]] = []
        for document in self._loaded_documents:
            document_name = str(document.get("name", "")).strip()
            old_condition = str(document.get("condition", "")).strip()
            if not document_name or not old_condition:
                continue
            try:
                compose_text, _exact, _unmatched = self._compose_expression_from_raw_condition_with_entries(
                    old_condition,
                    old_entries,
                )
            except ValueError:
                continue
            matched_names = self._clause_names_in_compose_text(compose_text) & impacted_names
            if not matched_names:
                continue
            try:
                new_condition = self._render_composed_condition_with_entries(compose_text, new_entries)
            except ValueError as error:
                raise ValueError(
                    f"Could not render updated trigger for document '{document_name}'.\n\nDetails: {error}"
                ) from error
            if self._canonical_condition_expression(new_condition) == self._canonical_condition_expression(old_condition):
                continue
            match_type = self._classify_clause_trigger_match(
                compose_text,
                matched_names,
                changed_clause_name=changed_clause_name,
            )
            proposals.append(
                {
                    "document": document,
                    "document_name": document_name,
                    "old_condition": old_condition,
                    "new_condition": new_condition,
                    "compose_text": compose_text,
                    "matched_names": sorted(matched_names, key=str.casefold),
                    "match_type": match_type,
                    "status": "Pending",
                }
            )
        return proposals

    def _find_impacted_clause_names(
        self,
        old_entries: list[dict[str, str]],
        new_entries: list[dict[str, str]],
        *,
        changed_clause_name: str,
    ) -> set[str]:
        impacted: set[str] = set()
        old_names = {str(item.get("name", "")).strip() for item in old_entries}
        new_names = {str(item.get("name", "")).strip() for item in new_entries}
        for name in sorted((old_names & new_names) - {""}, key=str.casefold):
            try:
                old_expression = self._resolve_clause_expression_by_name_from_entries(old_entries, name)
            except ValueError as error:
                if name == changed_clause_name:
                    raise ValueError(f"Could not resolve the saved clause expression.\n\nDetails: {error}") from error
                continue
            try:
                new_expression = self._resolve_clause_expression_by_name_from_entries(new_entries, name)
            except ValueError as error:
                if name == changed_clause_name:
                    raise ValueError(f"Could not resolve the edited clause expression.\n\nDetails: {error}") from error
                continue
            if self._canonical_condition_expression(old_expression) != self._canonical_condition_expression(new_expression):
                impacted.add(name)
        return impacted

    def _clause_names_in_compose_text(self, compose_text: str) -> set[str]:
        try:
            tokens = self._tokenize_clause_expression(compose_text)
        except ValueError:
            return set()
        return {token_value for token_type, token_value in tokens if token_type == "NAME"}

    def _classify_clause_trigger_match(
        self,
        compose_text: str,
        matched_names: set[str],
        *,
        changed_clause_name: str,
    ) -> str:
        single_clause_name = self._single_compose_clause_name(compose_text)
        if single_clause_name == changed_clause_name:
            return "Exact clause"
        if single_clause_name:
            return "Dependent clause"
        if changed_clause_name in matched_names:
            return "Embedded clause"
        return "Dependent clause"

    def _single_compose_clause_name(self, compose_text: str) -> str:
        try:
            tokens = self._tokenize_clause_expression(compose_text)
        except ValueError:
            return ""
        if len(tokens) == 1 and tokens[0][0] == "NAME":
            return tokens[0][1]
        return ""

    def _show_clause_trigger_update_window(
        self,
        proposals: list[dict[str, object]],
        clause_name: str,
    ) -> None:
        if self.clause_trigger_update_window is not None and self.clause_trigger_update_window.winfo_exists():
            self.clause_trigger_update_window.destroy()
        self._clause_trigger_update_proposals = proposals
        self._clause_trigger_update_index = 0
        self._create_clause_trigger_update_window(clause_name)
        self._render_clause_trigger_update_rows()
        self._update_clause_trigger_update_display()
        assert self.clause_trigger_update_window is not None
        self.clause_trigger_update_window.deiconify()
        self.clause_trigger_update_window.lift()
        self.clause_trigger_update_window.focus_force()

    def _create_clause_trigger_update_window(self, clause_name: str) -> None:
        parent = self.condition_library_window if self.condition_library_window and self.condition_library_window.winfo_exists() else self.root
        window = self._create_toplevel(parent)
        window.title("ATool - Update Document Triggers")
        window.minsize(760, 520)
        window.protocol("WM_DELETE_WINDOW", self._close_clause_trigger_update_window)
        self.clause_trigger_update_window = window

        container = ttk.Frame(window, padding=12)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        self.clause_trigger_update_summary_var = tk.StringVar(value="")
        heading = ttk.Label(
            container,
            text=f"Document Trigger Updates for {clause_name}",
            font=("TkDefaultFont", 12, "bold"),
        )
        heading.grid(row=0, column=0, sticky="w", pady=(0, 6))

        body = ttk.Panedwindow(container, orient=tk.VERTICAL)
        body.grid(row=1, column=0, sticky="nsew")

        list_frame = ttk.Frame(body)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(1, weight=1)
        ttk.Label(list_frame, textvariable=self.clause_trigger_update_summary_var).grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 4),
        )
        tree = ttk.Treeview(
            list_frame,
            columns=("status", "match", "clauses"),
            show="tree headings",
            height=8,
        )
        tree.heading("#0", text="Document")
        tree.heading("status", text="Status")
        tree.heading("match", text="Match")
        tree.heading("clauses", text="Clauses")
        tree.column("#0", width=220, anchor=tk.W)
        tree.column("status", width=90, anchor=tk.W)
        tree.column("match", width=130, anchor=tk.W)
        tree.column("clauses", width=220, anchor=tk.W)
        tree.grid(row=1, column=0, sticky="nsew")
        tree_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
        tree_scroll.grid(row=1, column=1, sticky="ns")
        tree.configure(yscrollcommand=tree_scroll.set)
        tree.bind("<<TreeviewSelect>>", self._on_clause_trigger_update_select)
        self.clause_trigger_update_tree = tree

        detail_frame = ttk.Frame(body)
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.columnconfigure(1, weight=1)
        detail_frame.rowconfigure(3, weight=1)
        self.clause_trigger_update_current_var = tk.StringVar(value="")
        self.clause_trigger_update_compose_var = tk.StringVar(value="")
        ttk.Label(
            detail_frame,
            textvariable=self.clause_trigger_update_current_var,
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Label(
            detail_frame,
            textvariable=self.clause_trigger_update_compose_var,
            wraplength=720,
            justify=tk.LEFT,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Label(detail_frame, text="Current Trigger").grid(row=2, column=0, sticky="w")
        ttk.Label(detail_frame, text="Proposed Trigger").grid(row=2, column=1, sticky="w", padx=(8, 0))
        old_text = tk.Text(detail_frame, height=8, wrap="word", undo=False)
        new_text = tk.Text(detail_frame, height=8, wrap="word", undo=False)
        old_text.grid(row=3, column=0, sticky="nsew", pady=(2, 0))
        new_text.grid(row=3, column=1, sticky="nsew", padx=(8, 0), pady=(2, 0))
        self.clause_trigger_update_old_text = old_text
        self.clause_trigger_update_new_text = new_text

        actions = ttk.Frame(container)
        actions.grid(row=2, column=0, sticky="e", pady=(10, 0))
        self.clause_trigger_apply_button = ttk.Button(
            actions,
            text="Apply This",
            command=self._apply_current_clause_trigger_update,
        )
        self.clause_trigger_apply_button.grid(row=0, column=0, padx=(0, 6))
        self.clause_trigger_skip_button = ttk.Button(
            actions,
            text="Skip",
            command=self._skip_current_clause_trigger_update,
        )
        self.clause_trigger_skip_button.grid(row=0, column=1, padx=(0, 6))
        self.clause_trigger_apply_exact_button = ttk.Button(
            actions,
            text="Apply All Exact",
            command=self._apply_all_exact_clause_trigger_updates,
        )
        self.clause_trigger_apply_exact_button.grid(row=0, column=2, padx=(0, 6))
        self.clause_trigger_close_button = ttk.Button(
            actions,
            text="Cancel",
            command=self._close_clause_trigger_update_window,
        )
        self.clause_trigger_close_button.grid(row=0, column=3)

        body.add(list_frame, weight=2)
        body.add(detail_frame, weight=3)

    def _render_clause_trigger_update_rows(self) -> None:
        if not hasattr(self, "clause_trigger_update_tree"):
            return
        tree = self.clause_trigger_update_tree
        tree.delete(*tree.get_children())
        for index, proposal in enumerate(self._clause_trigger_update_proposals):
            matched_names = proposal.get("matched_names", [])
            clauses = ", ".join(str(name) for name in matched_names) if isinstance(matched_names, list) else ""
            tree.insert(
                "",
                "end",
                iid=f"clause-trigger-update-{index}",
                text=str(proposal.get("document_name", "")),
                values=(
                    str(proposal.get("status", "Pending")),
                    str(proposal.get("match_type", "")),
                    clauses,
                ),
            )

    def _on_clause_trigger_update_select(self, _event: tk.Event) -> None:
        if not hasattr(self, "clause_trigger_update_tree"):
            return
        selected = self.clause_trigger_update_tree.selection()
        if not selected:
            return
        node_id = selected[0]
        prefix = "clause-trigger-update-"
        if not node_id.startswith(prefix):
            return
        try:
            index = int(node_id[len(prefix):])
        except ValueError:
            return
        if 0 <= index < len(self._clause_trigger_update_proposals):
            self._clause_trigger_update_index = index
            self._update_clause_trigger_update_display(select_row=False)

    def _update_clause_trigger_update_display(self, *, select_row: bool = True) -> None:
        if not self._clause_trigger_update_proposals:
            return
        total = len(self._clause_trigger_update_proposals)
        pending = sum(
            1 for proposal in self._clause_trigger_update_proposals
            if str(proposal.get("status", "Pending")) == "Pending"
        )
        exact_pending = sum(
            1 for proposal in self._clause_trigger_update_proposals
            if str(proposal.get("status", "Pending")) == "Pending"
            and str(proposal.get("match_type", "")) == "Exact clause"
        )
        self.clause_trigger_update_summary_var.set(
            f"{total} document trigger{'s' if total != 1 else ''} found. "
            f"{pending} pending, {exact_pending} exact."
        )
        self._clause_trigger_update_index = max(0, min(self._clause_trigger_update_index, total - 1))
        proposal = self._clause_trigger_update_proposals[self._clause_trigger_update_index]
        matched_names = proposal.get("matched_names", [])
        clauses = ", ".join(str(name) for name in matched_names) if isinstance(matched_names, list) else ""
        self.clause_trigger_update_current_var.set(
            f"{self._clause_trigger_update_index + 1} of {total}: "
            f"{proposal.get('document_name', '')} ({proposal.get('match_type', '')})"
        )
        self.clause_trigger_update_compose_var.set(
            f"Clauses: {clauses}\nComposed trigger: {proposal.get('compose_text', '')}"
        )
        self._set_readonly_text_widget_value(
            self.clause_trigger_update_old_text,
            str(proposal.get("old_condition", "")),
        )
        self._set_readonly_text_widget_value(
            self.clause_trigger_update_new_text,
            str(proposal.get("new_condition", "")),
        )
        if select_row and hasattr(self, "clause_trigger_update_tree"):
            node_id = f"clause-trigger-update-{self._clause_trigger_update_index}"
            if self.clause_trigger_update_tree.exists(node_id):
                self.clause_trigger_update_tree.selection_set(node_id)
                self.clause_trigger_update_tree.focus(node_id)
                self.clause_trigger_update_tree.see(node_id)

        status = str(proposal.get("status", "Pending"))
        current_state = tk.NORMAL if status == "Pending" else tk.DISABLED
        exact_state = tk.NORMAL if exact_pending > 0 else tk.DISABLED
        self.clause_trigger_apply_button.configure(state=current_state)
        self.clause_trigger_skip_button.configure(state=current_state)
        self.clause_trigger_apply_exact_button.configure(state=exact_state)
        self.clause_trigger_close_button.configure(text="Close" if pending == 0 else "Cancel")

    @staticmethod
    def _set_readonly_text_widget_value(widget: tk.Text, value: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        if value:
            widget.insert("1.0", value)
        widget.configure(state=tk.DISABLED)

    def _apply_current_clause_trigger_update(self) -> None:
        if not self._clause_trigger_update_proposals:
            return
        proposal = self._clause_trigger_update_proposals[self._clause_trigger_update_index]
        if str(proposal.get("status", "Pending")) != "Pending":
            return
        if not self._apply_clause_trigger_update_proposal(proposal, prompt_stale=True):
            return
        proposal["status"] = "Applied"
        self._render_clause_trigger_update_rows()
        self._select_next_pending_clause_trigger_update()
        self._update_clause_trigger_update_display()

    def _skip_current_clause_trigger_update(self) -> None:
        if not self._clause_trigger_update_proposals:
            return
        proposal = self._clause_trigger_update_proposals[self._clause_trigger_update_index]
        if str(proposal.get("status", "Pending")) != "Pending":
            return
        proposal["status"] = "Skipped"
        self._render_clause_trigger_update_rows()
        self._select_next_pending_clause_trigger_update()
        self._update_clause_trigger_update_display()

    def _apply_all_exact_clause_trigger_updates(self) -> None:
        exact_indices = [
            index for index, proposal in enumerate(self._clause_trigger_update_proposals)
            if str(proposal.get("status", "Pending")) == "Pending"
            and str(proposal.get("match_type", "")) == "Exact clause"
        ]
        if not exact_indices:
            messagebox.showinfo("Update Document Triggers", "There are no pending exact matches.")
            return
        if not messagebox.askyesno(
            "Update Document Triggers",
            f"Apply {len(exact_indices)} exact document trigger update"
            f"{'s' if len(exact_indices) != 1 else ''}?",
        ):
            return
        applied = 0
        skipped_stale = 0
        for index in exact_indices:
            proposal = self._clause_trigger_update_proposals[index]
            if self._apply_clause_trigger_update_proposal(proposal, prompt_stale=False):
                proposal["status"] = "Applied"
                applied += 1
            else:
                skipped_stale += 1
        self._render_clause_trigger_update_rows()
        self._select_next_pending_clause_trigger_update()
        self._update_clause_trigger_update_display()
        if skipped_stale:
            messagebox.showwarning(
                "Update Document Triggers",
                f"Applied {applied}. Skipped {skipped_stale} exact match"
                f"{'es' if skipped_stale != 1 else ''} because the current trigger no longer matched the preview.",
            )

    def _select_next_pending_clause_trigger_update(self) -> None:
        total = len(self._clause_trigger_update_proposals)
        if total == 0:
            return
        start = self._clause_trigger_update_index
        for offset in range(1, total + 1):
            index = (start + offset) % total
            if str(self._clause_trigger_update_proposals[index].get("status", "Pending")) == "Pending":
                self._clause_trigger_update_index = index
                return

    def _apply_clause_trigger_update_proposal(
        self,
        proposal: dict[str, object],
        *,
        prompt_stale: bool,
    ) -> bool:
        document = proposal.get("document")
        if not isinstance(document, dict):
            return False
        old_condition = str(proposal.get("old_condition", "")).strip()
        new_condition = str(proposal.get("new_condition", "")).strip()
        current_condition = str(document.get("condition", "")).strip()
        if self._canonical_condition_expression(current_condition) != self._canonical_condition_expression(old_condition):
            if not prompt_stale:
                return False
            document_name = str(proposal.get("document_name", ""))
            if not messagebox.askyesno(
                "Update Document Triggers",
                f"'{document_name}' changed since the preview was created.\n\nApply the proposed trigger anyway?",
            ):
                return False

        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        document["condition"] = new_condition
        document["updated"] = now_text
        self._sync_document_to_payload(document)

        if self.current_data_payload is not None:
            self._refresh_document_condition_mapping(document)

        self._set_dirty(True)
        source = document.get("source")
        self._refresh_documents_after_clause_trigger_update(source if isinstance(source, dict) else None)
        return True

    def _refresh_documents_after_clause_trigger_update(self, source_ref: dict[str, object] | None) -> None:
        self._render_documents_tree()
        if source_ref is not None:
            self._select_document_node_for_source(source_ref)

    def _close_clause_trigger_update_window(self) -> None:
        if self.clause_trigger_update_window is not None and self.clause_trigger_update_window.winfo_exists():
            self.clause_trigger_update_window.destroy()
        self.clause_trigger_update_window = None
        self._clause_trigger_update_proposals = []
        self._clause_trigger_update_index = 0

    def _show_selected_clause_usage(self) -> None:
        clause_name = self._active_clause_usage_name()
        if not clause_name:
            messagebox.showinfo("Clause Usage", "Select a clause first.")
            return
        self._sync_active_condition_forms_to_model()
        results = self._build_condition_usage_results(clause_name=clause_name)
        if not results:
            messagebox.showinfo("Clause Usage", f"No condition usages found for '{clause_name}'.")
            return
        title = f"Clause Usage - {clause_name}"
        summary = f"{len(results)} condition owner{'s' if len(results) != 1 else ''} use '{clause_name}'."
        self._show_condition_usage_window(results, title, summary)

    def _show_raw_condition_usage(self) -> None:
        self._sync_active_condition_forms_to_model()
        results = self._build_condition_usage_results(raw_only=True)
        if not results:
            messagebox.showinfo("Raw Condition Usage", "No conditions contain RAW fragments.")
            return
        title = "Raw Condition Usage"
        summary = f"{len(results)} condition owner{'s' if len(results) != 1 else ''} contain RAW fragments."
        self._show_condition_usage_window(results, title, summary)

    def _active_clause_usage_name(self) -> str:
        if self._active_condition_library_index is None:
            return ""
        index = self._active_condition_library_index
        if not (0 <= index < len(self._condition_library_entries)):
            return ""
        name = str(self._condition_library_entries[index].get("name", "")).strip()
        if name:
            return name
        if hasattr(self, "condition_library_name_var"):
            return self.condition_library_name_var.get().strip()
        return ""

    def _sync_active_condition_forms_to_model(self) -> None:
        self._sync_active_document_form_to_model()
        if self._updating_layout_form or not self._active_layout_node_id:
            return
        if not hasattr(self, "layout_condition_edit_var"):
            return
        self._apply_layout_form_change(condition=self.layout_condition_edit_var.get())

    def _build_condition_usage_results(
        self,
        *,
        clause_name: str = "",
        raw_only: bool = False,
    ) -> list[dict[str, object]]:
        clause_name = clause_name.strip()
        usage_names = self._find_clause_usage_names(clause_name) if clause_name else set()
        results: list[dict[str, object]] = []
        for target in self._iter_condition_usage_targets():
            condition = str(target.get("condition", "")).strip()
            if not condition:
                continue
            try:
                compose_text, exact, unmatched_count = self._compose_expression_from_raw_condition(condition)
            except ValueError as error:
                compose_text = ""
                exact = False
                unmatched_count = 0
                parse_error = str(error)
            else:
                parse_error = ""

            compose_clauses = sorted(self._clause_names_in_compose_text(compose_text), key=str.casefold)
            raw_fragments = self._raw_fragments_in_compose_text(compose_text)
            matched_clauses = sorted(set(compose_clauses) & usage_names, key=str.casefold)
            if raw_only:
                if not raw_fragments:
                    continue
                match_type = "Raw fragment"
            else:
                if not clause_name or not matched_clauses:
                    continue
                match_type = self._classify_clause_usage_match(compose_text, matched_clauses, clause_name)

            result = dict(target)
            result.update(
                {
                    "compose_text": compose_text,
                    "compose_clauses": compose_clauses,
                    "matched_clauses": matched_clauses,
                    "raw_fragments": raw_fragments,
                    "unmatched_count": unmatched_count,
                    "exact": exact,
                    "parse_error": parse_error,
                    "match_type": match_type,
                }
            )
            results.append(result)
        return results

    def _find_clause_usage_names(self, clause_name: str) -> set[str]:
        target = clause_name.strip()
        if not target:
            return set()
        usage_names = {target}
        changed = True
        while changed:
            changed = False
            for item in self._condition_library_entries:
                name = str(item.get("name", "")).strip()
                if not name or name in usage_names:
                    continue
                refs = set(self._extract_embedded_clause_references(str(item.get("expression", ""))))
                if refs & usage_names:
                    usage_names.add(name)
                    changed = True
        return usage_names

    def _classify_clause_usage_match(self, compose_text: str, matched_clauses: list[str], clause_name: str) -> str:
        matched = set(matched_clauses)
        single_clause_name = self._single_compose_clause_name(compose_text)
        if single_clause_name == clause_name:
            return "Exact clause"
        if single_clause_name and single_clause_name in matched:
            return "Dependent clause"
        if clause_name in matched:
            return "Embedded clause"
        return "Dependent clause"

    def _iter_condition_usage_targets(self) -> list[dict[str, object]]:
        targets: list[dict[str, object]] = []
        for document in self._loaded_documents:
            document_name = str(document.get("name", "")).strip() or "(unnamed document)"
            document_source = document.get("source")
            if not isinstance(document_source, dict):
                continue
            self._append_condition_usage_target(
                targets,
                document=document,
                source_ref=document_source,
                kind="document",
                owner=document_name,
                preferred_kind="document",
            )
            layouts = document_source.get("Layouts")
            if not isinstance(layouts, list):
                continue
            for index, layout in enumerate(layouts, start=1):
                if isinstance(layout, dict):
                    self._collect_layout_condition_usage_targets(targets, document, document_name, layout, index)
        return targets

    def _collect_layout_condition_usage_targets(
        self,
        targets: list[dict[str, object]],
        document: dict[str, object],
        document_name: str,
        layout: dict[str, object],
        layout_index: int,
    ) -> None:
        layout_name = self._condition_owner_name(layout, f"Layout {layout_index}")
        layout_owner = f"{document_name} > Layout: {layout_name}"
        self._append_condition_usage_target(
            targets,
            document=document,
            source_ref=layout,
            kind="layout",
            owner=layout_owner,
            preferred_kind="layout",
        )
        for content_index, content in enumerate(self._extract_contents(layout), start=1):
            content_name = self._condition_owner_name(content, f"Content {content_index}")
            content_owner = f"{layout_owner} > Content: {content_name}"
            self._append_condition_usage_target(
                targets,
                document=document,
                source_ref=content,
                kind="content",
                owner=content_owner,
                preferred_kind="condition",
            )
            iteration = self._extract_iteration(content)
            if not isinstance(iteration, dict):
                continue
            iteration_name = self._condition_owner_name(iteration, "Iteration")
            iteration_owner = f"{content_owner} > Iteration: {iteration_name}"
            self._append_condition_usage_target(
                targets,
                document=document,
                source_ref=iteration,
                kind="iteration",
                owner=iteration_owner,
                preferred_kind="condition",
            )
            for field_index, field in enumerate(self._extract_iteration_fields(iteration), start=1):
                field_name = self._condition_owner_name(field, f"Field {field_index}")
                field_owner = f"{iteration_owner} > Field: {field_name}"
                self._append_condition_usage_target(
                    targets,
                    document=document,
                    source_ref=field,
                    kind="field",
                    owner=field_owner,
                    preferred_kind="condition",
                )

    def _append_condition_usage_target(
        self,
        targets: list[dict[str, object]],
        *,
        document: dict[str, object],
        source_ref: dict[str, object],
        kind: str,
        owner: str,
        preferred_kind: str,
    ) -> None:
        condition = str(source_ref.get("Condition", "")).strip()
        if not condition:
            return
        targets.append(
            {
                "document": document,
                "source_ref": source_ref,
                "kind": kind,
                "kind_label": self._condition_usage_kind_label(kind),
                "owner": owner,
                "condition": condition,
                "preferred_kind": preferred_kind,
            }
        )

    @staticmethod
    def _condition_owner_name(source_ref: dict[str, object], fallback: str) -> str:
        name = str(source_ref.get("$$Id") or source_ref.get("Name") or source_ref.get("Id") or "").strip()
        return name or fallback

    @staticmethod
    def _condition_usage_kind_label(kind: str) -> str:
        labels = {
            "document": "Document",
            "layout": "Layout",
            "content": "Content",
            "iteration": "Iteration",
            "field": "Field",
        }
        return labels.get(kind, "Condition")

    def _raw_fragments_in_compose_text(self, compose_text: str) -> list[str]:
        if not compose_text:
            return []
        try:
            tokens = self._tokenize_clause_expression(compose_text)
        except ValueError:
            return []
        return [token_value for token_type, token_value in tokens if token_type == "RAW"]

    def _show_condition_usage_window(
        self,
        results: list[dict[str, object]],
        title: str,
        summary: str,
    ) -> None:
        if self.condition_usage_window is not None and self.condition_usage_window.winfo_exists():
            self.condition_usage_window.destroy()
        self._condition_usage_all_results = results
        self._condition_usage_results = []
        self._condition_usage_index = 0
        self._condition_usage_summary_text = summary
        self._condition_usage_type_filter = ""
        self._condition_usage_sort_column = ""
        self._condition_usage_sort_desc = False
        self._create_condition_usage_window(title, summary)
        self._refresh_condition_usage_view()
        assert self.condition_usage_window is not None
        self.condition_usage_window.deiconify()
        self.condition_usage_window.lift()
        self.condition_usage_window.focus_force()

    def _create_condition_usage_window(self, title: str, summary: str) -> None:
        parent = self.condition_library_window if self.condition_library_window and self.condition_library_window.winfo_exists() else self.root
        window = self._create_toplevel(parent)
        window.title(f"ATool - {title}")
        window.minsize(820, 520)
        window.protocol("WM_DELETE_WINDOW", self._close_condition_usage_window)
        self.condition_usage_window = window

        container = ttk.Frame(window, padding=12)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        heading = ttk.Label(container, text=title, font=("TkDefaultFont", 12, "bold"))
        heading.grid(row=0, column=0, sticky="w", pady=(0, 6))

        body = ttk.Panedwindow(container, orient=tk.VERTICAL)
        body.grid(row=1, column=0, sticky="nsew")

        list_frame = ttk.Frame(body)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(1, weight=1)
        self.condition_usage_summary_var = tk.StringVar(value=summary)
        list_header = ttk.Frame(list_frame)
        list_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        list_header.columnconfigure(0, weight=1)
        self.condition_usage_type_filter_button = ttk.Menubutton(
            list_header,
            text="Type: All",
        )
        self.condition_usage_type_filter_button.grid(
            row=0,
            column=1,
            sticky="e",
            padx=(8, 0),
        )
        self.condition_usage_type_filter_menu = tk.Menu(
            self.condition_usage_type_filter_button,
            tearoff=0,
        )
        self.condition_usage_type_filter_button.configure(menu=self.condition_usage_type_filter_menu)
        ttk.Label(list_header, textvariable=self.condition_usage_summary_var).grid(
            row=0,
            column=0,
            sticky="w",
        )
        tree = ttk.Treeview(
            list_frame,
            columns=("kind", "match", "clauses", "raw"),
            show="tree headings",
            height=9,
        )
        tree.heading("#0", text="Owner", command=lambda: self._set_condition_usage_sort("owner"))
        tree.heading("kind", text="Type", command=lambda: self._set_condition_usage_sort("kind"))
        tree.heading("match", text="Match", command=lambda: self._set_condition_usage_sort("match"))
        tree.heading("clauses", text="Matched Clauses", command=lambda: self._set_condition_usage_sort("clauses"))
        tree.heading("raw", text="Raw", command=lambda: self._set_condition_usage_sort("raw"))
        tree.column("#0", width=340, anchor=tk.W)
        tree.column("kind", width=90, anchor=tk.W)
        tree.column("match", width=120, anchor=tk.W)
        tree.column("clauses", width=190, anchor=tk.W)
        tree.column("raw", width=70, anchor=tk.W)
        tree.grid(row=1, column=0, sticky="nsew")
        tree_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
        tree_scroll.grid(row=1, column=1, sticky="ns")
        tree.configure(yscrollcommand=tree_scroll.set)
        tree.bind("<<TreeviewSelect>>", self._on_condition_usage_select)
        self.condition_usage_tree = tree

        detail_frame = ttk.Frame(body)
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.columnconfigure(1, weight=1)
        detail_frame.rowconfigure(2, weight=1)
        self.condition_usage_current_var = tk.StringVar(value="")
        ttk.Label(
            detail_frame,
            textvariable=self.condition_usage_current_var,
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Label(detail_frame, text="Condition").grid(row=1, column=0, sticky="w")
        ttk.Label(detail_frame, text="Composer / Raw Fragments").grid(row=1, column=1, sticky="w", padx=(8, 0))
        condition_text = tk.Text(detail_frame, height=9, wrap="word", undo=False)
        compose_text = tk.Text(detail_frame, height=9, wrap="word", undo=False)
        condition_text.grid(row=2, column=0, sticky="nsew", pady=(2, 0))
        compose_text.grid(row=2, column=1, sticky="nsew", padx=(8, 0), pady=(2, 0))
        self.condition_usage_condition_text = condition_text
        self.condition_usage_compose_text = compose_text

        actions = ttk.Frame(container)
        actions.grid(row=2, column=0, sticky="e", pady=(10, 0))
        self.condition_usage_select_button = ttk.Button(
            actions,
            text="Select Owner",
            command=self._select_current_condition_usage_target,
        )
        self.condition_usage_select_button.grid(row=0, column=0, padx=(0, 6))
        ttk.Button(actions, text="Close", command=self._close_condition_usage_window).grid(row=0, column=1)

        body.add(list_frame, weight=2)
        body.add(detail_frame, weight=3)

    def _refresh_condition_usage_view(self, selected_result: dict[str, object] | None = None) -> None:
        if selected_result is None and self._condition_usage_results:
            selected_result = self._condition_usage_results[self._condition_usage_index]
        available_types = self._condition_usage_available_types()
        if self._condition_usage_type_filter and self._condition_usage_type_filter not in available_types:
            self._condition_usage_type_filter = ""
        results = [
            result
            for result in self._condition_usage_all_results
            if not self._condition_usage_type_filter
            or str(result.get("kind_label", "")) == self._condition_usage_type_filter
        ]
        if self._condition_usage_sort_column:
            results.sort(
                key=lambda result: self._condition_usage_sort_key(result, self._condition_usage_sort_column),
                reverse=self._condition_usage_sort_desc,
            )
        self._condition_usage_results = results
        self._condition_usage_index = 0
        if selected_result is not None:
            for index, result in enumerate(results):
                if result is selected_result:
                    self._condition_usage_index = index
                    break
        self._refresh_condition_usage_type_filter_menu()
        self._refresh_condition_usage_summary()
        self._render_condition_usage_rows()
        self._update_condition_usage_display()

    def _condition_usage_available_types(self) -> list[str]:
        return sorted(
            {
                str(result.get("kind_label", "")).strip()
                for result in self._condition_usage_all_results
                if str(result.get("kind_label", "")).strip()
            },
            key=str.casefold,
        )

    def _refresh_condition_usage_type_filter_menu(self) -> None:
        if not hasattr(self, "condition_usage_type_filter_menu"):
            return
        menu = self.condition_usage_type_filter_menu
        menu.delete(0, tk.END)
        menu.add_command(label="All Types", command=lambda: self._set_condition_usage_type_filter(""))
        available_types = self._condition_usage_available_types()
        if available_types:
            menu.add_separator()
        for type_label in available_types:
            menu.add_command(
                label=type_label,
                command=lambda selected=type_label: self._set_condition_usage_type_filter(selected),
            )
        if hasattr(self, "condition_usage_type_filter_button"):
            button_text = f"Type: {self._condition_usage_type_filter or 'All'}"
            self.condition_usage_type_filter_button.configure(text=button_text)

    def _set_condition_usage_type_filter(self, type_label: str) -> None:
        self._condition_usage_type_filter = str(type_label or "").strip()
        self._refresh_condition_usage_view()

    def _set_condition_usage_sort(self, column: str) -> None:
        if self._condition_usage_sort_column == column:
            self._condition_usage_sort_desc = not self._condition_usage_sort_desc
        else:
            self._condition_usage_sort_column = column
            self._condition_usage_sort_desc = False
        self._refresh_condition_usage_view()

    def _refresh_condition_usage_summary(self) -> None:
        if not hasattr(self, "condition_usage_summary_var"):
            return
        total = len(self._condition_usage_all_results)
        visible = len(self._condition_usage_results)
        if self._condition_usage_type_filter:
            summary = f"{visible} of {total} shown. Type: {self._condition_usage_type_filter}. {self._condition_usage_summary_text}"
        else:
            summary = self._condition_usage_summary_text
        self.condition_usage_summary_var.set(summary)

    def _condition_usage_sort_key(self, result: dict[str, object], column: str) -> tuple[object, str]:
        owner = str(result.get("owner", ""))
        if column == "owner":
            return (owner.casefold(), "")
        if column == "kind":
            return (str(result.get("kind_label", "")).casefold(), owner.casefold())
        if column == "match":
            return (str(result.get("match_type", "")).casefold(), owner.casefold())
        if column == "clauses":
            return (self._condition_usage_result_clauses_text(result).casefold(), owner.casefold())
        if column == "raw":
            raw_fragments = result.get("raw_fragments", [])
            raw_count = len(raw_fragments) if isinstance(raw_fragments, list) else 0
            return (raw_count, owner.casefold())
        return (owner.casefold(), "")

    def _condition_usage_heading_text(self, column: str, label: str) -> str:
        if self._condition_usage_sort_column != column:
            return label
        return f"{label} {'v' if self._condition_usage_sort_desc else '^'}"

    def _configure_condition_usage_headings(self) -> None:
        if not hasattr(self, "condition_usage_tree"):
            return
        tree = self.condition_usage_tree
        tree.heading("#0", text=self._condition_usage_heading_text("owner", "Owner"), command=lambda: self._set_condition_usage_sort("owner"))
        tree.heading("kind", text=self._condition_usage_heading_text("kind", "Type"), command=lambda: self._set_condition_usage_sort("kind"))
        tree.heading("match", text=self._condition_usage_heading_text("match", "Match"), command=lambda: self._set_condition_usage_sort("match"))
        tree.heading(
            "clauses",
            text=self._condition_usage_heading_text("clauses", "Matched Clauses"),
            command=lambda: self._set_condition_usage_sort("clauses"),
        )
        tree.heading("raw", text=self._condition_usage_heading_text("raw", "Raw"), command=lambda: self._set_condition_usage_sort("raw"))

    def _condition_usage_result_clauses_text(self, result: dict[str, object]) -> str:
        matched_clauses = result.get("matched_clauses", [])
        if isinstance(matched_clauses, list) and matched_clauses:
            return ", ".join(str(name) for name in matched_clauses)
        compose_clauses = result.get("compose_clauses", [])
        if isinstance(compose_clauses, list):
            return ", ".join(str(name) for name in compose_clauses)
        return ""

    def _render_condition_usage_rows(self) -> None:
        if not hasattr(self, "condition_usage_tree"):
            return
        tree = self.condition_usage_tree
        self._configure_condition_usage_headings()
        tree.delete(*tree.get_children())
        for index, result in enumerate(self._condition_usage_results):
            raw_fragments = result.get("raw_fragments", [])
            raw_count = len(raw_fragments) if isinstance(raw_fragments, list) else 0
            clauses = self._condition_usage_result_clauses_text(result)
            tree.insert(
                "",
                "end",
                iid=f"condition-usage-{index}",
                text=self._truncate_ui_text(str(result.get("owner", "")), 120),
                values=(
                    str(result.get("kind_label", "")),
                    str(result.get("match_type", "")),
                    self._truncate_ui_text(clauses, 90),
                    str(raw_count) if raw_count else "",
                ),
            )

    def _on_condition_usage_select(self, _event: tk.Event) -> None:
        if not hasattr(self, "condition_usage_tree"):
            return
        selected = self.condition_usage_tree.selection()
        if not selected:
            return
        node_id = selected[0]
        prefix = "condition-usage-"
        if not node_id.startswith(prefix):
            return
        try:
            index = int(node_id[len(prefix):])
        except ValueError:
            return
        if 0 <= index < len(self._condition_usage_results):
            self._condition_usage_index = index
            self._update_condition_usage_display(select_row=False)

    def _update_condition_usage_display(self, *, select_row: bool = True) -> None:
        if not self._condition_usage_results:
            if hasattr(self, "condition_usage_current_var"):
                self.condition_usage_current_var.set("No condition usages match the selected Type filter.")
            if hasattr(self, "condition_usage_condition_text"):
                self._set_readonly_text_widget_value(self.condition_usage_condition_text, "")
            if hasattr(self, "condition_usage_compose_text"):
                self._set_readonly_text_widget_value(self.condition_usage_compose_text, "")
            if hasattr(self, "condition_usage_select_button"):
                self.condition_usage_select_button.configure(state=tk.DISABLED)
            return
        total = len(self._condition_usage_results)
        self._condition_usage_index = max(0, min(self._condition_usage_index, total - 1))
        result = self._condition_usage_results[self._condition_usage_index]
        owner = str(result.get("owner", ""))
        match_type = str(result.get("match_type", ""))
        self.condition_usage_current_var.set(f"{self._condition_usage_index + 1} of {total}: {owner} ({match_type})")
        self._set_readonly_text_widget_value(
            self.condition_usage_condition_text,
            str(result.get("condition", "")),
        )
        self._set_readonly_text_widget_value(
            self.condition_usage_compose_text,
            self._format_condition_usage_detail(result),
        )
        if hasattr(self, "condition_usage_select_button"):
            self.condition_usage_select_button.configure(state=tk.NORMAL)
        if select_row and hasattr(self, "condition_usage_tree"):
            node_id = f"condition-usage-{self._condition_usage_index}"
            if self.condition_usage_tree.exists(node_id):
                self.condition_usage_tree.selection_set(node_id)
                self.condition_usage_tree.focus(node_id)
                self.condition_usage_tree.see(node_id)

    def _format_condition_usage_detail(self, result: dict[str, object]) -> str:
        lines: list[str] = []
        compose_text = str(result.get("compose_text", "")).strip()
        if compose_text:
            lines.append(f"Composer:\n{compose_text}")
        compose_clauses = result.get("compose_clauses", [])
        if isinstance(compose_clauses, list) and compose_clauses:
            lines.append("Composer clauses:\n" + ", ".join(str(name) for name in compose_clauses))
        raw_fragments = result.get("raw_fragments", [])
        if isinstance(raw_fragments, list) and raw_fragments:
            raw_lines = [f"RAW{{{fragment}}}" for fragment in raw_fragments]
            lines.append("Raw fragments:\n" + "\n\n".join(raw_lines))
        parse_error = str(result.get("parse_error", "")).strip()
        if parse_error:
            lines.append(f"Parse error:\n{parse_error}")
        return "\n\n".join(lines)

    def _select_current_condition_usage_target(self) -> None:
        if not self._condition_usage_results:
            return
        result = self._condition_usage_results[self._condition_usage_index]
        document = result.get("document")
        if not isinstance(document, dict):
            return
        document_source = document.get("source")
        if isinstance(document_source, dict):
            self._select_document_node_for_source(document_source)
        source_ref = result.get("source_ref")
        if isinstance(source_ref, dict) and str(result.get("kind", "")) != "document":
            self._select_layout_node_for_source(
                source_ref,
                preferred_kind=str(result.get("preferred_kind", "")),
            )

    def _close_condition_usage_window(self) -> None:
        if self.condition_usage_window is not None and self.condition_usage_window.winfo_exists():
            self.condition_usage_window.destroy()
        self.condition_usage_window = None
        self._condition_usage_all_results = []
        self._condition_usage_results = []
        self._condition_usage_index = 0
        self._condition_usage_summary_text = ""
        self._condition_usage_type_filter = ""
        self._condition_usage_sort_column = ""
        self._condition_usage_sort_desc = False

    @staticmethod
    def _truncate_ui_text(value: str, limit: int) -> str:
        text = str(value or "")
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)] + "..."

    def _delete_condition_library_entry(self) -> None:
        if self._active_condition_library_index is None:
            return
        index = self._active_condition_library_index
        if not (0 <= index < len(self._condition_library_entries)):
            return
        del self._condition_library_entries[index]
        self._active_condition_library_index = None
        self._render_condition_library_list()
        self._populate_condition_library_form(None)
        self._persist_condition_library()

    def _apply_condition_library_entry(self) -> None:
        if self._active_condition_library_index is None:
            return
        index = self._active_condition_library_index
        if not (0 <= index < len(self._condition_library_entries)):
            return
        expression = str(self._condition_library_entries[index].get("expression", "")).strip()
        if not expression:
            messagebox.showinfo("Clause Manager", "Selected clause has no expression.")
            return
        self._apply_clause_expression_to_current_target(expression)

    def _insert_selected_clause_name(self) -> None:
        name = ""
        if hasattr(self, "condition_clause_name_var"):
            name = self.condition_clause_name_var.get().strip()
        if not name and self._active_condition_library_index is not None:
            index = self._active_condition_library_index
            if 0 <= index < len(self._condition_library_entries):
                name = str(self._condition_library_entries[index].get("name", "")).strip()
        if not name:
            return
        if self.compose_entry_widget is None or not self.compose_entry_widget.winfo_exists():
            return
        token = name
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", name):
            token = f"CLAUSE{{{name}}}"
        current = self._get_compose_text().strip()
        if not current:
            self._set_compose_text(token)
            return
        separator = " + "
        if current.endswith("(") or current.upper().endswith(" OR"):
            separator = " "
        self._set_compose_text(f"{current}{separator}{token}")

    def _apply_composed_condition(self) -> None:
        if self.compose_entry_widget is None or not self.compose_entry_widget.winfo_exists():
            return
        compose_text = self._get_compose_text().strip()
        if not compose_text:
            messagebox.showinfo("Clause Manager", "Enter a composed expression first.")
            return
        try:
            rendered = self._render_composed_condition(compose_text)
        except ValueError as error:
            messagebox.showerror("Clause Manager", str(error))
            return
        self._apply_clause_expression_to_current_target(rendered)

    def _autofill_compose_from_current_target(self) -> None:
        if self.compose_entry_widget is None or not self.compose_entry_widget.winfo_exists():
            return
        self._update_clause_manager_target_label()
        source_ref, kind = self._infer_conditions_target()
        if not isinstance(source_ref, dict):
            self._set_compose_text("")
            self.condition_compose_status_var.set("No target selected. Select a Document or Layout condition target.")
            return
        raw_condition = str(source_ref.get("Condition", "")).strip()
        if not raw_condition:
            self._set_compose_text("")
            self.condition_compose_status_var.set("Target has no condition.")
            return
        compose_text, exact, unmatched_count = self._compose_expression_from_raw_condition(raw_condition)
        self._set_compose_text(compose_text)
        if exact:
            self.condition_compose_status_var.set("Auto-compose: exact clause match.")
            return
        self.condition_compose_status_var.set(
            f"Auto-compose: partial match ({unmatched_count} raw fragment{'s' if unmatched_count != 1 else ''} as RAW{{...}})."
        )

    def _refresh_condition_composer_for_current_target(self) -> None:
        self._update_clause_manager_target_label()
        if self.condition_library_window is None or not self.condition_library_window.winfo_exists():
            return
        if self.compose_entry_widget is None or not self.compose_entry_widget.winfo_exists():
            return
        self._autofill_compose_from_current_target()

    def _on_condition_library_filter_changed(self, *_args: object) -> None:
        self._render_condition_library_list()

    def _clear_condition_library_filter(self) -> None:
        self.condition_clause_filter_var.set("")

    def _update_clause_manager_target_label(self) -> None:
        source_ref, kind = self._infer_conditions_target()
        if not isinstance(source_ref, dict):
            self.condition_compose_target_var.set("Target: (none selected)")
            return
        target_name = str(source_ref.get("$$Id") or source_ref.get("Name") or source_ref.get("Id") or "(unnamed)")
        kind_label_map = {
            "document": "Document",
            "layout": "Layout",
            "content": "Content",
            "iteration": "Iteration",
            "field": "Field",
            "condition": "Condition Owner",
        }
        kind_label = kind_label_map.get(kind, "Item")
        self.condition_compose_target_var.set(f"Target: {kind_label} {target_name}")

    def _show_compose_help(self) -> None:
        help_text = (
            "Compose Condition Help\n\n"
            "Build conditions with clause names and operators:\n"
            "- AND: use '+' or 'AND'\n"
            "- OR: use 'OR', '||', or '|'\n"
            "- Grouping: use parentheses '(...)'\n"
            "- Raw logic: use RAW{...} for unmatched/advanced fragments\n\n"
            "Embedded clauses inside clause definitions:\n"
            "- Use CLAUSE{name} in a clause expression to reference another clause\n\n"
            "Examples:\n"
            "- is_Tariff_RES + is_English + isNot_Staff\n"
            "- is_English + (isNot_Elderly OR isNot_Staff)\n"
            "- is_English + RAW{@.billPrint.billDetails.currBal > 150}\n\n"
            "Autocomplete:\n"
            "- Type a clause name fragment to get suggestions\n"
            "- Up/Down to navigate, Tab or Enter to accept, Esc to close"
        )
        messagebox.showinfo("Composer Help", help_text)

    def _apply_clause_expression_to_current_target(self, condition_text: str) -> bool:
        source_ref, kind = self._infer_conditions_target()
        if not isinstance(source_ref, dict):
            messagebox.showinfo(
                "Clause Manager",
                "Select a Document or a Layout item with a Condition, then apply again.",
            )
            return False

        normalized = condition_text.strip()
        if normalized == str(source_ref.get("Condition", "")):
            return True

        source_ref["Condition"] = normalized
        if kind == "document":
            self._apply_document_form_change(condition=normalized)
            self._updating_document_form = True
            self._set_text_widget_value(self.document_condition_widget, normalized)
            self._updating_document_form = False
        else:
            self._touch_selected_document_updated()
            self._set_dirty(True)
            self._refresh_layouts_for_active_document()
            preferred = "condition" if kind == "condition" else kind
            self._select_layout_node_for_source(source_ref, preferred_kind=preferred)

        return True

    def _persist_condition_library(self) -> None:
        self._sort_condition_library_entries()
        before = self._payload_clause_library_snapshot()
        self._sync_condition_library_to_payload()
        after = self._payload_clause_library_snapshot()
        if before != after:
            self._set_dirty(True)

        if not self.current_package_name or self.current_package_name == "(none)":
            return
        metadata_file = self._metadata_file_for_package(self.current_package_name)
        payload: dict[str, object] = {}
        if metadata_file.exists():
            try:
                with open(metadata_file, "r", encoding="utf-8") as source:
                    loaded = json.load(source)
                if isinstance(loaded, dict):
                    payload = loaded
            except (OSError, json.JSONDecodeError):
                payload = {}
        serialized_entries = self._serialize_condition_library_entries(self._condition_library_entries)
        payload["clause_library"] = serialized_entries
        payload.pop("condition_library", None)
        payload.pop("condition_library_updated_at", None)
        payload["clause_library_updated_at"] = self._current_timestamp()
        payload["package_name"] = self.current_package_name
        try:
            metadata_file.parent.mkdir(parents=True, exist_ok=True)
            with open(metadata_file, "w", encoding="utf-8") as target:
                json.dump(payload, target, indent=2)
        except OSError:
            return

    def _sync_condition_library_to_payload(self) -> None:
        if self.current_payload is None:
            return
        has_embedded_library = self._embedded_condition_library_entries(self.current_payload) is not None
        serialized_entries = self._serialize_condition_library_entries(self._condition_library_entries)
        self._condition_library_entries = serialized_entries
        if not serialized_entries and not has_embedded_library:
            return
        meta = self.current_payload.get("Meta")
        if not isinstance(meta, dict):
            meta = {}
            self.current_payload["Meta"] = meta
        meta["clause_library"] = copy.deepcopy(serialized_entries)
        meta.pop("condition_library", None)
        meta.pop("condition_library_updated_at", None)
        meta.pop("clause_library_updated_at", None)

    def _payload_clause_library_snapshot(self) -> str:
        entries = self._embedded_condition_library_entries(self.current_payload)
        if entries is None:
            return ""
        return json.dumps(entries, ensure_ascii=False, sort_keys=True)

    def _load_condition_library(self, package_name: str, payload: dict[str, object] | None = None) -> list[dict[str, str]]:
        embedded_entries = self._embedded_condition_library_entries(payload)
        if embedded_entries is not None:
            return self._serialize_condition_library_entries(embedded_entries)

        metadata_file = self._metadata_file_for_package(package_name)
        if not metadata_file.exists():
            return []
        try:
            with open(metadata_file, "r", encoding="utf-8") as source:
                payload = json.load(source)
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, dict):
            return []
        entries = payload.get("clause_library")
        if not isinstance(entries, list):
            return []
        return self._serialize_condition_library_entries(entries)

    @staticmethod
    def _embedded_condition_library_entries(payload: object) -> list[object] | None:
        if not isinstance(payload, dict):
            return None
        meta = payload.get("Meta")
        if not isinstance(meta, dict):
            return None
        entries = meta.get("clause_library")
        if isinstance(entries, list):
            return entries
        atool_meta = meta.get("ATool")
        if isinstance(atool_meta, dict):
            namespaced_entries = atool_meta.get("clause_library")
            if isinstance(namespaced_entries, list):
                return namespaced_entries
        legacy_entries = meta.get("condition_library")
        if isinstance(legacy_entries, list):
            return legacy_entries
        return None

    @classmethod
    def _serialize_condition_library_entries(cls, entries: list[object]) -> list[dict[str, str]]:
        serialized: list[dict[str, str]] = []
        now = cls._current_timestamp()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip()
            if not name:
                continue
            expression = str(entry.get("expression", "")).strip()
            serialized.append(
                {
                    "name": name,
                    "description": str(entry.get("description", "")).strip()
                    or cls._infer_clause_description(
                        expression,
                        name,
                    ),
                    "expression": expression,
                    "updated_at": str(entry.get("updated_at", "")).strip(),
                    "expression_hash": str(entry.get("expression_hash", "")).strip(),
                }
            )
        for item in serialized:
            expression_hash = cls._clause_expression_hash_for_entry(item, serialized)
            stored_hash = str(item.get("expression_hash", "")).strip()
            updated_at = str(item.get("updated_at", "")).strip()
            if not updated_at or (stored_hash and stored_hash != expression_hash):
                updated_at = now
            item["updated_at"] = updated_at
            item["expression_hash"] = expression_hash
        serialized.sort(key=lambda item: str(item.get("name", "")).casefold())
        return serialized

    @classmethod
    def _clause_expression_hash_for_entry(
        cls,
        entry: dict[str, str],
        entries: list[dict[str, str]],
    ) -> str:
        expression = str(entry.get("expression", "")).strip()
        name = str(entry.get("name", "")).strip()
        if name:
            try:
                expression = cls._resolve_clause_expression_by_name_from_entries(entries, name)
            except ValueError:
                pass
        return cls._clause_expression_hash(expression)

    @classmethod
    def _clause_expression_hash(cls, expression: str) -> str:
        canonical = cls._canonical_condition_expression(expression)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    @staticmethod
    def _clause_entry_base_signature(entry: dict[str, object]) -> tuple[str, str, str]:
        return (
            str(entry.get("name", "")).strip(),
            str(entry.get("description", "")).strip(),
            str(entry.get("expression", "")).strip(),
        )

    @staticmethod
    def _current_timestamp() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @classmethod
    def _infer_clause_description(cls, expression: str, clause_name: str) -> str:
        body = cls._strip_outer_parens(cls._extract_condition_body(expression)).strip()
        if not body:
            return cls._humanize_clause_name(clause_name) or "Reusable clause"

        or_parts = cls._split_top_level_operator(body, "||")
        if len(or_parts) > 1:
            return f"Any of {len(or_parts)} conditions are true"
        and_parts = cls._split_top_level_operator(body, "&&")
        if len(and_parts) > 1:
            return f"All of {len(and_parts)} conditions are true"

        empty_match = re.match(r"^(.*?)\s+empty\s+(true|false)\s*$", body, flags=re.IGNORECASE)
        if empty_match:
            subject = cls._describe_condition_subject(empty_match.group(1))
            expect_empty = empty_match.group(2).lower() == "true"
            return f"{subject} is empty" if expect_empty else f"{subject} has a value"

        size_match = cls._find_top_level_word_operator(body, "size")
        if size_match:
            subject = cls._describe_condition_subject(size_match[0])
            rhs = cls._describe_condition_operand(size_match[1])
            return f"{subject} has size {rhs}"

        comparison = cls._find_top_level_comparison(body)
        if comparison is not None:
            lhs, operator, rhs = comparison
            subject = cls._describe_condition_subject(lhs)
            rhs_text = cls._describe_condition_operand(rhs)
            operator_text = {
                "==": "equals",
                "!=": "does not equal",
                ">": "is greater than",
                "<": "is less than",
                ">=": "is greater than or equal to",
                "<=": "is less than or equal to",
            }.get(operator, operator)
            return f"{subject} {operator_text} {rhs_text}"

        lowered = body.lower()
        if ".length(" in lowered or "$.length(" in lowered:
            return "Length-based condition"
        if ".count(" in lowered or "$.count(" in lowered:
            return "Count-based condition"

        return cls._humanize_clause_name(clause_name) or "Parsed condition"

    @classmethod
    def _describe_condition_subject(cls, text: str) -> str:
        raw = str(text or "").strip()
        normalized = raw
        if normalized.startswith("@"):
            normalized = "$" + normalized[1:]
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", normalized)
        subject = tokens[-1] if tokens else raw
        display = cls._humanize_identifier(subject)

        filter_match = re.search(
            r"@\.(\w+)\s*(==|!=)\s*(['\"][^'\"]*['\"])",
            raw,
        )
        if not filter_match:
            return display
        filter_field = cls._humanize_identifier(filter_match.group(1))
        operator_text = "equals" if filter_match.group(2) == "==" else "does not equal"
        filter_value = cls._describe_condition_operand(filter_match.group(3))
        return f"{display} where {filter_field} {operator_text} {filter_value}"

    @classmethod
    def _describe_condition_operand(cls, text: str) -> str:
        raw = str(text or "").strip()
        literal, is_literal = cls._parse_condition_literal(raw)
        if is_literal:
            if isinstance(literal, bool):
                return "true" if literal else "false"
            if literal is None:
                return "null"
            if isinstance(literal, float) and literal.is_integer():
                return str(int(literal))
            if isinstance(literal, str):
                return f"'{literal}'"
            return str(literal)

        if raw.startswith("$") or raw.startswith("@"):
            return cls._describe_condition_subject(raw)
        return raw

    @staticmethod
    def _humanize_clause_name(name: str) -> str:
        cleaned = str(name or "").strip().replace("_", " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def _humanize_identifier(identifier: str) -> str:
        value = str(identifier or "").strip()
        value = value.replace("-", " ").replace("_", " ")
        value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value or "value"

    def _sort_condition_library_entries(self, active_name: str | None = None) -> None:
        if not self._condition_library_entries:
            self._active_condition_library_index = None
            return
        self._condition_library_entries = self._serialize_condition_library_entries(self._condition_library_entries)
        if active_name is None:
            active_name = self._active_condition_library_name()
        if not active_name:
            if self._active_condition_library_index is not None:
                if 0 <= self._active_condition_library_index < len(self._condition_library_entries):
                    return
            self._active_condition_library_index = None
            return
        for idx, item in enumerate(self._condition_library_entries):
            if str(item.get("name", "")).strip() == active_name:
                self._active_condition_library_index = idx
                return
        self._active_condition_library_index = None

    def _active_condition_library_name(self) -> str | None:
        index = self._active_condition_library_index
        if index is None:
            return None
        if not (0 <= index < len(self._condition_library_entries)):
            return None
        name = str(self._condition_library_entries[index].get("name", "")).strip()
        return name or None

    def _refresh_clause_name_dropdown(self) -> None:
        if not hasattr(self, "condition_clause_name_combo"):
            return
        names = [str(item.get("name", "")).strip() for item in self._condition_library_entries]
        names = [name for name in names if name]
        self.condition_clause_name_combo.configure(values=names)
        if not hasattr(self, "condition_clause_name_var"):
            return
        current = self.condition_clause_name_var.get().strip()
        if current in names:
            return
        if self._active_condition_library_index is not None:
            if 0 <= self._active_condition_library_index < len(self._condition_library_entries):
                active_name = str(
                    self._condition_library_entries[self._active_condition_library_index].get("name", "")
                ).strip()
                if active_name in names:
                    self.condition_clause_name_var.set(active_name)
                    return
        self.condition_clause_name_var.set(names[0] if names else "")
        self._update_compose_autocomplete()

    @staticmethod
    def _is_clause_token_char(char: str) -> bool:
        return char.isalnum() or char in {"_", "-"}

    def _get_compose_text(self) -> str:
        if self.compose_entry_widget is None or not self.compose_entry_widget.winfo_exists():
            return ""
        return self.compose_entry_widget.get("1.0", tk.END).rstrip("\n")

    def _set_compose_text(self, text: str) -> None:
        if self.compose_entry_widget is None or not self.compose_entry_widget.winfo_exists():
            return
        self.compose_entry_widget.delete("1.0", tk.END)
        if text:
            self.compose_entry_widget.insert("1.0", text)

    @staticmethod
    def _compose_text_index_to_offset(text: str, index: str) -> int:
        line_str, col_str = str(index).split(".", 1)
        line = max(int(line_str), 1)
        col = max(int(col_str), 0)
        lines = text.split("\n")
        line = min(line, len(lines))
        offset = 0
        for idx in range(line - 1):
            offset += len(lines[idx]) + 1
        offset += min(col, len(lines[line - 1]))
        return max(0, min(offset, len(text)))

    @staticmethod
    def _compose_offset_to_text_index(text: str, offset: int) -> str:
        position = max(0, min(offset, len(text)))
        consumed = 0
        lines = text.split("\n")
        for line_number, line_text in enumerate(lines, start=1):
            line_len = len(line_text)
            if position <= consumed + line_len:
                column = position - consumed
                return f"{line_number}.{column}"
            consumed += line_len + 1
        return f"{len(lines)}.{len(lines[-1]) if lines else 0}"

    def _get_compose_token_bounds(self, text: str, cursor_index: int) -> tuple[int, int, str]:
        cursor = max(0, min(cursor_index, len(text)))
        start = cursor
        while start > 0 and self._is_clause_token_char(text[start - 1]):
            start -= 1
        end = cursor
        while end < len(text) and self._is_clause_token_char(text[end]):
            end += 1
        return start, end, text[start:end]

    def _clause_name_matches(self, token: str) -> list[str]:
        names = [str(item.get("name", "")).strip() for item in self._condition_library_entries]
        names = sorted({name for name in names if name}, key=lambda value: value.casefold())
        if not token:
            return []
        token_key = token.casefold()
        starts = [name for name in names if name.casefold().startswith(token_key)]
        if starts:
            return starts[:20]
        contains = [name for name in names if token_key in name.casefold()]
        return contains[:20]

    def _ensure_compose_autocomplete_popup(self) -> bool:
        if self.compose_entry_widget is None or not self.compose_entry_widget.winfo_exists():
            return False
        if self.compose_autocomplete_popup is not None and self.compose_autocomplete_popup.winfo_exists():
            return True
        parent = self.condition_library_window if self.condition_library_window and self.condition_library_window.winfo_exists() else self.root
        popup = self._create_toplevel(parent)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.transient(parent)
        popup.attributes("-topmost", True)
        listbox = tk.Listbox(popup, height=8, activestyle="dotbox")
        listbox.pack(fill=tk.BOTH, expand=True)
        listbox.bind("<Double-Button-1>", self._on_compose_autocomplete_click)
        self.compose_autocomplete_popup = popup
        self.compose_autocomplete_listbox = listbox
        return True

    def _show_compose_autocomplete(self, matches: list[str]) -> None:
        if not matches or not self._ensure_compose_autocomplete_popup():
            self._hide_compose_autocomplete()
            return
        assert self.compose_entry_widget is not None
        assert self.compose_autocomplete_popup is not None
        assert self.compose_autocomplete_listbox is not None
        self.compose_autocomplete_listbox.delete(0, tk.END)
        for item in matches:
            self.compose_autocomplete_listbox.insert(tk.END, item)
        self.compose_autocomplete_listbox.selection_clear(0, tk.END)
        self.compose_autocomplete_listbox.selection_set(0)
        self.compose_autocomplete_listbox.activate(0)
        self.compose_autocomplete_listbox.see(0)

        entry_x = self.compose_entry_widget.winfo_rootx()
        entry_y = self.compose_entry_widget.winfo_rooty()
        width = max(260, self.compose_entry_widget.winfo_width())
        row_count = min(8, max(1, len(matches)))
        height = 26 + row_count * 20
        self.compose_autocomplete_popup.geometry(
            f"{width}x{height}+{entry_x}+{entry_y + self.compose_entry_widget.winfo_height()}"
        )
        self.compose_autocomplete_popup.deiconify()
        self.compose_autocomplete_popup.lift()

    def _hide_compose_autocomplete(self) -> None:
        if self.compose_autocomplete_popup is None or not self.compose_autocomplete_popup.winfo_exists():
            return
        self.compose_autocomplete_popup.withdraw()

    def _compose_autocomplete_visible(self) -> bool:
        if self.compose_autocomplete_popup is None or not self.compose_autocomplete_popup.winfo_exists():
            return False
        return self.compose_autocomplete_popup.state() != "withdrawn"

    def _selected_autocomplete_clause(self) -> str:
        if self.compose_autocomplete_listbox is None or not self.compose_autocomplete_listbox.winfo_exists():
            return ""
        selected = self.compose_autocomplete_listbox.curselection()
        if not selected:
            if self.compose_autocomplete_listbox.size() == 0:
                return ""
            self.compose_autocomplete_listbox.selection_set(0)
            return str(self.compose_autocomplete_listbox.get(0))
        return str(self.compose_autocomplete_listbox.get(selected[0]))

    def _accept_compose_autocomplete(self) -> bool:
        if self.compose_entry_widget is None or not self.compose_entry_widget.winfo_exists():
            return False
        clause_name = self._selected_autocomplete_clause()
        if not clause_name:
            return False
        current_text = self._get_compose_text()
        cursor = self._compose_text_index_to_offset(current_text, self.compose_entry_widget.index(tk.INSERT))
        start, end, _token = self._get_compose_token_bounds(current_text, cursor)
        new_text = f"{current_text[:start]}{clause_name}{current_text[end:]}"
        self._set_compose_text(new_text)
        new_cursor = start + len(clause_name)
        self.compose_entry_widget.mark_set(tk.INSERT, self._compose_offset_to_text_index(new_text, new_cursor))
        self._hide_compose_autocomplete()
        return True

    def _update_compose_autocomplete(self) -> None:
        if self.compose_entry_widget is None or not self.compose_entry_widget.winfo_exists():
            return
        text = self._get_compose_text()
        cursor = self._compose_text_index_to_offset(text, self.compose_entry_widget.index(tk.INSERT))
        _start, _end, token = self._get_compose_token_bounds(text, cursor)
        if not token:
            self._hide_compose_autocomplete()
            return
        matches = self._clause_name_matches(token)
        exact = any(match.casefold() == token.casefold() for match in matches)
        if exact and len(matches) == 1:
            self._hide_compose_autocomplete()
            return
        self._show_compose_autocomplete(matches)

    def _on_compose_autocomplete_click(self, _event: tk.Event) -> str:
        self._accept_compose_autocomplete()
        if self.compose_entry_widget is not None and self.compose_entry_widget.winfo_exists():
            self.compose_entry_widget.focus_set()
        return "break"

    def _on_compose_entry_keyrelease(self, event: tk.Event) -> None:
        if event.keysym in {"Up", "Down", "Return", "Tab", "Escape"}:
            return
        self._update_compose_autocomplete()

    def _on_compose_entry_down(self, _event: tk.Event) -> str:
        if not self._compose_autocomplete_visible():
            self._update_compose_autocomplete()
            return "break"
        if self.compose_autocomplete_listbox is None or not self.compose_autocomplete_listbox.winfo_exists():
            return "break"
        size = self.compose_autocomplete_listbox.size()
        if size <= 0:
            return "break"
        selected = self.compose_autocomplete_listbox.curselection()
        index = selected[0] if selected else 0
        next_index = min(index + 1, size - 1)
        self.compose_autocomplete_listbox.selection_clear(0, tk.END)
        self.compose_autocomplete_listbox.selection_set(next_index)
        self.compose_autocomplete_listbox.activate(next_index)
        self.compose_autocomplete_listbox.see(next_index)
        return "break"

    def _on_compose_entry_up(self, _event: tk.Event) -> str:
        if not self._compose_autocomplete_visible():
            return "break"
        if self.compose_autocomplete_listbox is None or not self.compose_autocomplete_listbox.winfo_exists():
            return "break"
        size = self.compose_autocomplete_listbox.size()
        if size <= 0:
            return "break"
        selected = self.compose_autocomplete_listbox.curselection()
        index = selected[0] if selected else 0
        next_index = max(index - 1, 0)
        self.compose_autocomplete_listbox.selection_clear(0, tk.END)
        self.compose_autocomplete_listbox.selection_set(next_index)
        self.compose_autocomplete_listbox.activate(next_index)
        self.compose_autocomplete_listbox.see(next_index)
        return "break"

    def _on_compose_entry_tab(self, _event: tk.Event) -> str:
        if self._compose_autocomplete_visible() and self._accept_compose_autocomplete():
            return "break"
        return "break"

    def _on_compose_entry_return(self, _event: tk.Event) -> str:
        if self._compose_autocomplete_visible() and self._accept_compose_autocomplete():
            return "break"
        return "break"

    def _on_compose_entry_escape(self, _event: tk.Event) -> str:
        self._hide_compose_autocomplete()
        return "break"

    def _on_compose_entry_focus_out(self, _event: tk.Event) -> None:
        self.root.after(150, self._hide_compose_autocomplete)

    def _render_composed_condition(self, compose_text: str) -> str:
        return self._render_composed_condition_with_entries(compose_text, self._condition_library_entries)

    def _render_composed_condition_with_entries(
        self,
        compose_text: str,
        entries: list[dict[str, str]],
    ) -> str:
        text = str(compose_text or "").strip()
        if not text:
            raise ValueError("Composed expression is empty.")
        tokens = self._tokenize_clause_expression(text)
        if not tokens:
            raise ValueError("Composed expression is empty.")
        position = 0

        def parse_or() -> tuple[str, object]:
            nonlocal position
            parts: list[tuple[str, object]] = [parse_and()]
            while position < len(tokens) and tokens[position][0] == "OR":
                position += 1
                parts.append(parse_and())
            if len(parts) == 1:
                return parts[0]
            return ("OR", parts)

        def parse_and() -> tuple[str, object]:
            nonlocal position
            parts: list[tuple[str, object]] = [parse_term()]
            while position < len(tokens) and tokens[position][0] == "AND":
                position += 1
                parts.append(parse_term())
            if len(parts) == 1:
                return parts[0]
            return ("AND", parts)

        def parse_term() -> tuple[str, object]:
            nonlocal position
            if position >= len(tokens):
                raise ValueError("Unexpected end of expression.")
            token_type, token_value = tokens[position]
            if token_type == "LPAREN":
                position += 1
                inner = parse_or()
                if position >= len(tokens) or tokens[position][0] != "RPAREN":
                    raise ValueError("Missing closing parenthesis in composed expression.")
                position += 1
                return inner
            if token_type == "RAW":
                position += 1
                raw_body = self._extract_condition_body(token_value).strip()
                if not raw_body:
                    raise ValueError("RAW{...} token cannot be empty.")
                return ("ATOM", raw_body)
            if token_type != "NAME":
                raise ValueError(f"Unexpected token '{token_value}'.")
            position += 1
            clause_expression = self._resolve_clause_expression_by_name_from_entries(entries, token_value)
            clause_expression = self._extract_condition_body(clause_expression)
            if not clause_expression:
                raise ValueError(f"Clause '{token_value}' has no expression.")
            return ("ATOM", clause_expression)

        def needs_atom_parens(expr: str) -> bool:
            stripped = self._strip_outer_parens(expr)
            return len(self._split_top_level_operator(stripped, "&&")) > 1 or len(
                self._split_top_level_operator(stripped, "||")
            ) > 1

        def render(node: tuple[str, object], parent_precedence: int = 0) -> str:
            kind, value = node
            if kind == "ATOM":
                atom = str(value).strip()
                if needs_atom_parens(atom):
                    return f"({atom})"
                return atom
            if kind == "AND":
                precedence = 2
                assert isinstance(value, list)
                text_value = " && ".join(render(child, precedence) for child in value)
                if precedence < parent_precedence:
                    return f"({text_value})"
                return text_value
            if kind == "OR":
                precedence = 1
                assert isinstance(value, list)
                text_value = " || ".join(render(child, precedence) for child in value)
                if precedence < parent_precedence:
                    return f"({text_value})"
                return text_value
            raise ValueError("Unexpected compose parser node type.")

        parsed_tree = parse_or()
        if position != len(tokens):
            raise ValueError("Unexpected trailing tokens in composed expression.")
        rendered_body = render(parsed_tree)
        return f"$[?({rendered_body})]"

    def _compose_expression_from_raw_condition(self, condition_text: str) -> tuple[str, bool, int]:
        return self._compose_expression_from_raw_condition_with_entries(condition_text, self._condition_library_entries)

    def _compose_expression_from_raw_condition_with_entries(
        self,
        condition_text: str,
        entries: list[dict[str, str]],
    ) -> tuple[str, bool, int]:
        raw_body = self._strip_outer_parens(self._extract_condition_body(condition_text)).strip()
        if not raw_body:
            return "", True, 0
        clause_lookup = self._build_clause_expression_lookup_with_entries(entries)
        composed, exact, unmatched = self._compose_clause_expression_recursive(raw_body, clause_lookup)
        return composed, exact, unmatched

    def _build_clause_expression_lookup(self) -> dict[str, str]:
        return self._build_clause_expression_lookup_with_entries(self._condition_library_entries)

    def _build_clause_expression_lookup_with_entries(self, entries: list[dict[str, str]]) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for item in entries:
            name = str(item.get("name", "")).strip()
            expression = str(item.get("expression", "")).strip()
            if not name or not expression:
                continue
            try:
                resolved_expression = self._resolve_clause_expression_by_name_from_entries(entries, name)
            except ValueError:
                resolved_expression = expression
            key = self._canonical_condition_expression(resolved_expression)
            if not key:
                continue
            if key not in lookup:
                lookup[key] = name
        return lookup

    @staticmethod
    def _extract_embedded_clause_references(expression: str) -> list[str]:
        matches = re.findall(r"CLAUSE\{([^}]+)\}", str(expression or ""), flags=re.IGNORECASE)
        references: list[str] = []
        for match in matches:
            name = str(match).strip()
            if name:
                references.append(name)
        return references

    def _get_clause_expression_by_name(self, clause_name: str) -> str:
        return self._get_clause_expression_by_name_from_entries(self._condition_library_entries, clause_name)

    @staticmethod
    def _get_clause_expression_by_name_from_entries(entries: list[dict[str, str]], clause_name: str) -> str:
        target = str(clause_name or "").strip()
        if not target:
            return ""
        for item in entries:
            if str(item.get("name", "")).strip() == target:
                return str(item.get("expression", "")).strip()
        return ""

    def _resolve_clause_expression_by_name(
        self,
        clause_name: str,
        *,
        stack: tuple[str, ...] = (),
    ) -> str:
        return self._resolve_clause_expression_by_name_from_entries(
            self._condition_library_entries,
            clause_name,
            stack=stack,
        )

    @classmethod
    def _resolve_clause_expression_by_name_from_entries(
        cls,
        entries: list[dict[str, str]],
        clause_name: str,
        *,
        stack: tuple[str, ...] = (),
    ) -> str:
        name = str(clause_name or "").strip()
        if not name:
            raise ValueError("Embedded clause name is empty.")
        if name in stack:
            chain = " -> ".join((*stack, name))
            raise ValueError(f"Embedded clause cycle detected: {chain}")
        expression = cls._get_clause_expression_by_name_from_entries(entries, name)
        if not expression:
            raise ValueError(f"Unknown clause '{name}'.")
        return cls._resolve_clause_expression_text_from_entries(entries, expression, stack=(*stack, name))

    def _resolve_clause_expression_text(
        self,
        expression: str,
        *,
        stack: tuple[str, ...] = (),
    ) -> str:
        return self._resolve_clause_expression_text_from_entries(
            self._condition_library_entries,
            expression,
            stack=stack,
        )

    @classmethod
    def _resolve_clause_expression_text_from_entries(
        cls,
        entries: list[dict[str, str]],
        expression: str,
        *,
        stack: tuple[str, ...] = (),
    ) -> str:
        text = str(expression or "").strip()
        if not text:
            return ""
        if not cls._extract_embedded_clause_references(text):
            return text

        def replace_match(match: re.Match[str]) -> str:
            ref_name = str(match.group(1) or "").strip()
            if not ref_name:
                raise ValueError("Embedded clause name is empty.")
            resolved = cls._resolve_clause_expression_by_name_from_entries(entries, ref_name, stack=stack)
            resolved_body = cls._extract_condition_body(resolved).strip()
            if not resolved_body:
                raise ValueError(f"Embedded clause '{ref_name}' has no expression.")
            return f"({resolved_body})"

        return re.sub(r"CLAUSE\{([^}]+)\}", replace_match, text, flags=re.IGNORECASE)

    def _compose_clause_expression_recursive(
        self,
        expression: str,
        clause_lookup: dict[str, str],
    ) -> tuple[str, bool, int]:
        expr = self._strip_outer_parens(str(expression or "").strip())
        if not expr:
            return "", True, 0
        key = self._canonical_condition_expression(expr)
        if key in clause_lookup:
            return clause_lookup[key], True, 0

        or_parts = self._split_top_level_operator(expr, "||")
        if len(or_parts) > 1:
            parts: list[str] = []
            exact_all = True
            unmatched_total = 0
            for part in or_parts:
                rendered, exact, unmatched = self._compose_clause_expression_recursive(part, clause_lookup)
                parts.append(f"({rendered})" if self._compose_needs_parens(rendered) else rendered)
                exact_all = exact_all and exact
                unmatched_total += unmatched
            return " OR ".join(parts), exact_all, unmatched_total

        and_parts = self._split_top_level_operator(expr, "&&")
        if len(and_parts) > 1:
            parts = []
            exact_all = True
            unmatched_total = 0
            for part in and_parts:
                rendered, exact, unmatched = self._compose_clause_expression_recursive(part, clause_lookup)
                parts.append(f"({rendered})" if self._compose_needs_parens(rendered) else rendered)
                exact_all = exact_all and exact
                unmatched_total += unmatched
            return " + ".join(parts), exact_all, unmatched_total

        escaped = expr.replace("}", "\\}")
        return f"RAW{{{escaped}}}", False, 1

    @staticmethod
    def _compose_needs_parens(text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        if value.startswith("RAW{") and value.endswith("}"):
            return False
        return (" + " in value) or (" OR " in value)

    @staticmethod
    def _canonical_condition_expression(expression: str) -> str:
        text = AToolApp._strip_outer_parens(AToolApp._extract_condition_body(str(expression or ""))).strip()
        if not text:
            return ""
        chars: list[str] = []
        in_quote = ""
        escaped = False
        for ch in text:
            if in_quote:
                chars.append(ch)
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == in_quote:
                    in_quote = ""
                continue
            if ch in {"'", '"'}:
                in_quote = ch
                chars.append(ch)
                continue
            if ch.isspace():
                continue
            chars.append(ch)
        canonical = "".join(chars)
        if canonical.startswith("$."):
            canonical = "@." + canonical[2:]
        return canonical

    @staticmethod
    def _tokenize_clause_expression(text: str) -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = []
        index = 0
        while index < len(text):
            char = text[index]
            if char.isspace():
                index += 1
                continue
            if char == "(":
                tokens.append(("LPAREN", char))
                index += 1
                continue
            if char == ")":
                tokens.append(("RPAREN", char))
                index += 1
                continue
            if text.startswith("CLAUSE{", index):
                start = index + 7
                end = text.find("}", start)
                if end < 0:
                    raise ValueError("Unterminated CLAUSE{...} token.")
                clause_name = text[start:end].strip()
                if not clause_name:
                    raise ValueError("CLAUSE{...} token cannot be empty.")
                tokens.append(("NAME", clause_name))
                index = end + 1
                continue
            if text.startswith("RAW{", index):
                start = index + 4
                cursor = start
                depth = 1
                quote = ""
                escaped = False
                while cursor < len(text):
                    ch = text[cursor]
                    if quote:
                        if escaped:
                            escaped = False
                        elif ch == "\\":
                            escaped = True
                        elif ch == quote:
                            quote = ""
                        cursor += 1
                        continue
                    if ch in {"'", '"'}:
                        quote = ch
                        cursor += 1
                        continue
                    if ch == "{":
                        depth += 1
                        cursor += 1
                        continue
                    if ch == "}":
                        depth -= 1
                        if depth == 0:
                            payload = text[start:cursor].strip().replace("\\}", "}")
                            if not payload:
                                raise ValueError("RAW{...} token cannot be empty.")
                            tokens.append(("RAW", payload))
                            cursor += 1
                            index = cursor
                            break
                        cursor += 1
                        continue
                    cursor += 1
                else:
                    raise ValueError("Unterminated RAW{...} token.")
                continue
            if text.startswith("&&", index):
                tokens.append(("AND", "&&"))
                index += 2
                continue
            if text.startswith("||", index):
                tokens.append(("OR", "||"))
                index += 2
                continue
            if char == "+":
                tokens.append(("AND", "+"))
                index += 1
                continue
            if char == "|":
                tokens.append(("OR", "|"))
                index += 1
                continue
            and_match = re.match(r"AND\b", text[index:], flags=re.IGNORECASE)
            if and_match:
                tokens.append(("AND", and_match.group(0)))
                index += len(and_match.group(0))
                continue
            or_match = re.match(r"OR\b", text[index:], flags=re.IGNORECASE)
            if or_match:
                tokens.append(("OR", or_match.group(0)))
                index += len(or_match.group(0))
                continue
            name_match = re.match(r"[A-Za-z_][A-Za-z0-9_-]*", text[index:])
            if name_match:
                name = name_match.group(0)
                tokens.append(("NAME", name))
                index += len(name)
                continue
            raise ValueError(f"Unsupported token near '{text[index:index + 20]}'.")
        return tokens

    def open_conditions_tool_from_document(self) -> None:
        document_ref = self._get_selected_document_ref()
        if document_ref is None:
            return
        source_ref = document_ref.get("source")
        if not isinstance(source_ref, dict):
            return
        self._show_condition_library_window()

    def open_conditions_tool_from_layout(self) -> None:
        if not self._active_layout_node_id:
            return
        details = self._layout_node_details.get(self._active_layout_node_id)
        if not details:
            return
        source_ref = details.get("source_ref")
        if not isinstance(source_ref, dict):
            return
        self._show_condition_library_window()

    def _infer_conditions_target(self) -> tuple[dict[str, object] | None, str]:
        if self._active_layout_node_id:
            details = self._layout_node_details.get(self._active_layout_node_id)
            if details:
                source_ref = details.get("source_ref")
                if isinstance(source_ref, dict):
                    return source_ref, str(details.get("node_kind", ""))
        document_ref = self._get_selected_document_ref()
        if document_ref is not None:
            source_ref = document_ref.get("source")
            if isinstance(source_ref, dict):
                return source_ref, "document"
        return None, ""

    def _load_document_view_mode(self) -> str:
        state = self._read_app_state()
        saved_mode = state.get("documents_view_mode")
        if saved_mode in {"hierarchy", "flat"}:
            return str(saved_mode)
        return "hierarchy" if self._get_document_collapse_setting() else "flat"

    def _set_document_view_mode(self, mode: str) -> None:
        if mode not in {"hierarchy", "flat"}:
            return
        self.document_view_mode = mode
        self._update_document_view_buttons()
        self._update_app_state({"documents_view_mode": mode})
        self._render_documents_tree()

    def _toggle_document_view_mode(self) -> None:
        next_mode = "flat" if self.document_view_mode == "hierarchy" else "hierarchy"
        self._set_document_view_mode(next_mode)

    def _update_document_view_buttons(self) -> None:
        if hasattr(self, "documents_view_toggle_button"):
            next_mode = "Flat" if self.document_view_mode == "hierarchy" else "Hierarchy"
            self.documents_view_toggle_button.config(text=f"View ({next_mode})")
        self._schedule_documents_controls_layout()

    def _on_documents_controls_configure(self, _event: tk.Event) -> None:
        self._schedule_documents_controls_layout()

    def _schedule_documents_controls_layout(self) -> None:
        if self._document_controls_layout_job:
            self.root.after_cancel(self._document_controls_layout_job)
        self._document_controls_layout_job = self.root.after(1, self._relayout_documents_controls)

    def _relayout_documents_controls(self) -> None:
        self._document_controls_layout_job = None
        if not hasattr(self, "documents_controls_frame") or not hasattr(self, "_document_toolbar_buttons"):
            return

        controls = self.documents_controls_frame
        frame_width = controls.winfo_width()
        if frame_width <= 1:
            return

        buttons = list(self._document_toolbar_buttons)
        if self.current_data_payload is None and hasattr(self, "document_mapping_filter_button"):
            buttons = [
                button
                for button in buttons
                if button is not self.document_mapping_filter_button
            ]
        if self.document_view_mode != "flat":
            buttons = [
                button
                for button in buttons
                if button
                not in {
                    self.move_document_top_button,
                    self.move_document_up_button,
                    self.move_document_down_button,
                    self.move_document_bottom_button,
                    self.auto_move_document_button,
                }
            ]

        signature = (
            self.document_view_mode,
            frame_width,
            tuple((button.winfo_name(), str(button.cget("text"))) for button in buttons),
        )
        if signature == self._document_controls_layout_signature:
            return
        self._document_controls_layout_signature = signature

        for button in self._document_toolbar_buttons:
            button.grid_forget()

        row = 0
        column = 0
        used_width = 0
        gap = 6

        for button in buttons:
            button.update_idletasks()
            button_width = button.winfo_reqwidth()
            projected = button_width if used_width == 0 else used_width + gap + button_width
            if used_width > 0 and projected > frame_width:
                row += 1
                column = 0
                used_width = 0
            button.grid(row=row, column=column, sticky="w", padx=(0, gap), pady=(0, 4))
            used_width = button_width if used_width == 0 else used_width + gap + button_width
            column += 1

    def _attach_tooltip(self, widget: tk.Widget, text: str) -> None:
        if not text:
            return
        widget.bind("<Enter>", lambda event, t=text: self._show_tooltip(event, t), add="+")
        widget.bind("<Leave>", lambda _event: self._hide_tooltip(), add="+")
        widget.bind("<ButtonPress>", lambda _event: self._hide_tooltip(), add="+")
        widget.bind("<FocusOut>", lambda _event: self._hide_tooltip(), add="+")

    def _show_tooltip(self, event: tk.Event, text: str) -> None:
        self._hide_tooltip()
        tip = self._create_toplevel(self.root)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        label = tk.Label(
            tip,
            text=text,
            background="#fffde8",
            relief="solid",
            borderwidth=1,
            padx=6,
            pady=3,
            justify=tk.LEFT,
        )
        label.pack()
        x_pos = event.x_root + 14
        y_pos = event.y_root + 12
        tip.wm_geometry(f"+{x_pos}+{y_pos}")
        self._tooltip_window = tip

    def _hide_tooltip(self) -> None:
        if self._tooltip_window is None:
            return
        if self._tooltip_window.winfo_exists():
            self._tooltip_window.destroy()
        self._tooltip_window = None

    def _run_document_move_button_command(self, button: ttk.Button, command: object) -> None:
        try:
            if callable(command):
                command()
        finally:
            self.root.after_idle(lambda selected_button=button: self._release_document_move_button(selected_button))

    @staticmethod
    def _release_document_move_button(button: ttk.Button) -> None:
        try:
            if button.winfo_exists():
                button.state(["!pressed", "active"])
        except tk.TclError:
            return

    def _update_mapping_controls(self) -> None:
        self._update_document_triggered_visibility()
        if hasattr(self, "clear_mapping_button"):
            if self._mapping_dialog_in_progress:
                self.clear_mapping_button.config(text="Opening...", command=self.map_data_file, state=tk.DISABLED)
                self._relayout_documents_controls()
                return
            has_mapped_file = self.current_data_file_path is not None
            text = "Clear Map" if has_mapped_file else "Map"
            command = self.clear_mapping if has_mapped_file else self._toggle_mapping_file
            enabled = has_mapped_file or self.current_payload is not None
            state = tk.NORMAL if enabled else tk.DISABLED
            self.clear_mapping_button.config(text=text, command=command, state=state)
            self._relayout_documents_controls()
        if hasattr(self, "document_mapping_filter_button"):
            label = "Show All" if self._show_triggered_documents_only else "Show Triggered"
            self.document_mapping_filter_button.config(text=label, state=tk.NORMAL)
            self._relayout_documents_controls()

    def _toggle_triggered_document_filter(self) -> None:
        if self.current_data_payload is None:
            return
        self._show_triggered_documents_only = not self._show_triggered_documents_only
        self._update_mapping_controls()
        self._render_documents_tree()

    def _update_document_context_buttons(self) -> None:
        selected_doc = self._get_selected_document_ref()
        document_state = tk.NORMAL if self.current_payload is not None else tk.DISABLED
        selected_state = tk.NORMAL if selected_doc is not None else tk.DISABLED
        if hasattr(self, "add_document_button"):
            self.add_document_button.config(state=document_state)
        if hasattr(self, "add_layout_button"):
            self.add_layout_button.config(state=selected_state)
        if hasattr(self, "move_document_top_button"):
            self.move_document_top_button.config(state=selected_state)
        if hasattr(self, "move_document_up_button"):
            self.move_document_up_button.config(state=selected_state)
        if hasattr(self, "move_document_down_button"):
            self.move_document_down_button.config(state=selected_state)
        if hasattr(self, "move_document_bottom_button"):
            self.move_document_bottom_button.config(state=selected_state)
        if hasattr(self, "auto_move_document_button"):
            self.auto_move_document_button.config(state=selected_state)
        if hasattr(self, "generate_sample_input_button"):
            self.generate_sample_input_button.config(state=selected_state)

    def _update_layout_context_buttons(self) -> None:
        node_kind = ""
        if self._active_layout_node_id:
            details = self._layout_node_details.get(self._active_layout_node_id, {})
            node_kind = str(details.get("node_kind", ""))
        add_content_state = tk.NORMAL if node_kind == "layout" else tk.DISABLED
        move_state = tk.NORMAL if node_kind == "layout" else tk.DISABLED
        add_iteration_state = tk.NORMAL if node_kind == "content" else tk.DISABLED
        add_field_state = tk.NORMAL if node_kind == "iteration" else tk.DISABLED
        remove_state = tk.NORMAL if node_kind in {"layout", "content", "iteration", "field", "condition"} else tk.DISABLED
        if hasattr(self, "add_content_button"):
            self.add_content_button.config(state=add_content_state)
        if hasattr(self, "move_layout_up_button"):
            self.move_layout_up_button.config(state=move_state)
        if hasattr(self, "move_layout_down_button"):
            self.move_layout_down_button.config(state=move_state)
        if hasattr(self, "add_iteration_button"):
            self.add_iteration_button.config(state=add_iteration_state)
        if hasattr(self, "add_iteration_field_button"):
            self.add_iteration_field_button.config(state=add_field_state)
        if hasattr(self, "remove_layout_item_button"):
            self.remove_layout_item_button.config(state=remove_state)
        if hasattr(self, "layout_condition_tool_button"):
            condition_state = tk.NORMAL if node_kind in {"layout", "content", "field", "condition"} else tk.DISABLED
            self.layout_condition_tool_button.config(state=condition_state)

    def _open_user_settings_dialog(self) -> None:
        dialog = self._create_toplevel(self.root)
        dialog.title("User Settings")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.grab_set()

        container = ttk.Frame(dialog, padding=14)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)

        group = ttk.LabelFrame(container, text="Document Display", padding=10)
        group.grid(row=0, column=0, sticky="ew")

        collapse_var = tk.BooleanVar(value=self._get_document_collapse_setting())
        collapse_check = ttk.Checkbutton(
            group,
            text="Collapse",
            variable=collapse_var,
        )
        collapse_check.grid(row=0, column=0, sticky="w")

        diagnostics_group = ttk.LabelFrame(container, text="Diagnostics", padding=10)
        diagnostics_group.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        debug_var = tk.BooleanVar(value=self._is_debug_logging_enabled())
        debug_check = ttk.Checkbutton(
            diagnostics_group,
            text="Debug Logging (console)",
            variable=debug_var,
        )
        debug_check.grid(row=0, column=0, sticky="w")

        occs_group = ttk.LabelFrame(container, text="OCCS CLI", padding=10)
        occs_group.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        occs_group.columnconfigure(1, weight=1)

        cli_path_var = tk.StringVar(value=self._get_occs_cli_path())
        work_dir_var = tk.StringVar(value=self._get_occs_work_dir())
        session_alias_var = tk.StringVar(value=self._get_occs_session_alias())
        shared_workspace_var = tk.StringVar(value=self._get_occs_shared_workspace_dir())
        occs_user_name_var = tk.StringVar(value=self._get_occs_user_name())
        preview_program_vars = {
            render_type: tk.StringVar(value=self._get_occs_preview_open_program(render_type))
            for render_type in self.OCCS_PREVIEW_RENDER_TYPES
        }

        ttk.Label(occs_group, text="CLI Path:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        cli_path_entry = ttk.Entry(occs_group, textvariable=cli_path_var, width=54)
        cli_path_entry.grid(row=0, column=1, sticky="ew")

        def _browse_cli_path() -> None:
            current_path = cli_path_var.get().strip()
            initial_dir = os.path.dirname(current_path) if current_path else str(Path.home())
            selected_path = filedialog.askopenfilename(
                parent=dialog,
                title="Select OCCS CLI",
                initialdir=initial_dir or None,
                filetypes=[
                    ("OCCS CLI", "occs.js"),
                    ("JavaScript Files", "*.js"),
                    ("All Files", "*.*"),
                ],
            )
            if selected_path:
                cli_path_var.set(selected_path)

        ttk.Button(occs_group, text="Browse...", command=_browse_cli_path).grid(
            row=0,
            column=2,
            sticky="e",
            padx=(6, 0),
        )

        ttk.Label(occs_group, text="Local Package Folder:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        work_dir_entry = ttk.Entry(occs_group, textvariable=work_dir_var, width=54)
        work_dir_entry.grid(row=1, column=1, sticky="ew", pady=(8, 0))

        def _browse_work_dir() -> None:
            current_path = work_dir_var.get().strip()
            initial_dir = current_path if current_path else str(Path.home())
            selected_dir = filedialog.askdirectory(
                parent=dialog,
                title="Select Local Package Folder",
                initialdir=initial_dir or None,
            )
            if selected_dir:
                work_dir_var.set(selected_dir)

        ttk.Button(occs_group, text="Browse...", command=_browse_work_dir).grid(
            row=1,
            column=2,
            sticky="e",
            padx=(6, 0),
            pady=(8, 0),
        )

        ttk.Label(occs_group, text="Session Alias:").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        session_alias_entry = ttk.Entry(occs_group, textvariable=session_alias_var, width=54)
        session_alias_entry.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(8, 0))

        ttk.Label(occs_group, text="Shared Package Folder:").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        shared_workspace_entry = ttk.Entry(occs_group, textvariable=shared_workspace_var, width=54)
        shared_workspace_entry.grid(row=3, column=1, sticky="ew", pady=(8, 0))

        def _browse_shared_workspace() -> None:
            current_path = shared_workspace_var.get().strip()
            initial_dir = current_path if current_path else str(Path.home())
            selected_dir = filedialog.askdirectory(
                parent=dialog,
                title="Select Shared Package Folder",
                initialdir=initial_dir or None,
            )
            if selected_dir:
                shared_workspace_var.set(selected_dir)

        ttk.Button(occs_group, text="Browse...", command=_browse_shared_workspace).grid(
            row=3,
            column=2,
            sticky="e",
            padx=(6, 0),
            pady=(8, 0),
        )

        ttk.Label(occs_group, text="User Name:").grid(row=4, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        user_name_entry = ttk.Entry(occs_group, textvariable=occs_user_name_var, width=54)
        user_name_entry.grid(row=4, column=1, columnspan=2, sticky="ew", pady=(8, 0))

        preview_group = ttk.LabelFrame(container, text="Preview Open Programs", padding=10)
        preview_group.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        preview_group.columnconfigure(1, weight=1)

        def _browse_preview_program(render_type: str) -> None:
            current_path = preview_program_vars[render_type].get().strip()
            initial_dir = os.path.dirname(current_path) if current_path else str(Path.home())
            selected_path = filedialog.askopenfilename(
                parent=dialog,
                title=f"Select {render_type} Open Program",
                initialdir=initial_dir or None,
                filetypes=[
                    ("Applications", "*.app"),
                    ("All Files", "*.*"),
                ],
            )
            if selected_path:
                preview_program_vars[render_type].set(selected_path)

        for row_index, render_type in enumerate(self.OCCS_PREVIEW_RENDER_TYPES):
            ttk.Label(preview_group, text=f"{render_type}:").grid(
                row=row_index,
                column=0,
                sticky="w",
                padx=(0, 6),
                pady=(0 if row_index == 0 else 8, 0),
            )
            ttk.Entry(preview_group, textvariable=preview_program_vars[render_type], width=54).grid(
                row=row_index,
                column=1,
                sticky="ew",
                pady=(0 if row_index == 0 else 8, 0),
            )
            ttk.Button(
                preview_group,
                text="Browse...",
                command=lambda selected_render_type=render_type: _browse_preview_program(selected_render_type),
            ).grid(
                row=row_index,
                column=2,
                sticky="e",
                padx=(6, 0),
                pady=(0 if row_index == 0 else 8, 0),
            )

        settings_path = self._settings_file()
        path_label = ttk.Label(
            container,
            text=f"Settings file: {settings_path}",
            wraplength=520,
            justify=tk.LEFT,
        )
        path_label.grid(row=4, column=0, sticky="w", pady=(10, 0))

        buttons = ttk.Frame(container)
        buttons.grid(row=5, column=0, sticky="e", pady=(14, 0))

        cancel_btn = ttk.Button(buttons, text="Cancel", command=dialog.destroy)
        cancel_btn.grid(row=0, column=0, padx=(0, 8))

        def _save_settings() -> None:
            self._set_document_collapse_enabled(bool(collapse_var.get()))
            self._set_debug_logging_enabled(bool(debug_var.get()))
            self._set_occs_cli_path(cli_path_var.get())
            self._set_occs_work_dir(work_dir_var.get())
            self._set_occs_session_alias(session_alias_var.get())
            self._set_occs_shared_workspace_dir(shared_workspace_var.get())
            self._set_occs_user_name(occs_user_name_var.get())
            for render_type, variable in preview_program_vars.items():
                self._set_occs_preview_open_program(render_type, variable.get())
            self._save_user_settings()
            preferred_mode = "hierarchy" if collapse_var.get() else "flat"
            self._set_document_view_mode(preferred_mode)
            self._debug_log("Debug logging enabled.")
            dialog.destroy()

        save_btn = ttk.Button(buttons, text="Save", command=_save_settings)
        save_btn.grid(row=0, column=1)

        dialog.update_idletasks()
        x_pos = self.root.winfo_x() + max((self.root.winfo_width() - dialog.winfo_width()) // 2, 0)
        y_pos = self.root.winfo_y() + max((self.root.winfo_height() - dialog.winfo_height()) // 2, 0)
        dialog.geometry(f"+{x_pos}+{y_pos}")

    def _set_document_collapse_enabled(self, enabled: bool) -> None:
        section = self.user_settings.setdefault("document_display", {})
        if not isinstance(section, dict):
            section = {}
            self.user_settings["document_display"] = section
        section["collapse"] = enabled

    def _set_debug_logging_enabled(self, enabled: bool) -> None:
        section = self.user_settings.setdefault("diagnostics", {})
        if not isinstance(section, dict):
            section = {}
            self.user_settings["diagnostics"] = section
        section["debug_logging"] = enabled

    def _set_occs_cli_path(self, cli_path: str) -> None:
        section = self._occs_settings_section()
        section["cli_path"] = str(cli_path or "").strip()

    def _set_occs_work_dir(self, work_dir: str) -> None:
        section = self._occs_settings_section()
        section["work_dir"] = str(work_dir or "").strip()

    def _set_occs_session_alias(self, session_alias: str) -> None:
        section = self._occs_settings_section()
        section["session_alias"] = str(session_alias or "").strip()

    def _set_occs_shared_workspace_dir(self, shared_workspace_dir: str) -> None:
        section = self._occs_settings_section()
        section["shared_workspace_dir"] = str(shared_workspace_dir or "").strip()

    def _set_occs_user_name(self, user_name: str) -> None:
        section = self._occs_settings_section()
        section["user_name"] = str(user_name or "").strip()

    def _set_occs_preview_open_program(self, render_type: str, program: str) -> None:
        section = self._occs_settings_section()
        programs = section.setdefault("preview_open_programs", {})
        if not isinstance(programs, dict):
            programs = {}
            section["preview_open_programs"] = programs
        normalized = self._normalize_preview_render_type(render_type)
        if normalized:
            programs[normalized] = str(program or "").strip()

    def _set_last_occs_config_id(self, config_id: str) -> None:
        section = self._occs_settings_section()
        section["last_config_id"] = str(config_id or "").strip()
        self._save_user_settings()

    def _occs_settings_section(self) -> dict[str, object]:
        section = self.user_settings.setdefault("occs", {})
        if not isinstance(section, dict):
            section = {}
            self.user_settings["occs"] = section
        return section

    def _get_occs_cli_path(self) -> str:
        section = self.user_settings.get("occs")
        configured = ""
        if isinstance(section, dict):
            configured = str(section.get("cli_path", "")).strip()
        return os.path.expanduser(configured or self._default_occs_cli_path())

    def _get_occs_work_dir(self) -> str:
        section = self.user_settings.get("occs")
        configured = ""
        if isinstance(section, dict):
            configured = str(section.get("work_dir", "")).strip()
        return os.path.expanduser(configured or self._default_occs_work_dir())

    def _get_occs_session_alias(self) -> str:
        section = self.user_settings.get("occs")
        if not isinstance(section, dict):
            return ""
        return str(section.get("session_alias", "")).strip()

    def _get_occs_shared_workspace_dir(self) -> str:
        section = self.user_settings.get("occs")
        configured = ""
        if isinstance(section, dict):
            configured = str(section.get("shared_workspace_dir", "")).strip()
        return os.path.expanduser(configured or self._default_occs_shared_workspace_dir())

    def _get_occs_user_name(self) -> str:
        section = self.user_settings.get("occs")
        if not isinstance(section, dict):
            return ""
        return str(section.get("user_name", "")).strip()

    def _get_occs_preview_open_program(self, render_type: str) -> str:
        section = self.user_settings.get("occs")
        if not isinstance(section, dict):
            return ""
        programs = section.get("preview_open_programs")
        if not isinstance(programs, dict):
            return ""
        return str(programs.get(self._normalize_preview_render_type(render_type), "")).strip()

    def _get_occs_package_mru(self) -> list[dict[str, str]]:
        section = self.user_settings.get("occs")
        if not isinstance(section, dict):
            return []
        return self._normalize_occs_package_mru(section.get("package_mru"))

    def _record_occs_package_mru(self, package_name: str, version_name: str) -> None:
        package_text = str(package_name or "").strip()
        version_text = str(version_name or "").strip()
        if not package_text or not version_text:
            return
        existing = self._get_occs_package_mru()
        normalized_package = package_text.lower()
        normalized_version = version_text.lower()
        filtered = [
            item
            for item in existing
            if not (
                item.get("package", "").lower() == normalized_package
                and item.get("version", "").lower() == normalized_version
            )
        ]
        next_entries = [
            {
                "package": package_text,
                "version": version_text,
                "lastOpenedAt": self._current_timestamp(),
            },
            *filtered,
        ][:5]
        section = self._occs_settings_section()
        section["package_mru"] = next_entries
        self._save_user_settings()

    def _record_occs_package_mru_from_manifest(self, manifest: dict[str, object] | None) -> None:
        self._record_occs_package_mru(
            self._occs_manifest_package_short_name(manifest),
            self._occs_manifest_version_short_name(manifest),
        )

    def _occs_mru_package_names(self) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for item in self._get_occs_package_mru():
            package_name = item.get("package", "").strip()
            key = package_name.lower()
            if package_name and key not in seen:
                names.append(package_name)
                seen.add(key)
        return names

    def _occs_mru_versions_for_package(self, package_name: str) -> list[str]:
        normalized_package = str(package_name or "").strip().lower()
        versions: list[str] = []
        seen: set[str] = set()
        for item in self._get_occs_package_mru():
            if item.get("package", "").strip().lower() != normalized_package:
                continue
            version_name = item.get("version", "").strip()
            key = version_name.lower()
            if version_name and key not in seen:
                versions.append(version_name)
                seen.add(key)
        return versions

    def _occs_mru_version_choices(self, package_name: str) -> list[str]:
        versions = self._occs_mru_versions_for_package(package_name)
        if not any(version.lower() == "latest" for version in versions):
            versions.append("latest")
        return versions or ["latest"]

    @staticmethod
    def _normalize_occs_package_mru(raw_entries: object) -> list[dict[str, str]]:
        if not isinstance(raw_entries, list):
            return []
        normalized: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                continue
            package_name = str(raw_entry.get("package", "")).strip()
            version_name = str(raw_entry.get("version", "")).strip()
            if not package_name or not version_name:
                continue
            key = (package_name.lower(), version_name.lower())
            if key in seen:
                continue
            seen.add(key)
            normalized.append(
                {
                    "package": package_name,
                    "version": version_name,
                    "lastOpenedAt": str(raw_entry.get("lastOpenedAt", "")).strip(),
                }
            )
            if len(normalized) >= 5:
                break
        return normalized

    def _normalize_occs_preview_open_programs(self, raw_programs: object) -> dict[str, str]:
        defaults = {
            render_type: ""
            for render_type in self.OCCS_PREVIEW_RENDER_TYPES
        }
        if not isinstance(raw_programs, dict):
            return defaults
        for render_type in self.OCCS_PREVIEW_RENDER_TYPES:
            value = raw_programs.get(render_type)
            if isinstance(value, str):
                defaults[render_type] = value
        return defaults

    def _normalize_preview_render_type(self, render_type: str) -> str:
        normalized = str(render_type or "").strip().upper()
        return normalized if normalized in self.OCCS_PREVIEW_RENDER_TYPES else ""

    def _get_last_occs_config_id(self) -> str:
        section = self.user_settings.get("occs")
        if not isinstance(section, dict):
            return ""
        return str(section.get("last_config_id", "")).strip()

    @staticmethod
    def _default_occs_cli_path() -> str:
        sibling_cli = Path(__file__).resolve().parent.parent / "ccs-tools" / "OCCS-CLI" / "bin" / "occs.js"
        if sibling_cli.exists():
            return str(sibling_cli)
        return "occs"

    @staticmethod
    def _default_occs_work_dir() -> str:
        return str(Path.home() / ".atool" / "occs-bundles")

    @staticmethod
    def _default_occs_shared_workspace_dir() -> str:
        clp_working = Path.home() / "clp-working"
        if clp_working.exists():
            return str(clp_working / "ATool")
        return str(Path.home() / ".atool" / "shared-workspace")

    def _get_document_collapse_setting(self) -> bool:
        document_display = self.user_settings.get("document_display")
        if not isinstance(document_display, dict):
            return False
        return bool(document_display.get("collapse"))

    def _is_debug_logging_enabled(self) -> bool:
        diagnostics = self.user_settings.get("diagnostics")
        if not isinstance(diagnostics, dict):
            return False
        return bool(diagnostics.get("debug_logging"))

    def _debug_log(self, message: str) -> None:
        if not self._is_debug_logging_enabled():
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[ATool {timestamp}] {message}", flush=True)

    def _load_user_settings(self) -> dict[str, object]:
        settings_path = self._settings_file()
        settings = json.loads(json.dumps(self.DEFAULT_SETTINGS))
        if not settings_path.exists():
            return settings

        try:
            with open(settings_path, "r", encoding="utf-8") as source:
                parsed = json.load(source)
        except (OSError, json.JSONDecodeError):
            return settings

        if not isinstance(parsed, dict):
            return settings

        document_display = parsed.get("document_display")
        if isinstance(document_display, dict):
            collapse_value = document_display.get("collapse")
            if isinstance(collapse_value, bool):
                settings["document_display"]["collapse"] = collapse_value

        diagnostics = parsed.get("diagnostics")
        if isinstance(diagnostics, dict):
            debug_value = diagnostics.get("debug_logging")
            if isinstance(debug_value, bool):
                settings["diagnostics"]["debug_logging"] = debug_value

        occs = parsed.get("occs")
        if isinstance(occs, dict):
            for key in ("cli_path", "work_dir", "session_alias", "last_config_id", "shared_workspace_dir", "user_name"):
                value = occs.get(key)
                if isinstance(value, str):
                    settings["occs"][key] = value
            settings["occs"]["package_mru"] = self._normalize_occs_package_mru(occs.get("package_mru"))
            settings["occs"]["preview_open_programs"] = self._normalize_occs_preview_open_programs(
                occs.get("preview_open_programs")
            )
        return settings

    def _save_user_settings(self) -> None:
        settings_path = self._settings_file()
        try:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            with open(settings_path, "w", encoding="utf-8") as target:
                json.dump(self.user_settings, target, indent=2)
        except OSError as error:
            messagebox.showwarning(
                "Settings Write Warning",
                f"Could not save settings to:\n{settings_path}\n\nDetails: {error}",
            )

    @staticmethod
    def _settings_file() -> Path:
        return Path.home() / ".atool" / ".settings.json"

    def _on_document_tree_select(self, _event: tk.Event) -> None:
        selected = self.documents_tree.selection()
        if not selected:
            self._active_document_node_id = None
            self._clear_document_details()
            self._set_empty_layouts_tree("No document selected")
            self._update_document_context_buttons()
            self._refresh_condition_composer_for_current_target()
            return
        node_id = selected[0]
        details = self._document_node_details.get(node_id)
        if not details:
            self._active_document_node_id = None
            self._clear_document_details()
            self._set_empty_layouts_tree("No document selected")
            self._update_document_context_buttons()
            self._refresh_condition_composer_for_current_target()
            return
        self._active_document_node_id = node_id
        self._set_document_details(details)
        self._render_layouts_for_document(details)
        self._update_document_context_buttons()
        self._refresh_condition_composer_for_current_target()

    def _on_documents_filter_changed(self, *_args: object) -> None:
        self._render_documents_tree()

    def _on_fields_filter_changed(self, *_args: object) -> None:
        self._render_fields_tree()

    def _render_layouts_for_document(self, details: dict[str, object]) -> None:
        document = details.get("document_ref")
        if not isinstance(document, dict):
            self._set_empty_layouts_tree("No layouts found")
            return
        source = document.get("source")
        if not isinstance(source, dict):
            self._set_empty_layouts_tree("No layouts found")
            return
        layouts = source.get("Layouts")
        if not isinstance(layouts, list) or not layouts:
            self._set_empty_layouts_tree("No layouts found")
            return

        self.layouts_tree.delete(*self.layouts_tree.get_children())
        self._layout_node_details = {}
        self._active_layout_node_id = None
        self._clear_layout_details()
        for layout in layouts:
            if not isinstance(layout, dict):
                continue
            self._insert_layout_node("", layout)

        if not self.layouts_tree.get_children():
            self._set_empty_layouts_tree("No layouts found")

    def _insert_layout_node(self, parent_node: str, layout: dict[str, object]) -> None:
        node_text = self._build_layout_tree_label("layout", layout)
        node_id = self.layouts_tree.insert(parent_node, "end", text=node_text, open=False)
        details = {
            "node_kind": "layout",
            "source_ref": layout,
        }
        self._layout_node_details[node_id] = details
        self._apply_layout_mapping_tag(node_id, details)
        contents = self._extract_contents(layout)
        for content in contents:
            self._insert_content_node(node_id, content)

    def _insert_content_node(self, parent_node: str, content: dict[str, object]) -> None:
        node_text = self._build_layout_tree_label("content", content)
        node_id = self.layouts_tree.insert(parent_node, "end", text=node_text, open=False)
        details = {
            "node_kind": "content",
            "source_ref": content,
        }
        self._layout_node_details[node_id] = details
        self._apply_layout_mapping_tag(node_id, details)
        self._insert_condition_child(node_id, content)

        iteration = self._extract_iteration(content)
        if isinstance(iteration, dict):
            iteration_text = self._build_layout_tree_label("iteration", iteration)
            iter_node_id = self.layouts_tree.insert(node_id, "end", text=iteration_text, open=False)
            self._layout_node_details[iter_node_id] = {
                "node_kind": "iteration",
                "source_ref": iteration,
            }
            self._insert_condition_child(iter_node_id, iteration)
            fields = self._extract_iteration_fields(iteration)
            for field in fields:
                if not isinstance(field, dict):
                    continue
                field_text = self._build_layout_tree_label("field", field)
                field_node_id = self.layouts_tree.insert(iter_node_id, "end", text=field_text, open=False)
                self._layout_node_details[field_node_id] = {
                    "node_kind": "field",
                    "source_ref": field,
                }
                self._insert_condition_child(field_node_id, field)

    def _insert_condition_child(self, parent_node: str, source_ref: dict[str, object]) -> None:
        condition = str(source_ref.get("Condition", "")).strip()
        if not condition:
            return
        condition_node_id = self.layouts_tree.insert(parent_node, "end", text=f"Condition: {condition}", open=False)
        self._layout_node_details[condition_node_id] = {
            "node_kind": "condition",
            "source_ref": source_ref,
        }

    @staticmethod
    def _extract_contents(layout: dict[str, object]) -> list[dict[str, object]]:
        for key in ("Contents", "Content", "contents", "content"):
            value = layout.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_iteration(content: dict[str, object]) -> dict[str, object] | None:
        for key in ("Iteration", "iteration"):
            value = content.get(key)
            if isinstance(value, dict):
                return value
        return None

    @staticmethod
    def _extract_iteration_fields(iteration: dict[str, object]) -> list[dict[str, object]]:
        for key in ("Fields", "fields"):
            value = iteration.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _build_layout_tree_label(self, kind: str, item: dict[str, object]) -> str:
        name = str(item.get("$$Id") or item.get("Name") or item.get("Id") or "(unnamed)")
        if kind == "layout":
            return f"Layout: {name}"
        if kind == "content":
            return f"Content: {name}"
        if kind == "iteration":
            return f"Iteration: {name}"
        if kind == "field":
            path = str(item.get("Path", "")).strip()
            if path:
                return f"Field: {name} ({path})"
            return f"Field: {name}"
        return name

    def _set_empty_layouts_tree(self, message: str) -> None:
        self.layouts_tree.delete(*self.layouts_tree.get_children())
        self._layout_node_details = {}
        self._clear_layout_details()
        self.layouts_tree.insert("", "end", text=message)
        self._active_layout_node_id = None
        self._update_layout_context_buttons()

    def _on_layout_tree_select(self, _event: tk.Event) -> None:
        selected = self.layouts_tree.selection()
        if not selected:
            self._active_layout_node_id = None
            self._clear_layout_details()
            self._update_layout_context_buttons()
            self._refresh_condition_composer_for_current_target()
            return
        node_id = selected[0]
        details = self._layout_node_details.get(node_id)
        if not details:
            self._active_layout_node_id = None
            self._clear_layout_details()
            self._update_layout_context_buttons()
            self._refresh_condition_composer_for_current_target()
            return
        self._active_layout_node_id = node_id
        self._set_layout_details(details)
        self._update_layout_context_buttons()
        self._refresh_condition_composer_for_current_target()

    def _set_layout_details(self, details: dict[str, object]) -> None:
        self._updating_layout_form = True
        source_ref = details.get("source_ref")
        if not isinstance(source_ref, dict):
            self._clear_layout_details()
            self._updating_layout_form = False
            return
        node_kind = str(details.get("node_kind", "-"))
        self._set_layout_property_visibility(node_kind)
        self.layout_item_kind_text.set(node_kind if node_kind != "condition" else "condition")
        if node_kind == "condition":
            self.layout_name_edit_var.set("")
            self.layout_condition_edit_var.set(str(source_ref.get("Condition", "")))
            self.layout_iteration_edit_var.set("")
            self.layout_path_edit_var.set("")
            self.layout_type_edit_var.set("")
            self.layout_mandatory_var.set(False)
        else:
            self.layout_name_edit_var.set(str(source_ref.get("$$Id") or source_ref.get("Name") or ""))
            self.layout_condition_edit_var.set(str(source_ref.get("Condition", "")))
            self.layout_iteration_edit_var.set(str(source_ref.get("Iteration", "")) if node_kind == "content" else "")
            self.layout_path_edit_var.set(str(source_ref.get("Path", "")))
            self.layout_type_edit_var.set(str(source_ref.get("Type", "")))
            self.layout_mandatory_var.set(self._mandatory_to_bool(source_ref.get("Mandatory")))
        summary = []
        if "Condition" in source_ref:
            summary.append(f"Condition: {source_ref.get('Condition', '')}")
        if "Path" in source_ref:
            summary.append(f"Path: {source_ref.get('Path', '')}")
        if "Type" in source_ref:
            summary.append(f"Type: {source_ref.get('Type', '')}")
        self.layout_summary_text.set(" | ".join(summary) if summary else "(no additional properties)")
        self.layout_mapped_text.set(self._build_layout_mapped_display(details))
        self._updating_layout_form = False

    def _clear_layout_details(self) -> None:
        self._updating_layout_form = True
        self._set_layout_property_visibility("")
        self.layout_item_kind_text.set("-")
        self.layout_name_edit_var.set("")
        self.layout_condition_edit_var.set("")
        self.layout_iteration_edit_var.set("")
        self.layout_path_edit_var.set("")
        self.layout_type_edit_var.set("")
        self.layout_mandatory_var.set(False)
        self.layout_summary_text.set("-")
        self.layout_mapped_text.set("-")
        self._updating_layout_form = False

    def _apply_layout_mapping_tag(self, node_id: str, details: dict[str, object]) -> None:
        node_kind = str(details.get("node_kind", ""))
        if node_kind not in {"layout", "content"} or self.current_data_payload is None:
            self.layouts_tree.item(node_id, tags=())
            return
        tag = "layout_triggered" if self._layout_node_chain_triggered_for_node(node_id) else "layout_untriggered"
        self.layouts_tree.item(node_id, tags=(tag,))

    def _refresh_layout_mapping_tags(self) -> None:
        for node_id, details in self._layout_node_details.items():
            self._apply_layout_mapping_tag(node_id, details)

    def _build_layout_mapped_display(self, details: dict[str, object]) -> str:
        if self.current_data_payload is None:
            return "(no data mapped)"
        if not self._layout_node_chain_triggered(details):
            return "(parent condition not triggered)"

        source_ref = details.get("source_ref")
        if not isinstance(source_ref, dict):
            return "-"
        node_kind = str(details.get("node_kind", ""))

        if node_kind == "iteration":
            path = str(source_ref.get("Path", "")).strip()
            if not path:
                return "(iteration has no path)"
            items = self._extract_values_by_path(self.current_data_payload, path)
            return f"{len(items)} item(s): {self._format_mapped_nodeset_preview(items)}"

        if node_kind == "field":
            path = str(source_ref.get("Path", "")).strip()
            if not path:
                return "(field has no path)"
            iteration_details = self._find_iteration_details_for_layout_node()
            if not iteration_details:
                values = self._extract_values_by_path(self.current_data_payload, path)
                return self._format_mapped_nodeset_preview(values) if values else "(no mapped value)"

            iteration_ref = iteration_details.get("source_ref")
            if not isinstance(iteration_ref, dict):
                return "(iteration context missing)"
            iteration_path = str(iteration_ref.get("Path", "")).strip()
            if not iteration_path:
                return "(iteration has no path)"
            iteration_items = self._extract_values_by_path(self.current_data_payload, iteration_path)
            if not iteration_items:
                return "(no iterator rows)"
            row_lines: list[str] = []
            for row_index, item in enumerate(iteration_items, start=1):
                row_values = self._extract_values_by_path(item, path)
                if row_values:
                    row_preview = self._format_mapped_nodeset_preview(row_values)
                else:
                    row_preview = "(no value)"
                row_lines.append(f"Row {row_index}: {row_preview}")
            return "\n".join(row_lines)

        return "-"

    def _layout_node_chain_triggered(self, details: dict[str, object]) -> bool:
        if self._active_layout_node_id is None:
            return False
        return self._layout_node_chain_triggered_for_node(self._active_layout_node_id)

    def _layout_node_chain_triggered_for_node(self, node_id: str) -> bool:
        document_ref = self._get_selected_document_ref()
        if document_ref is None:
            return False
        if self.current_data_payload is None:
            return False
        if not bool(document_ref.get("triggered", False)):
            return False
        while node_id:
            node_details = self._layout_node_details.get(node_id)
            if isinstance(node_details, dict):
                source_ref = node_details.get("source_ref")
                if isinstance(source_ref, dict):
                    condition_text = str(source_ref.get("Condition", "")).strip()
                    if condition_text and not self._evaluate_document_condition(condition_text, self.current_data_payload):
                        return False
            node_id = self.layouts_tree.parent(node_id)
        return True

    def _find_iteration_details_for_layout_node(self) -> dict[str, object] | None:
        if self._active_layout_node_id is None:
            return None
        node_id = self._active_layout_node_id
        while node_id:
            details = self._layout_node_details.get(node_id)
            if isinstance(details, dict) and str(details.get("node_kind", "")) == "iteration":
                return details
            node_id = self.layouts_tree.parent(node_id)
        return None

    def _set_layout_property_visibility(self, node_kind: str) -> None:
        if not hasattr(self, "_layout_property_widget_pairs"):
            return
        visible_by_kind: dict[str, set[str]] = {
            "layout": {"name", "condition"},
            "content": {"name", "condition", "iteration"},
            "iteration": {"name", "condition", "path", "type"},
            "field": {"name", "condition", "path", "mandatory"},
            "condition": {"condition"},
        }
        visible_fields = visible_by_kind.get(node_kind, set())
        for field_key, widgets in self._layout_property_widget_pairs.items():
            title_widget, value_widget = widgets
            if field_key in visible_fields:
                title_widget.grid()
                value_widget.grid()
            else:
                title_widget.grid_remove()
                value_widget.grid_remove()

    def _on_layout_name_changed(self, *_args: object) -> None:
        self._apply_layout_form_change(name=self.layout_name_edit_var.get())

    def _on_layout_condition_changed(self, *_args: object) -> None:
        self._apply_layout_form_change(condition=self.layout_condition_edit_var.get())

    def _on_layout_iteration_changed(self, *_args: object) -> None:
        self._apply_layout_form_change(iteration=self.layout_iteration_edit_var.get())

    def _on_layout_path_changed(self, *_args: object) -> None:
        self._apply_layout_form_change(path=self.layout_path_edit_var.get())

    def _on_layout_type_changed(self, *_args: object) -> None:
        self._apply_layout_form_change(type_value=self.layout_type_edit_var.get())

    def _on_layout_mandatory_changed(self, *_args: object) -> None:
        self._apply_layout_form_change(mandatory=bool(self.layout_mandatory_var.get()))

    def _apply_layout_form_change(
        self,
        *,
        name: str | None = None,
        condition: str | None = None,
        iteration: str | None = None,
        path: str | None = None,
        type_value: str | None = None,
        mandatory: bool | None = None,
    ) -> None:
        if self._updating_layout_form:
            return
        if not self._active_layout_node_id:
            return
        details = self._layout_node_details.get(self._active_layout_node_id)
        if not details:
            return
        source_ref = details.get("source_ref")
        if not isinstance(source_ref, dict):
            return
        node_kind = str(details.get("node_kind", ""))
        changed = False

        if name is not None:
            normalized = name.strip()
            if node_kind == "condition":
                pass
            elif "$$Id" in source_ref:
                if normalized != str(source_ref.get("$$Id", "")):
                    source_ref["$$Id"] = normalized
                    changed = True
            elif "Name" in source_ref:
                if normalized != str(source_ref.get("Name", "")):
                    source_ref["Name"] = normalized
                    changed = True

        if condition is not None and node_kind in {"layout", "content", "iteration", "field", "condition"}:
            normalized = condition.strip()
            current_condition = str(source_ref.get("Condition", ""))
            if normalized != current_condition:
                source_ref["Condition"] = normalized
                changed = True

        if iteration is not None and "Iteration" in source_ref and not isinstance(source_ref.get("Iteration"), dict):
            normalized = iteration.strip()
            if normalized != str(source_ref.get("Iteration", "")):
                source_ref["Iteration"] = normalized
                changed = True

        if path is not None and "Path" in source_ref:
            normalized = path.strip()
            if normalized != str(source_ref.get("Path", "")):
                source_ref["Path"] = normalized
                changed = True

        if type_value is not None and "Type" in source_ref:
            normalized = type_value.strip()
            if node_kind == "iteration" and normalized and normalized not in {"Iterator", "Spliterator"}:
                messagebox.showerror(
                    "Invalid Iteration Type",
                    "Iteration Type must be either 'Iterator' or 'Spliterator'.",
                )
                self._updating_layout_form = True
                self.layout_type_edit_var.set(str(source_ref.get("Type", "")))
                self._updating_layout_form = False
                return
            if normalized != str(source_ref.get("Type", "")):
                source_ref["Type"] = normalized
                changed = True

        if mandatory is not None and "Mandatory" in source_ref:
            normalized_mandatory = bool(mandatory)
            if normalized_mandatory != self._mandatory_to_bool(source_ref.get("Mandatory")):
                source_ref["Mandatory"] = normalized_mandatory
                changed = True

        if not changed:
            return
        self._touch_selected_document_updated()
        self._set_dirty(True)
        if node_kind == "condition":
            self.layouts_tree.item(
                self._active_layout_node_id,
                text=f"Condition: {str(source_ref.get('Condition', '')).strip()}",
            )
            self._refresh_layout_mapping_tags()
            self._set_layout_details(details)
            return
        self._refresh_layouts_for_active_document()
        self._select_layout_node_for_source(source_ref, preferred_kind=node_kind)

    def _refresh_layouts_for_active_document(self) -> None:
        if not self._active_document_node_id:
            return
        details = self._document_node_details.get(self._active_document_node_id)
        if not details:
            return
        self._render_layouts_for_document(details)

    def _touch_selected_document_updated(self) -> None:
        document_ref = self._get_selected_document_ref()
        if document_ref is None:
            return
        source = document_ref.get("source")
        if not isinstance(source, dict):
            return
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        source["Updated"] = now_text
        document_ref["updated"] = now_text
        if self._active_document_node_id:
            details = self._document_node_details.get(self._active_document_node_id)
            if isinstance(details, dict):
                details["updated"] = now_text
                self.document_updated_text.set(now_text)

    def _get_selected_document_ref(self) -> dict[str, object] | None:
        if not self._active_document_node_id:
            return None
        details = self._document_node_details.get(self._active_document_node_id)
        if not details:
            return None
        document_ref = details.get("document_ref")
        if not isinstance(document_ref, dict):
            return None
        return document_ref

    def _get_documents_source_list(self) -> list[dict[str, object]] | None:
        if not isinstance(self.current_payload, dict):
            return None
        documents = self.current_payload.get("Documents")
        if not isinstance(documents, list):
            return None
        return [item for item in documents if isinstance(item, dict)]

    def add_document(self) -> None:
        if self.current_payload is None:
            messagebox.showinfo("Add Document", "Open an assembly template first.")
            return

        documents = self.current_payload.get("Documents")
        if not isinstance(documents, list):
            documents = []
            self.current_payload["Documents"] = documents

        existing_names = {
            str(document.get("$$Id", "")).strip()
            for document in documents
            if isinstance(document, dict)
        }
        counter = len(existing_names) + 1
        while True:
            candidate = f"NewDocument{counter}"
            if candidate not in existing_names:
                break
            counter += 1

        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        source_document = {
            "$$Id": candidate,
            "Updated": now_text,
            "Descr": "",
            "Condition": "",
            "Layouts": [],
        }
        documents.append(source_document)

        self._loaded_documents = self._extract_documents(self.current_payload)
        new_document = next(
            (
                document
                for document in self._loaded_documents
                if document.get("source") is source_document
            ),
            None,
        )
        if new_document is not None and self.current_data_payload is not None:
            self._refresh_document_condition_mapping(new_document)
        elif self.current_data_payload is not None:
            self.document_count_text.set(
                f"Documents: {len(self._loaded_documents)} ({len(self._triggered_document_names)} matched)"
            )
        else:
            self.document_count_text.set(f"Documents: {len(self._loaded_documents)}")

        self._set_dirty(True)
        self._render_documents_tree()
        self._select_document_node_for_source(source_document)

    def add_layout_to_selected_document(self) -> None:
        document_ref = self._get_selected_document_ref()
        if document_ref is None:
            return
        source = document_ref.get("source")
        if not isinstance(source, dict):
            return
        layouts = source.get("Layouts")
        if not isinstance(layouts, list):
            layouts = []
            source["Layouts"] = layouts
        counter = len(layouts) + 1
        layout = {
            "$$Id": f"NewLayout{counter}",
            "Descr": "",
            "Condition": "",
            "Contents": [],
        }
        layouts.append(layout)
        self._touch_selected_document_updated()
        self._set_dirty(True)
        self._refresh_layouts_for_active_document()
        self._select_layout_node_for_source(layout, preferred_kind="layout")

    def generate_sample_input_for_selected_document(self) -> None:
        document_ref = self._get_selected_document_ref()
        if document_ref is None:
            messagebox.showinfo("Generate Sample Input", "Select a document first.")
            return

        document_name = str(document_ref.get("name", "")).strip() or "document"
        condition_text = str(document_ref.get("condition", "")).strip()
        field_specs: list[dict[str, str]] = []
        for field in self._loaded_fields:
            raw_path = str(field.get("path", "")).strip()
            if not raw_path:
                continue
            field_specs.append(
                {
                    "path": raw_path,
                    "name": str(field.get("name", "")).strip(),
                    "descr": str(field.get("descr", "")).strip(),
                }
            )

        sample_payload, report_lines = self._generate_sample_input_payload(condition_text, field_specs)
        self._show_generated_input_preview(document_name, sample_payload, report_lines)

    def _generate_sample_input_payload(
        self,
        condition_text: str,
        field_specs: list[dict[str, str]],
    ) -> tuple[dict[str, object], list[str]]:
        payload: dict[str, object] = {}
        report: list[str] = []

        for spec in field_specs:
            field_path = str(spec.get("path", "")).strip()
            if not field_path:
                continue
            true_path = self._normalize_true_path(field_path)
            seed_value = self._infer_mock_value_for_field(
                path=true_path,
                field_name=str(spec.get("name", "")),
                field_descr=str(spec.get("descr", "")),
            )
            self._set_generated_value_for_path(payload, true_path, seed_value)

        condition_body = self._extract_condition_body(condition_text)
        if condition_body:
            self._satisfy_condition_expression(condition_body, payload, report)

        missing_fields: list[str] = []
        for spec in field_specs:
            field_path = str(spec.get("path", "")).strip()
            if not field_path:
                continue
            true_path = self._normalize_true_path(field_path)
            if self._extract_values_by_path(payload, true_path):
                continue
            seed_value = self._infer_mock_value_for_field(
                path=true_path,
                field_name=str(spec.get("name", "")),
                field_descr=str(spec.get("descr", "")),
            )
            self._set_generated_value_for_path(payload, true_path, seed_value)
            if not self._extract_values_by_path(payload, true_path):
                missing_fields.append(field_path)

        if missing_fields:
            report.append("Some field paths could not be materialized:")
            report.extend(f"- {path}" for path in missing_fields[:25])
            if len(missing_fields) > 25:
                report.append(f"- ... and {len(missing_fields) - 25} more")

        condition_ok = self._evaluate_document_condition(condition_text, payload)
        if condition_ok:
            report.append("Document condition: satisfied.")
        else:
            report.append("Document condition: not satisfied after synthesis.")
            atomic = self._collect_atomic_condition_clauses(condition_body) if condition_body else []
            for clause in atomic:
                passed, details = self._evaluate_atomic_condition_with_detail(clause, payload)
                if passed:
                    continue
                report.append(f"- {clause} -> {details}")

        return payload, report

    def _show_generated_input_preview(
        self,
        document_name: str,
        payload: dict[str, object],
        report_lines: list[str],
    ) -> None:
        preview = json.dumps(payload, indent=2, ensure_ascii=False)
        summary = "\n".join(report_lines) if report_lines else "No warnings."

        dialog = self._create_toplevel(self.root)
        dialog.title(f"Sample Input - {document_name}")
        dialog.transient(self.root)
        dialog.geometry("860x640")
        dialog.minsize(640, 420)

        container = ttk.Frame(dialog, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        ttk.Label(container, text="Generation Report:", font=("TkDefaultFont", 10, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        report_widget = tk.Text(container, height=6, wrap="word")
        report_widget.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        report_widget.insert("1.0", summary)
        report_widget.configure(state=tk.DISABLED)

        ttk.Label(container, text="Generated JSON:", font=("TkDefaultFont", 10, "bold")).grid(
            row=2, column=0, sticky="w", pady=(0, 6)
        )
        json_frame = ttk.Frame(container)
        json_frame.grid(row=3, column=0, sticky="nsew")
        container.rowconfigure(3, weight=3)
        json_frame.columnconfigure(0, weight=1)
        json_frame.rowconfigure(0, weight=1)

        json_widget = tk.Text(json_frame, wrap="none")
        json_widget.grid(row=0, column=0, sticky="nsew")
        json_widget.insert("1.0", preview)

        y_scroll = ttk.Scrollbar(json_frame, orient=tk.VERTICAL, command=json_widget.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        json_widget.configure(yscrollcommand=y_scroll.set)

        x_scroll = ttk.Scrollbar(json_frame, orient=tk.HORIZONTAL, command=json_widget.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        json_widget.configure(xscrollcommand=x_scroll.set)

        actions = ttk.Frame(container)
        actions.grid(row=4, column=0, sticky="e", pady=(8, 0))

        def _save_generated() -> None:
            default_name = f"{self._slugify(document_name)}_sample_input.json"
            path = filedialog.asksaveasfilename(
                parent=dialog,
                title="Save Generated Sample Input",
                defaultextension=".json",
                initialfile=default_name,
                filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            )
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8") as target:
                    target.write(preview)
            except OSError as error:
                messagebox.showerror("Save Error", f"Could not save file:\n{path}\n\nDetails: {error}")
                return
            messagebox.showinfo("Saved", f"Generated sample input saved to:\n{path}")

        ttk.Button(actions, text="Save As...", command=_save_generated).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(actions, text="Close", command=dialog.destroy).grid(row=0, column=1)

    def _satisfy_condition_expression(self, expression: str, payload: object, report: list[str]) -> bool:
        expr = self._strip_outer_parens(expression)
        if not expr:
            return True

        or_parts = self._split_top_level_operator(expr, "||")
        if len(or_parts) > 1:
            for part in or_parts:
                candidate = copy.deepcopy(payload)
                local_report: list[str] = []
                if self._satisfy_condition_expression(part, candidate, local_report):
                    if isinstance(payload, dict) and isinstance(candidate, dict):
                        payload.clear()
                        payload.update(candidate)
                    report.extend(local_report)
                    return True
            report.append(f"Could not satisfy OR expression: {expr}")
            return False

        and_parts = self._split_top_level_operator(expr, "&&")
        if len(and_parts) > 1:
            overall = True
            for part in and_parts:
                if not self._satisfy_condition_expression(part, payload, report):
                    overall = False
            return overall

        return self._apply_atomic_generation_constraint(expr, payload, report)

    def _apply_atomic_generation_constraint(self, expression: str, payload: object, report: list[str]) -> bool:
        expr = self._strip_outer_parens(expression)
        if not expr:
            return True

        empty_match = re.match(r"^(.*?)\s+empty\s+(true|false)\s*$", expr, flags=re.IGNORECASE)
        if empty_match:
            path = self._normalize_condition_path(empty_match.group(1).strip())
            expect_empty = empty_match.group(2).lower() == "true"
            if expect_empty:
                parent_path = self._get_empty_check_parent_path(path)
                self._ensure_generated_path_exists(payload, parent_path)
                self._clear_generated_path_value(payload, path)
                return True
            self._set_generated_value_for_path(payload, path, "sample")
            return True

        size_match = self._find_top_level_word_operator(expr, "size")
        if size_match is not None:
            path_text, expected_size_text = size_match
            expected_values = self._evaluate_condition_operand(payload, expected_size_text)
            expected_size = self._first_integral_condition_value(expected_values)
            if expected_size is None:
                report.append(f"Could not determine target size for expression: {expr}")
                return False
            path = self._normalize_condition_path(path_text)
            if expected_size <= 0:
                self._clear_generated_path_value(payload, path)
            else:
                self._ensure_generated_path_exists(payload, path)
            actual_size = len(self._extract_values_by_path(payload, path))
            if actual_size != expected_size:
                report.append(
                    f"Could not materialize expression size: {expr} "
                    f"(expected {expected_size}, found {actual_size})"
                )
                return False
            return True

        comparison = self._find_top_level_comparison(expr)
        if comparison is not None:
            lhs_text, operator, rhs_text = comparison
            lhs_literal, lhs_is_literal = self._parse_condition_literal(lhs_text)
            rhs_literal, rhs_is_literal = self._parse_condition_literal(rhs_text)
            lhs_path = None if lhs_is_literal else self._normalize_condition_path(lhs_text)
            rhs_path = None if rhs_is_literal else self._normalize_condition_path(rhs_text)

            if lhs_path is None and rhs_path is None:
                return self._compare_single_condition_value(lhs_literal, operator, rhs_literal)

            if lhs_path is not None and rhs_path is None:
                lhs_value = self._derive_generation_value(operator, rhs_literal, side="left")
                self._set_generated_value_for_path(payload, lhs_path, lhs_value)
                return True

            if lhs_path is None and rhs_path is not None:
                rhs_value = self._derive_generation_value(operator, lhs_literal, side="right")
                self._set_generated_value_for_path(payload, rhs_path, rhs_value)
                return True

            left_value, right_value = self._derive_generation_pair(operator)
            if lhs_path is not None:
                self._set_generated_value_for_path(payload, lhs_path, left_value)
            if rhs_path is not None:
                self._set_generated_value_for_path(payload, rhs_path, right_value)
            return True

        literal_value, is_literal = self._parse_condition_literal(expr)
        if is_literal:
            return bool(literal_value)

        path = self._normalize_condition_path(expr)
        self._set_generated_value_for_path(payload, path, "sample")
        if not self._extract_values_by_path(payload, path):
            report.append(f"Could not materialize path for expression: {expr}")
            return False
        return True

    @staticmethod
    def _derive_generation_pair(operator: str) -> tuple[object, object]:
        if operator == "==":
            return "sample", "sample"
        if operator == "!=":
            return "sample", "different"
        if operator in {">", ">="}:
            return 2.0, 1.0
        if operator in {"<", "<="}:
            return 1.0, 2.0
        return "sample", "sample"

    def _derive_generation_value(self, operator: str, rhs_value: object, side: str) -> object:
        if operator == "==":
            return rhs_value
        if operator == "!=":
            return self._different_value(rhs_value)

        rhs_number = self._as_float(rhs_value)
        if rhs_number is None:
            return 2.0 if operator in {">", ">="} else 1.0

        if side == "left":
            if operator == ">":
                return rhs_number + 1.0
            if operator == ">=":
                return rhs_number
            if operator == "<":
                return rhs_number - 1.0
            if operator == "<=":
                return rhs_number
        else:
            if operator == ">":
                return rhs_number - 1.0
            if operator == ">=":
                return rhs_number
            if operator == "<":
                return rhs_number + 1.0
            if operator == "<=":
                return rhs_number
        return rhs_value

    @staticmethod
    def _as_float(value: object) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _different_value(value: object) -> object:
        if isinstance(value, bool):
            return not value
        if isinstance(value, (int, float)):
            return float(value) + 1.0
        if value is None:
            return "sample"
        if isinstance(value, str):
            return value + "_x"
        return "different"

    def _default_generated_value_for_path(self, path: str) -> object:
        lowered = str(path).lower()
        if lowered.endswith(".mandatory") or lowered.endswith(".required"):
            return True
        if lowered.endswith(".count") or lowered.endswith(".amount") or lowered.endswith(".total"):
            return 1.0
        return "sample"

    def _infer_mock_value_for_field(self, path: str, field_name: str, field_descr: str) -> object:
        combined = " ".join([field_name, field_descr, path]).casefold()
        compact = combined.replace("_", " ").replace("-", " ")

        if any(token in compact for token in ("mandatory", "required", "is ", " has ", "flag", "enabled")):
            return True
        if any(token in compact for token in ("date", "due", "issued", "updated", "created", "posted", "period")):
            return "2026-03-13"
        if any(token in compact for token in ("time", "timestamp")):
            return "2026-03-13T09:30:00Z"
        if any(token in compact for token in ("email", "e-mail")):
            return "sample.user@example.com"
        if any(token in compact for token in ("phone", "tel", "mobile", "fax")):
            return "+1-212-555-0188"
        if any(token in compact for token in ("url", "uri", "website", "link")):
            return "https://example.com/sample"
        if any(token in compact for token in ("zip", "postal", "postcode")):
            return "10001"
        if any(token in compact for token in ("country",)):
            return "US"
        if any(token in compact for token in ("state", "province")):
            return "NY"
        if any(token in compact for token in ("city",)):
            return "New York"
        if any(token in compact for token in ("address", "street")):
            return "123 Sample Street"
        if any(token in compact for token in ("currency", "ccy")):
            return "USD"
        if any(token in compact for token in ("percent", "percentage", "rate")):
            return 12.5
        if any(token in compact for token in ("amount", "total", "balance", "price", "cost", "charge", "fee")):
            return 123.45
        if any(token in compact for token in ("count", "qty", "quantity", "number of", "num ")) or compact.endswith(" count"):
            return 2
        if any(token in compact for token in ("id", "identifier", "reference", "ref", "code", "number", "acct", "account")):
            return "REF-10001"
        if any(token in compact for token in ("name", "customer", "person", "contact")):
            return "Sample Name"
        if any(token in compact for token in ("status", "state", "result")):
            return "ACTIVE"
        if any(token in compact for token in ("desc", "description", "note", "remark", "comment")):
            return "Sample description"
        return self._default_generated_value_for_path(path)

    def _ensure_generated_path_exists(self, payload: object, path: str) -> bool:
        refs = self._resolve_generation_leaf_refs(payload, path, create=True)
        return len(refs) > 0

    def _set_generated_value_for_path(self, payload: object, path: str, value: object) -> bool:
        refs = self._resolve_generation_leaf_refs(payload, path, create=True)
        if not refs:
            return False
        for parent, slot in refs:
            self._assign_generation_slot(parent, slot, value)
        return True

    def _clear_generated_path_value(self, payload: object, path: str) -> bool:
        refs = self._resolve_generation_leaf_refs(payload, path, create=False)
        if not refs:
            return False
        for parent, slot in refs:
            if isinstance(parent, dict) and isinstance(slot, str):
                parent.pop(slot, None)
            elif isinstance(parent, list) and isinstance(slot, int) and 0 <= slot < len(parent):
                parent[slot] = None
        return True

    def _resolve_generation_leaf_refs(
        self,
        payload: object,
        path: str,
        create: bool,
    ) -> list[tuple[object, str | int]]:
        normalized = self._normalize_true_path(path)
        if not normalized.startswith("$"):
            return []
        segments = self._path_to_segments(normalized)
        if not segments or segments[0] != "$":
            return []
        if len(segments) == 1:
            return []

        refs: list[tuple[object, object, object]] = [(None, None, payload)]
        for segment in segments[1:]:
            refs = self._advance_generation_refs(refs, str(segment), create)
            if not refs:
                return []
        leaf_refs: list[tuple[object, str | int]] = []
        for parent, slot, _node in refs:
            if parent is None:
                continue
            if isinstance(slot, (str, int)):
                leaf_refs.append((parent, slot))
        return leaf_refs

    def _advance_generation_refs(
        self,
        refs: list[tuple[object, object, object]],
        segment: str,
        create: bool,
    ) -> list[tuple[object, object, object]]:
        base, brackets = self._split_path_segment(segment.strip())
        current_refs = refs

        if base:
            next_refs: list[tuple[object, object, object]] = []
            for parent, slot, node in current_refs:
                if base == "*":
                    wildcard_target = self._select_or_create_wildcard_child(parent, slot, node, create)
                    if wildcard_target is None:
                        continue
                    next_refs.append(wildcard_target)
                    continue
                child_ref = self._select_or_create_named_child(parent, slot, node, base, create)
                if child_ref is not None:
                    next_refs.append(child_ref)
            current_refs = next_refs

        for bracket in brackets:
            content = bracket[1:-1].strip()
            next_refs = []
            for parent, slot, node in current_refs:
                bracket_refs = self._select_or_create_bracket_child(parent, slot, node, content, create)
                next_refs.extend(bracket_refs)
            current_refs = next_refs
            if not current_refs:
                break

        return current_refs

    def _select_or_create_named_child(
        self,
        parent: object,
        slot: object,
        node: object,
        key: str,
        create: bool,
    ) -> tuple[object, object, object] | None:
        current = node
        if not isinstance(current, dict):
            if not create:
                return None
            replacement: dict[str, object] = {}
            if not self._replace_generation_node(parent, slot, replacement):
                return None
            current = replacement
        if key not in current:
            if not create:
                return None
            current[key] = {}
        return (current, key, current[key])

    def _select_or_create_wildcard_child(
        self,
        parent: object,
        slot: object,
        node: object,
        create: bool,
    ) -> tuple[object, object, object] | None:
        current = node
        if isinstance(current, dict):
            if not current:
                if not create:
                    return None
                current["item"] = {}
            first_key = next(iter(current))
            return (current, first_key, current[first_key])

        if not isinstance(current, list):
            if not create:
                return None
            replacement: list[object] = []
            if not self._replace_generation_node(parent, slot, replacement):
                return None
            current = replacement

        if not current:
            if not create:
                return None
            current.append({})
        return (current, 0, current[0])

    def _select_or_create_bracket_child(
        self,
        parent: object,
        slot: object,
        node: object,
        content: str,
        create: bool,
    ) -> list[tuple[object, object, object]]:
        text = content.strip()
        if not text:
            return []
        if text == "*":
            wildcard = self._select_or_create_wildcard_child(parent, slot, node, create)
            return [wildcard] if wildcard is not None else []

        if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')):
            key = text[1:-1]
            named = self._select_or_create_named_child(parent, slot, node, key, create)
            return [named] if named is not None else []

        if text.startswith("?(") and text.endswith(")"):
            wildcard = self._select_or_create_wildcard_child(parent, slot, node, create)
            if wildcard is None:
                return []
            filter_expression = text[2:-1].strip()
            candidate = wildcard[2]
            self._satisfy_condition_expression(filter_expression, candidate, [])
            return [wildcard]

        try:
            index_value = int(text)
        except ValueError:
            return []

        current = node
        if not isinstance(current, list):
            if not create:
                return []
            replacement: list[object] = []
            if not self._replace_generation_node(parent, slot, replacement):
                return []
            current = replacement

        target_index = index_value if index_value >= 0 else 0
        while len(current) <= target_index:
            if not create:
                return []
            current.append({})
        return [(current, target_index, current[target_index])]

    def _replace_generation_node(self, parent: object, slot: object, value: object) -> bool:
        if parent is None:
            return False
        self._assign_generation_slot(parent, slot, value)
        return True

    @staticmethod
    def _assign_generation_slot(parent: object, slot: object, value: object) -> None:
        if isinstance(parent, dict) and isinstance(slot, str):
            parent[slot] = value
        elif isinstance(parent, list) and isinstance(slot, int):
            while len(parent) <= slot:
                parent.append({})
            parent[slot] = value

    def move_selected_document(self, direction: int) -> None:
        context = self._selected_document_move_context()
        if context is None:
            return
        selected_sources, documents, _selected_indexes = context
        visible_sources = self._visible_document_sources(documents)
        reordered_sources = self._move_visible_document_selection(
            visible_sources,
            selected_sources,
            direction,
        )
        if reordered_sources is None:
            return
        self._apply_document_visible_order(documents, reordered_sources, selected_sources)

    def move_selected_document_to_top(self) -> None:
        context = self._selected_document_move_context()
        if context is None:
            return
        selected_sources, documents, _selected_indexes = context
        visible_sources = self._visible_document_sources(documents)
        selected_ids = {id(source) for source in selected_sources}
        reordered_sources = [
            source for source in visible_sources if id(source) in selected_ids
        ] + [
            source for source in visible_sources if id(source) not in selected_ids
        ]
        self._apply_document_visible_order(documents, reordered_sources, selected_sources)

    def move_selected_document_to_bottom(self) -> None:
        context = self._selected_document_move_context()
        if context is None:
            return
        selected_sources, documents, _selected_indexes = context
        visible_sources = self._visible_document_sources(documents)
        selected_ids = {id(source) for source in selected_sources}
        reordered_sources = [
            source for source in visible_sources if id(source) not in selected_ids
        ] + [
            source for source in visible_sources if id(source) in selected_ids
        ]
        self._apply_document_visible_order(documents, reordered_sources, selected_sources)

    def auto_move_selected_document(self) -> None:
        context = self._selected_document_move_context()
        if context is None:
            return
        selected_sources, documents, _selected_indexes = context
        source = selected_sources[0]
        insertion_slot = self._auto_document_insertion_slot(source, documents, selected_sources)
        if insertion_slot is None:
            self._show_temporary_status("Auto Move: no similarly named document found.")
            return
        moved = self._move_selected_documents_to_remaining_slot(
            insertion_slot,
            documents=documents,
            selected_sources=selected_sources,
        )
        if not moved:
            self._show_temporary_status("Auto Move: document is already near similarly named documents.")

    def _selected_document_move_context(self) -> tuple[list[dict[str, object]], list[object], list[int]] | None:
        if not isinstance(self.current_payload, dict):
            return None
        documents = self.current_payload.get("Documents")
        if not isinstance(documents, list):
            return None

        selected_sources = self._selected_document_sources()
        if not selected_sources:
            return None
        source_indexes = {
            id(document): index
            for index, document in enumerate(documents)
            if isinstance(document, dict)
        }
        selected_indexes = [
            source_indexes[id(source)]
            for source in selected_sources
            if id(source) in source_indexes
        ]
        if not selected_indexes:
            return None
        return selected_sources, documents, selected_indexes

    def _selected_document_sources(self) -> list[dict[str, object]]:
        selected_node_ids = set(self.documents_tree.selection())
        visible_node_ids = list(self.documents_tree.get_children(""))
        ordered_node_ids = [
            node_id
            for node_id in visible_node_ids
            if node_id in selected_node_ids
        ]
        if not ordered_node_ids and self._active_document_node_id:
            ordered_node_ids = [self._active_document_node_id]

        selected_sources: list[dict[str, object]] = []
        seen_source_ids: set[int] = set()
        for node_id in ordered_node_ids:
            details = self._document_node_details.get(node_id, {})
            document_ref = details.get("document_ref")
            source = document_ref.get("source") if isinstance(document_ref, dict) else None
            if not isinstance(source, dict):
                continue
            source_id = id(source)
            if source_id in seen_source_ids:
                continue
            seen_source_ids.add(source_id)
            selected_sources.append(source)
        return selected_sources

    def _visible_document_sources(self, documents: list[object]) -> list[dict[str, object]]:
        source_ids = {
            id(document)
            for document in documents
            if isinstance(document, dict)
        }
        sources: list[dict[str, object]] = []
        for node_id in self.documents_tree.get_children(""):
            details = self._document_node_details.get(node_id, {})
            document_ref = details.get("document_ref")
            source = document_ref.get("source") if isinstance(document_ref, dict) else None
            if isinstance(source, dict) and id(source) in source_ids:
                sources.append(source)
        return sources

    def _move_visible_document_selection(
        self,
        visible_sources: list[dict[str, object]],
        selected_sources: list[dict[str, object]],
        direction: int,
    ) -> list[dict[str, object]] | None:
        if direction == 0 or not visible_sources:
            return None
        selected_ids = {id(source) for source in selected_sources}
        if direction < 0:
            return self._move_visible_document_selection_up(visible_sources, selected_ids)
        return self._move_visible_document_selection_down(visible_sources, selected_ids)

    @staticmethod
    def _move_visible_document_selection_up(
        visible_sources: list[dict[str, object]],
        selected_ids: set[int],
    ) -> list[dict[str, object]] | None:
        reordered_sources = list(visible_sources)
        changed = False
        index = 0
        while index < len(reordered_sources):
            if id(reordered_sources[index]) not in selected_ids:
                index += 1
                continue
            start = index
            while index < len(reordered_sources) and id(reordered_sources[index]) in selected_ids:
                index += 1
            end = index
            if start > 0 and id(reordered_sources[start - 1]) not in selected_ids:
                previous_source = reordered_sources.pop(start - 1)
                reordered_sources.insert(end - 1, previous_source)
                changed = True
        return reordered_sources if changed else None

    @staticmethod
    def _move_visible_document_selection_down(
        visible_sources: list[dict[str, object]],
        selected_ids: set[int],
    ) -> list[dict[str, object]] | None:
        reordered_sources = list(visible_sources)
        changed = False
        index = len(reordered_sources) - 1
        while index >= 0:
            if id(reordered_sources[index]) not in selected_ids:
                index -= 1
                continue
            end = index + 1
            while index >= 0 and id(reordered_sources[index]) in selected_ids:
                index -= 1
            start = index + 1
            if end < len(reordered_sources) and id(reordered_sources[end]) not in selected_ids:
                next_source = reordered_sources.pop(end)
                reordered_sources.insert(start, next_source)
                changed = True
        return reordered_sources if changed else None

    def _apply_document_visible_order(
        self,
        documents: list[object],
        ordered_visible_sources: list[dict[str, object]],
        selected_sources: list[dict[str, object]],
    ) -> bool:
        visible_ids = {id(source) for source in ordered_visible_sources}
        current_visible_order = [
            id(document)
            for document in documents
            if isinstance(document, dict) and id(document) in visible_ids
        ]
        next_visible_order = [id(source) for source in ordered_visible_sources]
        if current_visible_order == next_visible_order:
            return False

        ordered_iterator = iter(ordered_visible_sources)
        for index, document in enumerate(documents):
            if isinstance(document, dict) and id(document) in visible_ids:
                documents[index] = next(ordered_iterator)
        self._sync_loaded_documents_order(documents)
        self._set_dirty(True)
        self._sync_document_tree_positions(documents, selected_sources)
        return True

    def _move_selected_documents_to_remaining_slot(
        self,
        insertion_slot: int,
        *,
        documents: list[object],
        selected_sources: list[dict[str, object]],
    ) -> bool:
        selected_ids = {id(source) for source in selected_sources}
        selected_documents = [
            document
            for document in documents
            if isinstance(document, dict) and id(document) in selected_ids
        ]
        remaining_documents = [
            document
            for document in documents
            if not (isinstance(document, dict) and id(document) in selected_ids)
        ]
        insertion_slot = max(0, min(insertion_slot, len(remaining_documents)))
        reordered_documents = (
            remaining_documents[:insertion_slot]
            + selected_documents
            + remaining_documents[insertion_slot:]
        )
        if [id(document) for document in documents] == [id(document) for document in reordered_documents]:
            return False
        documents[:] = reordered_documents
        self._sync_loaded_documents_order(documents)
        self._set_dirty(True)
        self._sync_document_tree_positions(documents, selected_sources)
        return True

    def _sync_loaded_documents_order(self, documents: list[object]) -> None:
        source_order = {
            id(document): index
            for index, document in enumerate(documents)
            if isinstance(document, dict)
        }
        self._loaded_documents.sort(
            key=lambda document: source_order.get(id(document.get("source")), len(source_order))
        )

    def _sync_document_tree_positions(
        self,
        documents: list[object],
        selected_sources: list[dict[str, object]],
    ) -> None:
        if self.document_view_mode != "flat":
            return

        source_order = {
            id(document): index
            for index, document in enumerate(documents)
            if isinstance(document, dict)
        }

        child_sources: list[tuple[str, dict[str, object]]] = []
        children = list(self.documents_tree.get_children(""))
        for child_id in children:
            details = self._document_node_details.get(child_id, {})
            document_ref = details.get("document_ref")
            child_source = document_ref.get("source") if isinstance(document_ref, dict) else None
            if isinstance(child_source, dict) and id(child_source) in source_order:
                child_sources.append((child_id, child_source))

        child_sources.sort(key=lambda item: source_order[id(item[1])])
        for visible_index, (child_id, _source) in enumerate(child_sources):
            self.documents_tree.move(child_id, "", visible_index)

        selected_ids = {id(source) for source in selected_sources}
        selected_node_ids = [
            child_id
            for child_id, source in child_sources
            if id(source) in selected_ids
        ]
        if not selected_node_ids:
            return
        if set(self.documents_tree.selection()) != set(selected_node_ids):
            self.documents_tree.selection_set(*selected_node_ids)
        focus_node_id = (
            self._active_document_node_id
            if self._active_document_node_id in selected_node_ids
            else selected_node_ids[0]
        )
        self.documents_tree.focus(focus_node_id)
        self.documents_tree.see(focus_node_id)

    def _auto_document_insertion_slot(
        self,
        source: dict[str, object],
        documents: list[object],
        selected_sources: list[dict[str, object]],
    ) -> int | None:
        selected_name = str(source.get("$$Id", "")).strip()
        if not selected_name:
            return None

        selected_ids = {id(source) for source in selected_sources}
        remaining = [
            document
            for document in documents
            if isinstance(document, dict) and id(document) not in selected_ids
        ]
        if not remaining:
            return None

        selected_tokens = self._document_name_tokens(selected_name)
        for prefix_length in range(len(selected_tokens) - 1, 0, -1):
            prefix = selected_tokens[:prefix_length]
            matching_indexes = [
                index
                for index, document in enumerate(remaining)
                if self._document_name_tokens(str(document.get("$$Id", "")))[:prefix_length] == prefix
            ]
            if matching_indexes:
                return matching_indexes[-1] + 1

        selected_normalized = self._normalize_document_name_for_move(selected_name)
        if len(selected_normalized) < 3:
            return None

        best_length = 0
        best_indexes: list[int] = []
        for index, document in enumerate(remaining):
            other_name = self._normalize_document_name_for_move(str(document.get("$$Id", "")))
            common_length = self._common_prefix_length(selected_normalized, other_name)
            if common_length > best_length:
                best_length = common_length
                best_indexes = [index]
            elif common_length == best_length and common_length > 0:
                best_indexes.append(index)

        if best_length < 3 or not best_indexes:
            return None
        return best_indexes[-1] + 1

    @staticmethod
    def _document_name_tokens(name: str) -> list[str]:
        return [
            token.casefold()
            for token in re.split(r"[^A-Za-z0-9]+", name)
            if token
        ]

    @staticmethod
    def _normalize_document_name_for_move(name: str) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "", name).casefold()

    @staticmethod
    def _common_prefix_length(first: str, second: str) -> int:
        limit = min(len(first), len(second))
        index = 0
        while index < limit and first[index] == second[index]:
            index += 1
        return index

    def add_content_to_selected_layout(self) -> None:
        details = self._layout_node_details.get(self._active_layout_node_id or "")
        if not details or str(details.get("node_kind", "")) != "layout":
            return
        layout = details.get("source_ref")
        if not isinstance(layout, dict):
            return
        contents = layout.get("Contents")
        if not isinstance(contents, list):
            contents = []
            layout["Contents"] = contents
        counter = len(contents) + 1
        content = {
            "$$Id": f"NewContent{counter}",
            "Descr": "",
            "Condition": "",
        }
        contents.append(content)
        self._touch_selected_document_updated()
        self._set_dirty(True)
        self._refresh_layouts_for_active_document()
        self._select_layout_node_for_source(content, preferred_kind="content")

    def _remove_selected_layout_item_event(self, _event: tk.Event) -> str:
        self.remove_selected_layout_item()
        return "break"

    def remove_selected_layout_item(self) -> None:
        node_id = self._active_layout_node_id
        if not node_id:
            return
        details = self._layout_node_details.get(node_id)
        if not details:
            return
        node_kind = str(details.get("node_kind", ""))
        if node_kind not in {"layout", "content", "iteration", "field", "condition"}:
            return
        source_ref = details.get("source_ref")
        if not isinstance(source_ref, dict):
            return

        item_text = str(self.layouts_tree.item(node_id, "text") or node_kind)
        message = f"Remove this {node_kind}?"
        if node_kind in {"layout", "content", "iteration"}:
            message = f"Remove this {node_kind} and all child items?"
        if not messagebox.askyesno("Remove Layout Item", f"{message}\n\n{item_text}"):
            return

        parent_node_id = self.layouts_tree.parent(node_id)
        parent_details = self._layout_node_details.get(parent_node_id, {}) if parent_node_id else {}
        parent_source = parent_details.get("source_ref")
        parent_kind = str(parent_details.get("node_kind", ""))
        next_selection: tuple[dict[str, object], str] | None = None

        removed = False
        if node_kind == "layout":
            removed, next_selection = self._remove_selected_layout(source_ref)
        elif node_kind == "content":
            removed = self._remove_selected_content(source_ref, parent_source)
            if isinstance(parent_source, dict):
                next_selection = (parent_source, "layout")
        elif node_kind == "iteration":
            removed = self._remove_selected_iteration(source_ref, parent_source)
            if isinstance(parent_source, dict):
                next_selection = (parent_source, "content")
        elif node_kind == "field":
            removed = self._remove_selected_iteration_field(source_ref, parent_source)
            if isinstance(parent_source, dict):
                next_selection = (parent_source, "iteration")
        elif node_kind == "condition":
            removed = self._remove_selected_condition(source_ref)
            if isinstance(parent_source, dict) and parent_kind:
                next_selection = (parent_source, parent_kind)

        if not removed:
            messagebox.showerror("Remove Layout Item", "Could not remove the selected layout item.")
            return

        self._touch_selected_document_updated()
        self._set_dirty(True)
        self._refresh_layouts_for_active_document()
        if next_selection is not None:
            self._select_layout_node_for_source(next_selection[0], preferred_kind=next_selection[1])

    def _remove_selected_layout(
        self,
        layout: dict[str, object],
    ) -> tuple[bool, tuple[dict[str, object], str] | None]:
        document_ref = self._get_selected_document_ref()
        if document_ref is None:
            return False, None
        doc_source = document_ref.get("source")
        if not isinstance(doc_source, dict):
            return False, None
        layouts = doc_source.get("Layouts")
        if not isinstance(layouts, list):
            return False, None
        index = self._index_of_identity(layouts, layout)
        if index < 0:
            return False, None
        layouts.pop(index)
        remaining_layouts = [item for item in layouts if isinstance(item, dict)]
        if not remaining_layouts:
            return True, None
        next_index = min(index, len(remaining_layouts) - 1)
        return True, (remaining_layouts[next_index], "layout")

    def _remove_selected_content(self, content: dict[str, object], parent_source: object) -> bool:
        if not isinstance(parent_source, dict):
            return False
        contents = self._contents_list_for_layout(parent_source)
        return self._remove_identity_from_list(contents, content)

    def _remove_selected_iteration(self, iteration: dict[str, object], parent_source: object) -> bool:
        if not isinstance(parent_source, dict):
            return False
        for key in ("Iteration", "iteration"):
            if parent_source.get(key) is iteration:
                parent_source.pop(key, None)
                return True
        return False

    def _remove_selected_iteration_field(self, field: dict[str, object], parent_source: object) -> bool:
        if not isinstance(parent_source, dict):
            return False
        fields = self._fields_list_for_iteration(parent_source)
        return self._remove_identity_from_list(fields, field)

    @staticmethod
    def _remove_selected_condition(source_ref: dict[str, object]) -> bool:
        if "Condition" not in source_ref:
            return False
        source_ref.pop("Condition", None)
        return True

    @staticmethod
    def _contents_list_for_layout(layout: dict[str, object]) -> list[object] | None:
        for key in ("Contents", "Content", "contents", "content"):
            value = layout.get(key)
            if isinstance(value, list):
                return value
        return None

    @staticmethod
    def _fields_list_for_iteration(iteration: dict[str, object]) -> list[object] | None:
        for key in ("Fields", "fields"):
            value = iteration.get(key)
            if isinstance(value, list):
                return value
        return None

    @staticmethod
    def _index_of_identity(items: list[object], target: object) -> int:
        for index, item in enumerate(items):
            if item is target:
                return index
        return -1

    @classmethod
    def _remove_identity_from_list(cls, items: list[object] | None, target: object) -> bool:
        if items is None:
            return False
        index = cls._index_of_identity(items, target)
        if index < 0:
            return False
        items.pop(index)
        return True

    def move_selected_layout(self, direction: int) -> None:
        details = self._layout_node_details.get(self._active_layout_node_id or "")
        if not details or str(details.get("node_kind", "")) != "layout":
            return
        layout = details.get("source_ref")
        if not isinstance(layout, dict):
            return
        document_ref = self._get_selected_document_ref()
        if document_ref is None:
            return
        doc_source = document_ref.get("source")
        if not isinstance(doc_source, dict):
            return
        layouts = doc_source.get("Layouts")
        if not isinstance(layouts, list):
            return
        index = -1
        for i, item in enumerate(layouts):
            if item is layout:
                index = i
                break
        if index < 0:
            return
        new_index = index + direction
        if new_index < 0 or new_index >= len(layouts):
            return
        layouts[index], layouts[new_index] = layouts[new_index], layouts[index]
        self._set_dirty(True)
        self._refresh_layouts_for_active_document()
        self._select_layout_node_for_source(layout, preferred_kind="layout")

    def add_iteration_to_selected_content(self) -> None:
        details = self._layout_node_details.get(self._active_layout_node_id or "")
        if not details or str(details.get("node_kind", "")) != "content":
            return
        content = details.get("source_ref")
        if not isinstance(content, dict):
            return
        iteration = content.get("Iteration")
        if not isinstance(iteration, dict):
            iteration = {
                "$$Id": "NewIteration1",
                "Descr": "",
                "Condition": "",
                "Path": "$",
                "Type": "Array",
                "Fields": [],
            }
            content["Iteration"] = iteration
        self._touch_selected_document_updated()
        self._set_dirty(True)
        self._refresh_layouts_for_active_document()
        self._select_layout_node_for_source(iteration, preferred_kind="iteration")

    def add_field_to_selected_iteration(self) -> None:
        details = self._layout_node_details.get(self._active_layout_node_id or "")
        if not details or str(details.get("node_kind", "")) != "iteration":
            return
        iteration = details.get("source_ref")
        if not isinstance(iteration, dict):
            return
        fields = iteration.get("Fields")
        if not isinstance(fields, list):
            fields = []
            iteration["Fields"] = fields
        counter = len(fields) + 1
        field = {
            "Name": f"NewIterField{counter}",
            "Descr": "",
            "Mandatory": False,
            "Path": "$",
            "Condition": "",
        }
        fields.append(field)
        self._touch_selected_document_updated()
        self._set_dirty(True)
        self._refresh_layouts_for_active_document()
        self._select_layout_node_for_source(field, preferred_kind="field")

    def _select_document_node_for_source(self, source_ref: dict[str, object]) -> None:
        for node_id, details in self._document_node_details.items():
            doc_ref = details.get("document_ref")
            if not isinstance(doc_ref, dict):
                continue
            if doc_ref.get("source") is source_ref:
                self.documents_tree.selection_set(node_id)
                self.documents_tree.focus(node_id)
                self.documents_tree.see(node_id)
                self._active_document_node_id = node_id
                self._set_document_details(details)
                self._render_layouts_for_document(details)
                self._update_document_context_buttons()
                return

    def _select_layout_node_for_source(self, source_ref: dict[str, object], preferred_kind: str = "") -> None:
        fallback_node_id = ""
        for node_id, details in self._layout_node_details.items():
            if details.get("source_ref") is not source_ref:
                continue
            kind = str(details.get("node_kind", ""))
            if preferred_kind and kind == preferred_kind:
                self.layouts_tree.selection_set(node_id)
                self.layouts_tree.focus(node_id)
                self.layouts_tree.see(node_id)
                self._active_layout_node_id = node_id
                self._set_layout_details(details)
                self._update_layout_context_buttons()
                return
            if not fallback_node_id:
                fallback_node_id = node_id
        if fallback_node_id:
            details = self._layout_node_details.get(fallback_node_id)
            if not details:
                return
            self.layouts_tree.selection_set(fallback_node_id)
            self.layouts_tree.focus(fallback_node_id)
            self.layouts_tree.see(fallback_node_id)
            self._active_layout_node_id = fallback_node_id
            self._set_layout_details(details)
            self._update_layout_context_buttons()

    def _clear_documents_filter(self) -> None:
        self.documents_filter_var.set("")

    def _clear_fields_filter(self) -> None:
        self.fields_filter_var.set("")

    def _on_field_tree_select(self, _event: tk.Event) -> None:
        selected = self.fields_tree.selection()
        if not selected:
            self._active_field_node_id = None
            self._clear_field_details()
            return
        node_id = selected[0]
        details = self._field_node_details.get(node_id)
        if not details:
            self._active_field_node_id = None
            self._clear_field_details()
            return
        self._active_field_node_id = node_id
        self._set_field_details(details)

    def _set_field_details(self, field: dict[str, object]) -> None:
        self._updating_field_form = True
        self.field_name_text.set(str(field.get("name", "-")))
        self.edit_field_name_var.set(str(field.get("name", "")))
        mandatory = bool(field.get("mandatory"))
        self.field_mandatory_text.set("true" if mandatory else "false")
        self.edit_field_mandatory_var.set(mandatory)
        self.field_path_text.set(str(field.get("path", "-")))
        self.edit_field_path_var.set(str(field.get("path", "")))
        self.field_true_path_text.set(str(field.get("true_path", "-")))
        self.field_updated_text.set(str(field.get("updated", "-")))
        self.field_descr_text.set(str(field.get("descr", "")))
        mapped_values = field.get("mapped_values")
        if isinstance(mapped_values, list) and mapped_values:
            self.field_mapped_value_text.set(self._format_field_mapped_value(field, mapped_values))
        else:
            self.field_mapped_value_text.set("-")
        segments = field.get("path_segments")
        if isinstance(segments, list) and segments:
            self.field_hierarchy_text.set(" > ".join(str(segment) for segment in segments))
        else:
            self.field_hierarchy_text.set("-")
        self._updating_field_form = False

    def _clear_field_details(self) -> None:
        self._updating_field_form = True
        self.field_name_text.set("(no field selected)")
        self.field_mandatory_text.set("-")
        self.field_path_text.set("-")
        self.field_true_path_text.set("-")
        self.field_updated_text.set("-")
        self.field_descr_text.set("")
        self.field_mapped_value_text.set("-")
        self.edit_field_name_var.set("")
        self.edit_field_mandatory_var.set(False)
        self.edit_field_path_var.set("")
        self.field_hierarchy_text.set("-")
        self._updating_field_form = False

    def _set_document_details(self, document: dict[str, object]) -> None:
        self._updating_document_form = True
        self.document_name_text.set(str(document.get("name", "-")))
        self.edit_document_name_var.set(str(document.get("name", "")))
        triggered = bool(document.get("triggered"))
        warnings = document.get("condition_warnings")
        warning_lines = [str(warning) for warning in warnings] if isinstance(warnings, list) else []
        trigger_text = "Y" if triggered else "N"
        if warning_lines:
            trigger_text += "\nComms-compatible condition warnings:"
            trigger_text += "\n" + "\n".join(f"- {warning}" for warning in warning_lines[:5])
            if len(warning_lines) > 5:
                trigger_text += f"\n- ... and {len(warning_lines) - 5} more"
        self.document_triggered_text.set(trigger_text)
        self._set_document_match_details(document)
        updated = str(document.get("updated", "")).strip()
        self.document_updated_text.set(updated if updated else "-")
        descr = str(document.get("descr", "")).strip()
        self.document_descr_edit_text.set(descr)
        condition = str(document.get("condition", "")).strip()
        self._set_text_widget_value(self.document_condition_widget, condition)
        self._update_document_triggered_visibility()
        self._apply_document_details_section_visibility()
        self._updating_document_form = False

    def _clear_document_details(self) -> None:
        self._updating_document_form = True
        self._active_document_node_id = None
        self.document_name_text.set("(no document selected)")
        self.document_triggered_text.set("-")
        self.edit_document_name_var.set("")
        self._set_text_widget_value(self.document_condition_widget, "")
        self._clear_document_match_details()
        self.document_descr_edit_text.set("")
        self.document_updated_text.set("-")
        self._update_document_triggered_visibility()
        self._apply_document_details_section_visibility()
        self._updating_document_form = False

    def _format_document_match_details(self, document: dict[str, object]) -> str:
        if self.current_data_payload is None:
            return "(map a data file to see match diagnostics)"
        breakdown = document.get("condition_breakdown")
        if isinstance(breakdown, list) and breakdown:
            return "\n".join(str(line) for line in breakdown)
        if bool(document.get("triggered")):
            return "PASS Document condition matched."
        return "No match diagnostics recorded."

    def _set_document_match_details(self, document: dict[str, object]) -> None:
        widget = getattr(self, "document_match_details_widget", None)
        if not isinstance(widget, tk.Text):
            return

        source_document = document.get("document_ref")
        if not isinstance(source_document, dict):
            source_document = document
        details = source_document.get("condition_match_details")
        if not isinstance(details, list) or not details:
            self._set_readonly_text_widget_value(widget, self._format_document_match_details(source_document))
            return

        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        for tag_name in widget.tag_names():
            if tag_name.startswith("match_detail_"):
                widget.tag_delete(tag_name)

        for index, detail in enumerate(details):
            if not isinstance(detail, dict):
                continue
            passed = bool(detail.get("passed"))
            status = "PASS" if passed else "FAIL"
            label = str(detail.get("label", "")).strip() or "(unnamed clause)"
            line_start = widget.index(tk.INSERT)
            widget.insert(tk.INSERT, f"{status} {label}\n", "match_pass" if passed else "match_fail")
            line_end = widget.index(tk.INSERT)
            tooltip_text = self._format_match_detail_tooltip(detail)
            if tooltip_text:
                detail_tag = f"match_detail_{index}"
                widget.tag_add(detail_tag, line_start, line_end)
                widget.tag_bind(detail_tag, "<Enter>", lambda event, text=tooltip_text: self._show_tooltip(event, text))
                widget.tag_bind(detail_tag, "<Leave>", lambda _event: self._hide_tooltip())
                widget.tag_bind(detail_tag, "<ButtonPress>", lambda _event: self._hide_tooltip())

        widget.configure(state=tk.DISABLED)

    def _clear_document_match_details(self) -> None:
        widget = getattr(self, "document_match_details_widget", None)
        if isinstance(widget, tk.Text):
            self._set_readonly_text_widget_value(widget, "")

    def _format_match_detail_tooltip(self, detail: dict[str, object]) -> str:
        lines = detail.get("details")
        if not isinstance(lines, list) or not lines:
            return "Clause passed."
        return "\n".join(
            self._truncate_ui_text(str(line), 240)
            for line in lines[:12]
        )

    def _on_document_name_commit(self, _event: tk.Event | None = None) -> None:
        self._apply_document_form_change(name=self.edit_document_name_var.get())

    def _on_document_name_changed(self, _event: tk.Event) -> None:
        self._apply_document_form_change(name=self.edit_document_name_var.get())

    def _on_document_condition_changed(self, _event: tk.Event) -> None:
        if not hasattr(self, "document_condition_widget"):
            return
        value = self.document_condition_widget.get("1.0", tk.END).rstrip("\n")
        self._apply_document_form_change(condition=value)

    def _on_document_descr_changed(self, *_args: object) -> None:
        self._apply_document_form_change(descr=self.document_descr_edit_text.get())

    def _apply_document_form_change(
        self,
        *,
        name: str | None = None,
        condition: str | None = None,
        descr: str | None = None,
    ) -> None:
        if self._updating_document_form:
            return
        if not self._active_document_node_id:
            return
        details = self._document_node_details.get(self._active_document_node_id)
        if not details:
            return
        document = details.get("document_ref")
        if not isinstance(document, dict):
            return

        changed = False
        condition_changed = False
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if name is not None:
            normalized_name = name.strip()
            if normalized_name and normalized_name != str(document.get("name", "")):
                document["name"] = normalized_name
                details["name"] = normalized_name
                changed = True

        if condition is not None:
            normalized_condition = condition.strip()
            if normalized_condition != str(document.get("condition", "")):
                document["condition"] = normalized_condition
                details["condition"] = normalized_condition
                changed = True
                condition_changed = True

        if descr is not None and descr != str(document.get("descr", "")):
            document["descr"] = descr
            details["descr"] = descr
            changed = True

        if not changed:
            return

        document["updated"] = now_text
        details["updated"] = now_text
        self._sync_document_to_payload(document)
        self._set_dirty(True)
        if condition_changed and self.current_data_payload is not None:
            self._refresh_document_condition_mapping(document)
            details["triggered"] = bool(document.get("triggered"))
            details["condition_warnings"] = list(document.get("condition_warnings", [])) if isinstance(
                document.get("condition_warnings"),
                list,
            ) else []
            details["condition_breakdown"] = list(document.get("condition_breakdown", [])) if isinstance(
                document.get("condition_breakdown"),
                list,
            ) else []
            details["condition_match_details"] = list(document.get("condition_match_details", [])) if isinstance(
                document.get("condition_match_details"),
                list,
            ) else []
            self._set_document_match_details(details)

        if name is not None and self._active_document_node_id:
            self.documents_tree.item(self._active_document_node_id, text=str(document.get("name", "")))

        self._updating_document_form = True
        self.document_updated_text.set(now_text)
        self._updating_document_form = False

    def _sync_active_document_form_to_model(self) -> None:
        if self._updating_document_form:
            return
        if not self._active_document_node_id:
            return
        if not hasattr(self, "document_condition_widget"):
            return
        self._apply_document_form_change(name=self.edit_document_name_var.get())
        condition_value = self.document_condition_widget.get("1.0", tk.END).rstrip("\n")
        self._apply_document_form_change(condition=condition_value)
        self._apply_document_form_change(descr=self.document_descr_edit_text.get())

    @staticmethod
    def _set_text_widget_value(widget: tk.Text, value: str) -> None:
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)

    @staticmethod
    def _sync_document_to_payload(document: dict[str, object]) -> None:
        source = document.get("source")
        if not isinstance(source, dict):
            return
        id_value = str(document.get("name", ""))
        updated_value = str(document.get("updated", ""))
        descr_value = str(document.get("descr", ""))
        condition_value = str(document.get("condition", ""))

        source["$$Id"] = id_value
        source["Updated"] = updated_value
        source["Descr"] = descr_value
        source["Condition"] = condition_value

        ordered: dict[str, object] = {
            "$$Id": source.get("$$Id", id_value),
            "Updated": source.get("Updated", updated_value),
            "Descr": source.get("Descr", descr_value),
        }
        for key, value in list(source.items()):
            if key in ordered:
                continue
            ordered[key] = value
        source.clear()
        source.update(ordered)

    def _collect_atomic_condition_clauses(self, expression: str) -> list[str]:
        expr = self._strip_outer_parens(expression)
        if not expr:
            return []
        or_parts = self._split_top_level_operator(expr, "||")
        if len(or_parts) > 1:
            clauses: list[str] = []
            for part in or_parts:
                clauses.extend(self._collect_atomic_condition_clauses(part))
            return clauses
        and_parts = self._split_top_level_operator(expr, "&&")
        if len(and_parts) > 1:
            clauses = []
            for part in and_parts:
                clauses.extend(self._collect_atomic_condition_clauses(part))
            return clauses
        return [expr]

    def _evaluate_atomic_condition_with_detail(
        self,
        expression: str,
        data_payload: object,
        *,
        comms_compatible: bool = True,
    ) -> tuple[bool, str]:
        expr = self._strip_outer_parens(expression)
        if not expr:
            return True, "empty expression"

        empty_match = re.match(r"^(.*?)\s+empty\s+(true|false)\s*$", expr, flags=re.IGNORECASE)
        if empty_match:
            path = empty_match.group(1).strip()
            expect_empty = empty_match.group(2).lower() == "true"
            normalized_path = self._normalize_condition_path(path)
            parent_path = self._get_empty_check_parent_path(normalized_path)
            parent_values = self._extract_values_by_path(data_payload, parent_path)
            if len(parent_values) == 0:
                if comms_compatible and expect_empty and self._path_has_filter(normalized_path):
                    return (
                        False,
                        "filtered parent path missing: "
                        f"{parent_path}; Comms-compatible check treats this as not empty",
                    )
                passed = expect_empty
                return passed, f"parent path missing: {parent_path}"
            full_values = self._extract_values_by_path(data_payload, normalized_path)
            is_empty = len(full_values) == 0
            passed = is_empty if expect_empty else not is_empty
            return passed, f"values={self._format_mapped_nodeset_preview(full_values)}"

        size_match = self._find_top_level_word_operator(expr, "size")
        if size_match is not None:
            path, expected_size = size_match
            values = self._evaluate_condition_operand(data_payload, path)
            expected_values = self._evaluate_condition_operand(data_payload, expected_size)
            passed = self._compare_condition_operand_values([len(values)], "==", expected_values)
            return (
                passed,
                f"size={len(values)} "
                f"values={self._format_mapped_nodeset_preview(values)} "
                f"expected={self._format_mapped_nodeset_preview(expected_values)}",
            )

        comparison = self._find_top_level_comparison(expr)
        if comparison is not None:
            lhs, operator, rhs = comparison
            left_values = self._evaluate_condition_operand(data_payload, lhs)
            right_values = self._evaluate_condition_operand(data_payload, rhs)
            if operator in {"==", "!="}:
                missing_result = self._compare_missing_condition_operand_values(
                    left_values,
                    operator,
                    right_values,
                    comms_compatible=comms_compatible,
                )
                if missing_result is not None:
                    passed, side, present_values = missing_result
                    if operator == "==" and passed:
                        return True, f"{side} missing; treated as null-equivalent"
                    if operator == "!=" and passed:
                        return (
                            True,
                            f"{side} missing; treated as not-equal to "
                            f"{self._format_mapped_nodeset_preview(present_values)}",
                        )
                    return (
                        False,
                        f"{side} missing; treated as null-equivalent to "
                        f"{self._format_mapped_nodeset_preview(present_values)}",
                    )
            if not left_values or not right_values:
                return False, f"left={len(left_values)} right={len(right_values)}"
            passed = self._compare_condition_operand_values(left_values, operator, right_values)
            return (
                passed,
                f"left={self._format_mapped_nodeset_preview(left_values)} "
                f"right={self._format_mapped_nodeset_preview(right_values)}",
            )

        values = self._evaluate_condition_operand(data_payload, expr)
        passed = len(values) > 0
        return passed, f"values={self._format_mapped_nodeset_preview(values)}"

    def _on_field_name_changed(self, *_args: object) -> None:
        self._apply_field_form_change(name=self.edit_field_name_var.get())

    def _on_field_mandatory_changed(self, *_args: object) -> None:
        self._apply_field_form_change(mandatory=bool(self.edit_field_mandatory_var.get()))

    def _on_field_path_changed(self, *_args: object) -> None:
        self._apply_field_form_change(path=self.edit_field_path_var.get())

    def _on_field_path_commit(self, _event: tk.Event | None = None) -> None:
        self._apply_field_form_change(path=self.edit_field_path_var.get())

    def _on_field_descr_changed(self, *_args: object) -> None:
        self._apply_field_form_change(descr=self.field_descr_text.get())

    def _apply_field_form_change(
        self,
        *,
        name: str | None = None,
        mandatory: bool | None = None,
        path: str | None = None,
        descr: str | None = None,
    ) -> bool:
        if self._updating_field_form:
            return True
        if not self._active_field_node_id:
            return True
        field = self._field_node_details.get(self._active_field_node_id)
        if not field:
            return True

        changed = False
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if name is not None:
            normalized_name = name.strip()
            if normalized_name and normalized_name != str(field.get("name", "")):
                field["name"] = normalized_name
                changed = True

        if mandatory is not None and mandatory != bool(field.get("mandatory")):
            field["mandatory"] = mandatory
            changed = True

        if path is not None:
            normalized_path = self._normalize_path_expression(path.strip())
            if normalized_path and normalized_path != str(field.get("path", "")):
                valid, reason = self._validate_field_path(normalized_path)
                if not valid:
                    messagebox.showerror(
                        "Invalid Field Path",
                        "Path must be a valid JSONPath expression.\n\n"
                        f"Value: {normalized_path}\n"
                        f"Details: {reason}",
                    )
                    self._updating_field_form = True
                    self.edit_field_path_var.set(str(field.get("path", "")))
                    self._updating_field_form = False
                    return False
                field["path"] = normalized_path
                field["true_path"] = self._normalize_true_path(normalized_path)
                field["path_segments"] = self._path_to_segments(str(field["true_path"]))
                changed = True

        if descr is not None and descr != str(field.get("descr", "")):
            field["descr"] = descr
            changed = True

        if not changed:
            return True

        field["updated"] = now_text
        if self.current_data_payload is not None:
            field["mapped_values"] = self._extract_values_by_path(
                self.current_data_payload,
                str(field.get("true_path") or field.get("path") or ""),
            )
        self._sync_field_to_payload(field)
        self._set_dirty(True)
        self._render_fields_tree(selected_field=field)
        return True

    def _sync_field_to_payload(self, field: dict[str, object]) -> None:
        source = field.get("source")
        if not isinstance(source, dict):
            return
        name_value = str(field.get("name", ""))
        updated_value = str(field.get("updated", ""))
        descr_value = str(field.get("descr", ""))
        mandatory_value = bool(field.get("mandatory", False))
        path_value = self._normalize_path_expression(str(field.get("path", "")))
        field["path"] = path_value

        source["Name"] = name_value
        source["Updated"] = updated_value
        source["Descr"] = descr_value
        source["Mandatory"] = mandatory_value
        source["Path"] = path_value

        ordered: dict[str, object] = {
            "Name": source.get("Name", name_value),
            "Updated": source.get("Updated", updated_value),
            "Descr": source.get("Descr", descr_value),
            "Mandatory": source.get("Mandatory", mandatory_value),
            "Path": source.get("Path", path_value),
        }
        for key, value in list(source.items()):
            if key in ordered:
                continue
            ordered[key] = value
        source.clear()
        source.update(ordered)

    def _validate_field_path(self, path: str) -> tuple[bool, str]:
        candidate = path.strip()
        if not candidate:
            return False, "Path is empty."
        if not candidate.startswith("$"):
            return False, "Path must start with '$'."
        parse_candidate = self._normalize_path_expression(candidate)
        if not self._is_balanced_parenthesized(parse_candidate):
            return False, "Unbalanced brackets/parentheses/quotes."

        true_path = self._normalize_true_path(parse_candidate).strip()
        if not true_path or not true_path.startswith("$"):
            return False, "Could not derive a valid JSONPath from the expression."
        if not self._is_supported_jsonpath_segments(true_path):
            return False, f"Unsupported JSONPath syntax in resolved path: {true_path}"
        return True, ""

    def _is_supported_jsonpath_segments(self, path: str) -> bool:
        expression = path.strip()
        if expression == "$":
            return True
        if expression.startswith("$.."):
            tail = expression[3:].strip()
            if not tail:
                return False
            expression = "$." + tail
        segments = self._path_to_segments(expression)
        if not segments or segments[0] != "$":
            return False
        for segment in segments[1:]:
            if not self._is_supported_jsonpath_segment(str(segment)):
                return False
        return True

    def _is_supported_jsonpath_segment(self, segment: str) -> bool:
        text = segment.strip()
        if not text:
            return False
        base, brackets = self._split_path_segment(text)
        if "[" in text and not brackets:
            return False
        if base and base != "*" and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", base):
            return False
        if not base and not brackets:
            return False
        for bracket in brackets:
            content = bracket[1:-1].strip()
            if not content:
                return False
            if content == "*":
                continue
            if content.startswith("?(") and content.endswith(")"):
                continue
            if (content.startswith("'") and content.endswith("'")) or (
                content.startswith('"') and content.endswith('"')
            ):
                continue
            try:
                int(content)
                continue
            except ValueError:
                return False
        return True

    def _set_dirty(self, dirty: bool) -> None:
        if self.is_dirty == dirty:
            return
        self.is_dirty = dirty
        if self.current_file_path:
            file_name = os.path.basename(self.current_file_path)
            marker = " *" if self.is_dirty else ""
            self.root.title(f"ATool - {file_name}{marker}")
        else:
            self.root.title("ATool" + (" *" if self.is_dirty else ""))

    def _bind_shortcuts(self) -> None:
        if self._is_macos():
            self.root.bind_all("<Command-o>", self._open_event)
            self.root.bind_all("<Command-O>", self._open_event)
            self.root.bind_all("<Command-s>", self._save_event)
            self.root.bind_all("<Command-S>", self._save_event)
            self.root.bind_all("<Command-m>", self._map_event)
            self.root.bind_all("<Command-M>", self._map_event)
            self.root.bind_all("<Command-p>", self._preview_event)
            self.root.bind_all("<Command-P>", self._preview_event)
            self.root.bind_all("<Command-Shift-M>", self._convert_and_map_event)
            self.root.bind_all("<Command-u>", self._update_shared_event)
            self.root.bind_all("<Command-Shift-U>", self._publish_to_comms_event)
        else:
            self.root.bind_all("<Alt-o>", self._open_event)
            self.root.bind_all("<Alt-O>", self._open_event)
            self.root.bind_all("<Alt-s>", self._save_event)
            self.root.bind_all("<Alt-S>", self._save_event)
            self.root.bind_all("<Alt-m>", self._map_event)
            self.root.bind_all("<Alt-M>", self._map_event)
            self.root.bind_all("<Control-p>", self._preview_event)
            self.root.bind_all("<Control-P>", self._preview_event)
            self.root.bind_all("<Control-Shift-M>", self._convert_and_map_event)
            self.root.bind_all("<Control-u>", self._update_shared_event)
            self.root.bind_all("<Control-Shift-U>", self._publish_to_comms_event)

    def _open_event(self, event: tk.Event) -> str:
        self.open_occs_package()
        return "break"

    def _save_event(self, event: tk.Event) -> str:
        self.save_assembly_template()
        return "break"

    def _map_event(self, event: tk.Event) -> str:
        self.map_data_file()
        return "break"

    def _preview_event(self, event: tk.Event) -> str:
        self.preview_occs_package()
        return "break"

    def _convert_and_map_event(self, event: tk.Event) -> str:
        self.convert_and_map_data_file()
        return "break"

    def _update_shared_event(self, event: tk.Event) -> str:
        self.update_shared_occs_package()
        return "break"

    def _publish_to_comms_event(self, event: tk.Event) -> str:
        self.publish_occs_package_to_comms()
        return "break"

    def open_assembly_template(self) -> None:
        if not self._prompt_save_if_dirty():
            return
        filetypes = [
            ("Assembly Template JSON", "*.json"),
            ("Assembly Template Files", "*.json *.yaml *.yml *.xml *.txt"),
            ("All Files", "*.*"),
        ]

        file_path = filedialog.askopenfilename(
            title="Open Raw AT",
            filetypes=filetypes,
        )

        if file_path:
            self._load_assembly_template(file_path)

    def open_occs_package(self) -> None:
        if self._occs_operation_in_progress:
            messagebox.showinfo("Package", "A package operation is already in progress.")
            return
        if not self._prompt_save_if_dirty():
            return
        workspace_dir = self._ensure_occs_shared_workspace_dir()
        if workspace_dir is None:
            return

        entries = self._list_shared_package_versions(workspace_dir)
        if not entries:
            if messagebox.askyesno(
                "Open Package",
                "No package versions were found in the shared package folder.\n\n"
                "Retrieve a package version from Comms now?",
            ):
                self.list_occs_packages_from_comms()
            return

        self._open_shared_package_selection_dialog(entries)

    def list_occs_packages_from_comms(self) -> None:
        if self._occs_operation_in_progress:
            messagebox.showinfo("Get Packages from Comms", "An OCCS operation is already in progress.")
            return
        self._run_occs_json_command_async(
            [
                "package",
                "list",
                "--timeout",
                str(self.OCCS_SPECIFIC_VERSION_TIMEOUT_MS),
            ],
            "Listing Comms packages...",
            lambda result: self._open_occs_package_list_dialog(self._normalize_occs_packages(result)),
            on_failure=lambda error: messagebox.showerror("Get Packages from Comms", str(error)),
        )

    def open_occs_package_bundle(self) -> None:
        if not self._prompt_save_if_dirty():
            return
        selected_dir = filedialog.askdirectory(
            title="Open Local Package",
            initialdir=self._get_occs_work_dir() or None,
        )
        if not selected_dir:
            return
        self._load_occs_bundle(selected_dir)

    def clean_local_occs_packages(self) -> None:
        work_dir = Path(os.path.expanduser(self._get_occs_work_dir()))
        if not work_dir.exists() or not work_dir.is_dir():
            messagebox.showinfo("Clean Local Packages", f"Local package folder does not exist:\n{work_dir}")
            return

        entries = self._local_occs_cleanup_entries(work_dir)
        if not entries:
            messagebox.showinfo("Clean Local Packages", f"No local package bundles were found in:\n{work_dir}")
            return

        self._open_local_occs_cleanup_dialog(work_dir, entries)

    def _open_local_occs_cleanup_dialog(
        self,
        work_dir: Path,
        entries: list[dict[str, object]],
    ) -> None:
        dialog = self._create_toplevel(self.root)
        dialog.title("Clean Local Packages")
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.grab_set()

        container = ttk.Frame(dialog, padding=14)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        summary_var = tk.StringVar(value="")
        ttk.Label(
            container,
            textvariable=summary_var,
            wraplength=920,
            justify=tk.LEFT,
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        tree = ttk.Treeview(
            container,
            columns=("selected", "package", "version", "modified", "age", "size", "status", "folder"),
            show="headings",
            height=min(max(len(entries), 8), 18),
        )
        headings = {
            "selected": "Delete",
            "package": "Package",
            "version": "Version",
            "modified": "Modified",
            "age": "Age",
            "size": "Size",
            "status": "Status",
            "folder": "Folder",
        }
        widths = {
            "selected": 60,
            "package": 150,
            "version": 90,
            "modified": 150,
            "age": 70,
            "size": 80,
            "status": 210,
            "folder": 320,
        }
        for column, heading in headings.items():
            tree.heading(column, text=heading)
            tree.column(column, width=widths[column], stretch=column in {"status", "folder"})
        tree.grid(row=1, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        item_to_entry: dict[str, dict[str, object]] = {}

        def _selected_entries() -> list[dict[str, object]]:
            return [
                entry
                for entry in entries
                if bool(entry.get("selected")) and not bool(entry.get("protected"))
            ]

        def _render_rows() -> None:
            item_to_entry.clear()
            tree.delete(*tree.get_children())
            for entry in entries:
                selected_text = "Yes" if bool(entry.get("selected")) else ""
                item_id = tree.insert(
                    "",
                    tk.END,
                    values=(
                        selected_text,
                        str(entry.get("package", "")),
                        str(entry.get("version", "")),
                        str(entry.get("modified_text", "")),
                        str(entry.get("age_text", "")),
                        str(entry.get("size_text", "")),
                        str(entry.get("status", "")),
                        str(entry.get("folder", "")),
                    ),
                )
                item_to_entry[item_id] = entry
            selected_count = len(_selected_entries())
            removable_count = sum(1 for entry in entries if not bool(entry.get("protected")))
            total_size = sum(
                int(entry.get("size_bytes", 0))
                for entry in entries
                if bool(entry.get("selected")) and not bool(entry.get("protected"))
            )
            summary_var.set(
                f"Local package folder: {work_dir}\n"
                f"Default cleanup selects removable bundles at least {self.OCCS_LOCAL_CLEANUP_DEFAULT_DAYS} days old. "
                f"Selected: {selected_count} of {removable_count} removable, {self._format_bytes(total_size)}."
            )

        def _toggle_selected_row() -> None:
            selection = tree.selection()
            if not selection:
                return
            entry = item_to_entry.get(selection[0])
            if not entry or bool(entry.get("protected")):
                return
            entry["selected"] = not bool(entry.get("selected"))
            _render_rows()

        def _select_old() -> None:
            for entry in entries:
                entry["selected"] = bool(entry.get("default_selected"))
            _render_rows()

        def _select_all_removable() -> None:
            for entry in entries:
                entry["selected"] = not bool(entry.get("protected"))
            _render_rows()

        def _clear_selection() -> None:
            for entry in entries:
                entry["selected"] = False
            _render_rows()

        def _delete_selected() -> None:
            nonlocal entries
            selected = _selected_entries()
            if not selected:
                messagebox.showinfo("Clean Local Packages", "Select at least one removable local package folder.", parent=dialog)
                return
            total_size = sum(int(entry.get("size_bytes", 0)) for entry in selected)
            if not messagebox.askyesno(
                "Clean Local Packages",
                f"Delete {len(selected)} local package folder(s)?\n\n"
                f"Estimated space: {self._format_bytes(total_size)}\n\n"
                "This cannot be undone.",
                parent=dialog,
            ):
                return

            errors: list[str] = []
            deleted_count = 0
            for entry in selected:
                path = entry.get("path")
                if not isinstance(path, Path) or not self._is_direct_child_directory(path, work_dir):
                    errors.append(f"Skipped unsafe path: {path}")
                    continue
                try:
                    shutil.rmtree(path)
                    deleted_count += 1
                except OSError as error:
                    errors.append(f"{path.name}: {error}")

            self._show_temporary_status(f"Cleaned {deleted_count} local package folder(s)", duration_ms=5000)
            if errors:
                messagebox.showwarning(
                    "Clean Local Packages",
                    "Some local package folders could not be deleted:\n\n" + "\n".join(errors[:12]),
                    parent=dialog,
                )
            entries = self._local_occs_cleanup_entries(work_dir)
            if not entries:
                dialog.destroy()
                messagebox.showinfo("Clean Local Packages", "No local package bundles remain.")
                return
            _render_rows()

        tree.bind("<Double-1>", lambda _event: _toggle_selected_row())
        tree.bind("<space>", lambda _event: (_toggle_selected_row(), "break")[1])

        buttons = ttk.Frame(container)
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Close", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Toggle", command=_toggle_selected_row).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(buttons, text="Select Old", command=_select_old).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(buttons, text="Select All Removable", command=_select_all_removable).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(buttons, text="Clear", command=_clear_selection).grid(row=0, column=4, padx=(0, 8))
        ttk.Button(buttons, text="Clean Selected", command=_delete_selected).grid(row=0, column=5)

        _render_rows()
        dialog.update_idletasks()
        width = max(dialog.winfo_width(), 1100)
        height = max(dialog.winfo_height(), 480)
        x_pos = self.root.winfo_x() + max((self.root.winfo_width() - width) // 2, 0)
        y_pos = self.root.winfo_y() + max((self.root.winfo_height() - height) // 2, 0)
        dialog.geometry(f"{width}x{height}+{x_pos}+{y_pos}")

    def _local_occs_cleanup_entries(self, work_dir: Path) -> list[dict[str, object]]:
        locked_bundle_dirs = self._active_shared_lock_bundle_dirs()
        current_bundle_dir = self._resolved_path(Path(self.current_occs_bundle_dir)) if self.current_occs_bundle_dir else None
        now = time.time()
        entries: list[dict[str, object]] = []
        for bundle_dir in sorted(work_dir.iterdir(), key=lambda item: item.name.lower()):
            if not bundle_dir.is_dir() or not (bundle_dir / "occs-package.json").exists():
                continue
            if not self._is_direct_child_directory(bundle_dir, work_dir):
                continue
            try:
                manifest = self._read_occs_manifest(str(bundle_dir))
                package_name = self._occs_manifest_package_short_name(manifest) or "(unknown)"
                version_name = self._occs_manifest_version_short_name(manifest) or "(unknown)"
            except ValueError:
                package_name = "(unreadable)"
                version_name = "(unreadable)"
            resolved_dir = self._resolved_path(bundle_dir)
            modified_ts = self._directory_modified_time(bundle_dir)
            age_days = max(0.0, (now - modified_ts) / 86400)
            size_bytes = self._directory_size_bytes(bundle_dir)
            protected_reason = ""
            if current_bundle_dir is not None and resolved_dir == current_bundle_dir:
                protected_reason = "Current open package"
            elif resolved_dir in locked_bundle_dirs:
                protected_reason = "Referenced by active shared lock"
            default_selected = not protected_reason and age_days >= self.OCCS_LOCAL_CLEANUP_DEFAULT_DAYS
            entries.append(
                {
                    "path": bundle_dir,
                    "folder": bundle_dir.name,
                    "package": package_name,
                    "version": version_name,
                    "modified_ts": modified_ts,
                    "modified_text": datetime.fromtimestamp(modified_ts).strftime("%Y-%m-%d %H:%M"),
                    "age_days": age_days,
                    "age_text": f"{int(age_days)}d",
                    "size_bytes": size_bytes,
                    "size_text": self._format_bytes(size_bytes),
                    "protected": bool(protected_reason),
                    "status": protected_reason or ("Old cleanup candidate" if default_selected else "Removable"),
                    "default_selected": default_selected,
                    "selected": default_selected,
                }
            )
        entries.sort(key=lambda entry: (bool(entry.get("protected")), -float(entry.get("age_days", 0)), str(entry.get("folder", ""))))
        return entries

    def _active_shared_lock_bundle_dirs(self) -> set[Path]:
        workspace_text = self._get_occs_shared_workspace_dir()
        if not workspace_text:
            return set()
        workspace_dir = Path(os.path.expanduser(workspace_text))
        packages_dir = workspace_dir / "packages"
        if not packages_dir.exists():
            return set()
        bundle_dirs: set[Path] = set()
        for lock_path in packages_dir.rglob("package.lock.json"):
            lock_payload = self._read_shared_lock(lock_path)
            if not isinstance(lock_payload, dict):
                continue
            bundle_dir_text = str(lock_payload.get("bundleDir", "")).strip()
            if bundle_dir_text:
                bundle_dirs.add(self._resolved_path(Path(os.path.expanduser(bundle_dir_text))))
        return bundle_dirs

    @staticmethod
    def _resolved_path(path: Path) -> Path:
        try:
            return path.expanduser().resolve()
        except OSError:
            return path.expanduser()

    def _is_direct_child_directory(self, path: Path, parent_dir: Path) -> bool:
        try:
            resolved_path = self._resolved_path(path)
            resolved_parent = self._resolved_path(parent_dir)
        except OSError:
            return False
        return resolved_path.is_dir() and resolved_path.parent == resolved_parent

    @staticmethod
    def _directory_modified_time(path: Path) -> float:
        latest = path.stat().st_mtime
        for root, _dirs, files in os.walk(path):
            for file_name in files:
                try:
                    latest = max(latest, (Path(root) / file_name).stat().st_mtime)
                except OSError:
                    continue
        return latest

    @staticmethod
    def _directory_size_bytes(path: Path) -> int:
        total = 0
        for root, _dirs, files in os.walk(path):
            for file_name in files:
                try:
                    total += (Path(root) / file_name).stat().st_size
                except OSError:
                    continue
        return total

    @staticmethod
    def _format_bytes(size_bytes: int) -> str:
        size = float(max(size_bytes, 0))
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                if unit == "B":
                    return f"{int(size)} {unit}"
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"

    def preview_occs_package(self) -> None:
        if self._occs_operation_in_progress:
            messagebox.showinfo("Preview Package", "An OCCS operation is already in progress.")
            return
        if not self.current_occs_bundle_dir or not self.current_occs_manifest:
            messagebox.showinfo("Preview Package", "Open a package version first.")
            return

        package_name = self._occs_manifest_package_short_name(self.current_occs_manifest)
        if not package_name:
            messagebox.showerror("Preview Package", "The current package version is missing a package short name.")
            return

        data_file_text = self.current_data_file_path or ""
        mapped_data_file = bool(data_file_text)

        dialog = self._create_toplevel(self.root)
        dialog.title("Preview Package")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.grab_set()

        container = ttk.Frame(dialog, padding=14)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)

        ttk.Label(container, text="Package:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Label(container, text=package_name).grid(row=0, column=1, columnspan=2, sticky="w")

        data_file_var = tk.StringVar(value=data_file_text)
        data_label_text = "Mapped Data:" if mapped_data_file else "JSON File:"
        ttk.Label(container, text=data_label_text).grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        data_file_entry = ttk.Entry(
            container,
            textvariable=data_file_var,
            width=58,
            state="readonly" if mapped_data_file else "normal",
        )
        data_file_entry.grid(row=1, column=1, sticky="ew", pady=(8, 0))

        def _browse_json_file() -> None:
            selected_path = filedialog.askopenfilename(
                parent=dialog,
                title="Select JSON File",
                filetypes=[
                    ("JSON Files", "*.json"),
                    ("All Files", "*.*"),
                ],
            )
            if selected_path:
                data_file_var.set(selected_path)

        if not mapped_data_file:
            ttk.Button(container, text="Browse...", command=_browse_json_file).grid(
                row=1,
                column=2,
                sticky="e",
                padx=(6, 0),
                pady=(8, 0),
            )

        render_group = ttk.LabelFrame(container, text="Render Types", padding=10)
        render_group.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 0))

        render_vars = {
            render_type: tk.BooleanVar(value=(render_type == "PDF"))
            for render_type in self.OCCS_PREVIEW_RENDER_TYPES
        }
        for index, render_type in enumerate(self.OCCS_PREVIEW_RENDER_TYPES):
            ttk.Checkbutton(
                render_group,
                text=render_type,
                variable=render_vars[render_type],
            ).grid(
                row=index // 3,
                column=index % 3,
                sticky="w",
                padx=(0 if index % 3 == 0 else 16, 0),
                pady=(0 if index < 3 else 6, 0),
            )

        timeout_var = tk.StringVar(value=str(self._default_preview_timeout_seconds(["PDF"])))
        timeout_user_modified = False
        updating_timeout_default = False

        def _selected_render_types() -> list[str]:
            return [
                render_type
                for render_type in self.OCCS_PREVIEW_RENDER_TYPES
                if render_vars[render_type].get()
            ]

        def _on_timeout_changed(*_args: object) -> None:
            nonlocal timeout_user_modified
            if updating_timeout_default:
                return
            timeout_user_modified = True

        def _refresh_timeout_default(*_args: object) -> None:
            nonlocal updating_timeout_default
            selected = _selected_render_types()
            if timeout_user_modified or not selected:
                return
            updating_timeout_default = True
            try:
                timeout_var.set(str(self._default_preview_timeout_seconds(selected)))
            finally:
                updating_timeout_default = False

        for variable in render_vars.values():
            variable.trace_add("write", _refresh_timeout_default)

        ttk.Label(container, text="Timeout (seconds):").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=(10, 0))
        timeout_entry = ttk.Entry(container, textvariable=timeout_var, width=12)
        timeout_entry.grid(row=3, column=1, sticky="w", pady=(10, 0))
        timeout_var.trace_add("write", _on_timeout_changed)

        open_after_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            container,
            text="Open after generation",
            variable=open_after_var,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(10, 0))

        buttons = ttk.Frame(container)
        buttons.grid(row=5, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))

        def _submit() -> None:
            data_file_path = Path(os.path.expanduser(data_file_var.get().strip()))
            if not data_file_var.get().strip():
                messagebox.showerror("Preview Package", "JSON file is required.", parent=dialog)
                return
            if not data_file_path.exists() or not data_file_path.is_file():
                messagebox.showerror(
                    "Preview Package",
                    f"JSON file not found:\n{data_file_path}",
                    parent=dialog,
                )
                return

            render_types = _selected_render_types()
            if not render_types:
                messagebox.showerror("Preview Package", "Select at least one render type.", parent=dialog)
                return

            timeout_seconds = self._safe_int(timeout_var.get().strip())
            if timeout_seconds is None or timeout_seconds <= 0:
                messagebox.showerror("Preview Package", "Timeout must be a positive number of seconds.", parent=dialog)
                return
            if timeout_seconds > self.OCCS_PREVIEW_MAX_TIMEOUT_SECONDS:
                messagebox.showerror(
                    "Preview Package",
                    f"Timeout cannot exceed {self.OCCS_PREVIEW_MAX_TIMEOUT_SECONDS} seconds.",
                    parent=dialog,
                )
                return

            unpublished_reasons = self._occs_preview_unpublished_change_reasons()
            if unpublished_reasons:
                detail = "\n".join(f"- {reason}" for reason in unpublished_reasons)
                if not messagebox.askyesno(
                    "Preview Package",
                    "Local and/or Shared Changes have not been published to Comms; preview anyway?\n\n"
                    f"{detail}",
                    parent=dialog,
                ):
                    return

            output_base = self._build_occs_preview_output_base(data_file_path, package_name)
            args = [
                "preview",
                "--package",
                package_name,
                "--input",
                str(data_file_path),
                "--output",
                str(output_base),
                "--timeout",
                str(timeout_seconds * 1000),
                "--render-type",
                *render_types,
            ]
            dialog.destroy()
            self._run_occs_command_async(
                args,
                f"Previewing package {package_name}...",
                lambda result, selected_render_types=render_types, should_open=open_after_var.get(): self._on_occs_preview_complete(
                    result,
                    selected_render_types,
                    should_open,
                ),
                on_failure=lambda error: messagebox.showerror("Preview Package", str(error)),
            )

        preview_button = ttk.Button(buttons, text="Preview", command=_submit, default="active")
        preview_button.grid(row=0, column=1)
        dialog.bind("<Return>", lambda _event: _submit())
        preview_button.focus_set()
        dialog.update_idletasks()
        x_pos = self.root.winfo_x() + max((self.root.winfo_width() - dialog.winfo_width()) // 2, 0)
        y_pos = self.root.winfo_y() + max((self.root.winfo_height() - dialog.winfo_height()) // 2, 0)
        dialog.geometry(f"+{x_pos}+{y_pos}")

    def save_occs_package(self) -> None:
        if self._occs_operation_in_progress:
            messagebox.showinfo("OCCS", "An OCCS operation is already in progress.")
            return
        if not self.current_occs_bundle_dir or not self.current_occs_manifest:
            messagebox.showinfo("Publish Package to Comms", "Open a package version first.")
            return
        if self.is_dirty and not self.save_assembly_template():
            return

        self._run_occs_json_command_async(
            [
                "list-configs",
                "--timeout",
                str(self.OCCS_SPECIFIC_VERSION_TIMEOUT_MS),
            ],
            "Loading Comms Config IDs...",
            lambda result: self._open_occs_save_dialog(self._normalize_occs_configs(result)),
            on_failure=self._on_occs_config_list_failed,
        )

    def check_out_shared_occs_bundle(self) -> None:
        context = self._current_occs_shared_context()
        if context is None:
            return
        lock_path = self._shared_lock_path(context["package_dir"])
        existing_lock = self._read_shared_lock(lock_path)
        owner = self._current_shared_user_identity()
        if existing_lock and not self._is_shared_lock_owner(existing_lock, owner):
            if not messagebox.askyesno(
                "Check Out Package Version",
                "This package/version is already locked.\n\n"
                f"{self._format_shared_lock(existing_lock)}\n\n"
                "Replace this lock?",
            ):
                return
        if not self._verify_shared_update_base(context, existing_lock, "Check Out Package Version"):
            return
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with open(lock_path, "w", encoding="utf-8") as target:
                json.dump(self._build_shared_lock_payload(context, owner), target, indent=2)
        except OSError as error:
            messagebox.showerror(
                "Check Out Package Version",
                f"Could not write shared lock:\n{lock_path}\n\nDetails: {error}",
            )
            return
        self._show_temporary_status("Package version checked out", duration_ms=5000)
        messagebox.showinfo("Check Out Package Version", f"Lock created:\n{lock_path}")

    def release_shared_occs_lock(self) -> None:
        context = self._current_occs_shared_context()
        if context is None:
            return
        lock_path = self._shared_lock_path(context["package_dir"])
        existing_lock = self._read_shared_lock(lock_path)
        if not existing_lock:
            messagebox.showinfo("Release Shared Package Lock", "No lock exists for this package version.")
            return
        owner = self._current_shared_user_identity()
        if not self._is_shared_lock_owner(existing_lock, owner):
            if not messagebox.askyesno(
                "Release Shared Package Lock",
                "This lock belongs to another user.\n\n"
                f"{self._format_shared_lock(existing_lock)}\n\n"
                "Release it anyway?",
            ):
                return
        try:
            lock_path.unlink()
        except OSError as error:
            messagebox.showerror(
                "Release Shared Package Lock",
                f"Could not remove shared lock:\n{lock_path}\n\nDetails: {error}",
            )
            return
        if self.current_occs_shared_package_dir == context["package_dir"]:
            self.current_occs_shared_mode = "testing"
        self._show_temporary_status("Package version lock released", duration_ms=5000)

    def update_shared_occs_package(self) -> None:
        if self.current_occs_shared_mode != "edit":
            messagebox.showinfo(
                "Update Shared Package",
                "Open the package version for edit before updating the shared package folder.",
            )
            return
        self._update_shared_from_current(release_lock_after=None, show_message=True)

    def publish_shared_occs_bundle(self) -> None:
        self.update_shared_occs_package()

    def publish_occs_package_to_comms(self) -> None:
        if self._occs_operation_in_progress:
            messagebox.showinfo("Publish Package to Comms", "A package operation is already in progress.")
            return
        if not self._prompt_save_if_dirty():
            return

        if self.current_occs_shared_package_dir is not None:
            if self.current_occs_shared_mode == "edit":
                if messagebox.askyesno(
                    "Publish Package to Comms",
                    "You are editing this package version locally.\n\n"
                    "Update the shared package folder before publishing to Comms?",
                ):
                    if not self._update_shared_from_current(release_lock_after=False, show_message=False):
                        return
                else:
                    messagebox.showinfo(
                        "Publish Package to Comms",
                        "Publishing uses the shared package folder, not unsynced local edits.",
                    )
            entry = self._shared_package_entry_from_package_dir(self.current_occs_shared_package_dir)
            if entry is None:
                messagebox.showerror(
                    "Publish Package to Comms",
                    "Could not find the shared package version for the currently open package.",
                )
                return
            self._publish_shared_entry_to_comms(entry)
            return

        workspace_dir = self._ensure_occs_shared_workspace_dir()
        if workspace_dir is None:
            return
        entries = self._list_shared_package_versions(workspace_dir)
        if not entries:
            messagebox.showinfo(
                "Publish Package to Comms",
                "No package versions were found in the shared package folder.",
            )
            return
        self._open_shared_package_selection_dialog(
            entries,
            title="Publish Package to Comms",
            on_select=self._publish_shared_entry_to_comms,
        )

    def _update_shared_from_current(
        self,
        release_lock_after: bool | None,
        show_message: bool,
    ) -> bool:
        context = self._current_occs_shared_context()
        if context is None:
            return False
        if self.is_dirty and not self.save_assembly_template():
            return False
        owner = self._current_shared_user_identity()
        lock_path = self._shared_lock_path(context["package_dir"])
        existing_lock = self._read_shared_lock(lock_path)
        if not existing_lock:
            messagebox.showerror(
                "Update Shared Package",
                "Cannot update the shared package folder because no edit lock exists.",
            )
            return False
        if not self._is_shared_lock_owner(existing_lock, owner):
            messagebox.showerror(
                "Update Shared Package",
                "Cannot update because this package version is locked by another user.\n\n"
                f"{self._format_shared_lock(existing_lock)}",
            )
            return False
        if not self._verify_shared_update_base(context, existing_lock, "Update Shared Package"):
            return False

        published_dir = context["package_dir"] / "published" / "current"
        history_dir = context["package_dir"] / "published" / "history" / self._shared_publication_folder_name(owner)
        try:
            self._copy_occs_bundle_to_shared(context, published_dir)
            self._copy_occs_bundle_to_shared(context, history_dir)
        except OSError as error:
            messagebox.showerror(
                "Update Shared Package",
                f"Could not update the shared package folder.\n\nDetails: {error}",
            )
            return False

        baseline_warning = ""
        updated_entry = self._shared_package_entry_from_package_dir(context["package_dir"])
        bundle_dir = context.get("bundle_dir")
        if updated_entry is not None and isinstance(bundle_dir, Path):
            try:
                self._write_shared_baseline_for_local_copy(bundle_dir, updated_entry, reason="updatedShared")
            except (OSError, ValueError) as error:
                baseline_warning = str(error)

        release_lock = release_lock_after
        if release_lock is None:
            release_lock = messagebox.askyesno(
                "Update Shared Package",
                "Shared package folder updated.\n\nRelease the edit lock now?",
            )
        if release_lock:
            try:
                lock_path.unlink()
                self.current_occs_shared_mode = "testing"
            except OSError as error:
                messagebox.showwarning(
                    "Update Shared Package",
                    f"Shared package folder was updated, but the lock could not be released.\n\nDetails: {error}",
                )
                release_lock = False

        self._show_temporary_status("Updated shared package version", duration_ms=5000)
        self._record_occs_package_mru(
            str(context.get("package_name", "")),
            str(context.get("version_name", "")),
        )
        if show_message:
            lock_text = "released" if release_lock else "still held"
            warning_text = f"\n\nBaseline warning: {baseline_warning}" if baseline_warning else ""
            messagebox.showinfo(
                "Update Shared Package",
                f"Updated shared package version:\n{published_dir}\n\nLock: {lock_text}{warning_text}",
            )
        return True

    def open_shared_published_bundle(self) -> None:
        workspace_dir = self._ensure_occs_shared_workspace_dir()
        if workspace_dir is None:
            return
        initial_dir = workspace_dir
        if self.current_occs_manifest:
            context = self._current_occs_shared_context(show_errors=False)
            if context is not None:
                candidate = context["package_dir"] / "published" / "current"
                if (candidate / "occs-package.json").exists():
                    if not self._prompt_save_if_dirty():
                        return
                    self._load_occs_bundle(str(candidate))
                    return
                initial_dir = context["package_dir"]

        selected_dir = filedialog.askdirectory(
            title="Open Published Package Version",
            initialdir=str(initial_dir),
        )
        if not selected_dir:
            return
        candidate = Path(selected_dir)
        if not (candidate / "occs-package.json").exists():
            published_candidate = candidate / "published" / "current"
            if (published_candidate / "occs-package.json").exists():
                candidate = published_candidate
        if not self._prompt_save_if_dirty():
            return
        self._load_occs_bundle(str(candidate))

    def _open_shared_package_selection_dialog(
        self,
        entries: list[dict[str, object]],
        title: str = "Open Package",
        on_select: object | None = None,
    ) -> None:
        dialog = self._create_toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.grab_set()

        container = ttk.Frame(dialog, padding=14)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        tree = ttk.Treeview(
            container,
            columns=("version", "status", "updated"),
            show="tree headings",
            height=min(max(len(entries), 6), 14),
        )
        tree.heading("#0", text="Package")
        tree.heading("version", text="Version")
        tree.heading("status", text="Status")
        tree.heading("updated", text="Updated")
        tree.column("#0", width=180, stretch=True)
        tree.column("version", width=100, stretch=False)
        tree.column("status", width=220, stretch=True)
        tree.column("updated", width=170, stretch=False)
        tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        entry_by_id: dict[str, dict[str, object]] = {}
        current_shared_dir = self.current_occs_shared_package_dir
        selected_item = ""
        for entry in entries:
            package_dir = entry.get("package_dir")
            lock_payload = self._read_shared_lock(self._shared_lock_path(package_dir)) if isinstance(package_dir, Path) else None
            entry["lock"] = lock_payload
            status = "Available"
            if lock_payload:
                status = f"Locked by {self._shared_lock_owner_text(lock_payload)}"
            item_id = tree.insert(
                "",
                tk.END,
                text=str(entry.get("package_name", "")),
                values=(
                    str(entry.get("version_name", "")),
                    status,
                    self._shared_entry_updated_at(entry),
                ),
            )
            entry_by_id[item_id] = entry
            if isinstance(package_dir, Path) and current_shared_dir == package_dir:
                selected_item = item_id

        if selected_item:
            tree.selection_set(selected_item)
            tree.focus(selected_item)
            tree.see(selected_item)
        elif entry_by_id:
            first_item = next(iter(entry_by_id))
            tree.selection_set(first_item)
            tree.focus(first_item)

        buttons = ttk.Frame(container)
        buttons.grid(row=1, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))

        def _retrieve_from_comms() -> None:
            dialog.destroy()
            self.list_occs_packages_from_comms()

        ttk.Button(buttons, text="Retrieve from Comms...", command=_retrieve_from_comms).grid(
            row=0,
            column=1,
            padx=(0, 8),
        )

        def _open_selected() -> None:
            selection = tree.selection()
            if not selection:
                messagebox.showinfo(title, "Select a package version first.", parent=dialog)
                return
            entry = entry_by_id.get(selection[0])
            if not entry:
                return
            dialog.destroy()
            if callable(on_select):
                on_select(entry)
            else:
                self._handle_shared_package_selection(entry)

        action_label = "Publish" if callable(on_select) else "Open"
        ttk.Button(buttons, text=action_label, command=_open_selected).grid(row=0, column=2)
        tree.bind("<Double-1>", lambda _event: _open_selected())

        dialog.update_idletasks()
        width = max(dialog.winfo_width(), 760)
        height = max(dialog.winfo_height(), 360)
        x_pos = self.root.winfo_x() + max((self.root.winfo_width() - width) // 2, 0)
        y_pos = self.root.winfo_y() + max((self.root.winfo_height() - height) // 2, 0)
        dialog.geometry(f"{width}x{height}+{x_pos}+{y_pos}")

    def _handle_shared_package_selection(self, entry: dict[str, object]) -> None:
        entry = self._refresh_shared_package_entry(entry) or entry
        lock_payload = entry.get("lock")
        owner = self._current_shared_user_identity()
        if isinstance(lock_payload, dict) and not self._is_shared_lock_owner(lock_payload, owner):
            if messagebox.askyesno(
                "Open Package",
                "This package version is locked for edit.\n\n"
                f"{self._format_shared_lock(lock_payload)}\n\n"
                "Open a local testing copy? You will not be able to update the shared package folder.",
            ):
                self._open_shared_entry_local_copy(entry, mode="testing")
            return

        self._prompt_lock_and_open_shared_entry(entry)

    def _open_shared_entry_for_edit(self, entry: dict[str, object], title: str = "Open Package") -> bool:
        entry = self._refresh_shared_package_entry(entry) or entry
        package_dir = entry.get("package_dir")
        if not isinstance(package_dir, Path):
            messagebox.showerror(title, "The selected package version is missing shared folder metadata.")
            return False

        lock_path = self._shared_lock_path(package_dir)
        lock_payload = self._read_shared_lock(lock_path)
        owner = self._current_shared_user_identity()
        if lock_payload and not self._is_shared_lock_owner(lock_payload, owner):
            if messagebox.askyesno(
                title,
                "This package version is locked for edit.\n\n"
                f"{self._format_shared_lock(lock_payload)}\n\n"
                "Open a local testing copy? You will not be able to update the shared package folder.",
            ):
                return self._open_shared_entry_local_copy(entry, mode="testing")
            return False

        context = self._shared_context_from_entry(entry)
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_write_mode = "w" if lock_payload else "x"
            with open(lock_path, lock_write_mode, encoding="utf-8") as target:
                json.dump(self._build_shared_lock_payload(context, owner), target, indent=2)
        except FileExistsError:
            fresh_lock = self._read_shared_lock(lock_path)
            if fresh_lock and messagebox.askyesno(
                title,
                "This package version was locked by another user before the edit lock could be created.\n\n"
                f"{self._format_shared_lock(fresh_lock)}\n\n"
                "Open a local testing copy?",
            ):
                return self._open_shared_entry_local_copy(entry, mode="testing")
            return False
        except OSError as error:
            messagebox.showerror(
                title,
                f"Could not write shared lock:\n{lock_path}\n\nDetails: {error}",
            )
            return False

        return self._open_shared_entry_local_copy(entry, mode="edit")

    def _can_get_shared_package_for_edit(self, manifest: dict[str, object], bundle_path: Path) -> bool:
        try:
            package_dir = self._shared_package_dir_for_manifest(manifest)
        except OSError as error:
            messagebox.showerror("Get Package from Comms", str(error))
            return False

        lock_payload = self._read_shared_lock(self._shared_lock_path(package_dir))
        owner = self._current_shared_user_identity()
        if not lock_payload or self._is_shared_lock_owner(lock_payload, owner):
            return True

        if messagebox.askyesno(
            "Get Package from Comms",
            "Cannot update the shared package folder because this package version is locked for edit.\n\n"
            f"{self._format_shared_lock(lock_payload)}\n\n"
            "Open the downloaded bundle as a local package instead?",
        ):
            self._load_occs_bundle(str(bundle_path))
        return False

    def _verify_shared_update_base(
        self,
        context: dict[str, object],
        lock_payload: dict[str, object] | None,
        title: str,
    ) -> bool:
        package_dir = context.get("package_dir")
        bundle_dir = context.get("bundle_dir")
        if not isinstance(package_dir, Path) or not isinstance(bundle_dir, Path):
            messagebox.showerror(title, "The current package is missing shared folder metadata.")
            return False

        entry = self._shared_package_entry_from_package_dir(package_dir)
        if entry is None:
            messagebox.showerror(title, "Could not read the current shared package version.")
            return False

        try:
            current_shared_hashes = self._shared_current_hashes_for_entry(entry)
        except ValueError as error:
            messagebox.showerror(title, f"Could not verify the current shared package version.\n\nDetails: {error}")
            return False

        baseline = self._read_shared_baseline_for_local_copy(bundle_dir)
        baseline_hashes = baseline.get("sharedHashes") if isinstance(baseline, dict) else None
        if not isinstance(baseline_hashes, dict) or not baseline_hashes:
            messagebox.showerror(
                title,
                "Cannot safely update the shared package folder because this local copy does not have "
                "shared baseline metadata.\n\n"
                "Open the package from the shared workspace again, then reapply your local changes.",
            )
            return False
        baseline_package = str(baseline.get("package", "")).strip()
        baseline_version = str(baseline.get("version", "")).strip()
        if (
            baseline_package != str(context.get("package_name", "")).strip()
            or baseline_version != str(context.get("version_name", "")).strip()
        ):
            messagebox.showerror(
                title,
                "Cannot safely update the shared package folder because this local copy's shared baseline "
                "does not match the current package/version.",
            )
            return False

        if not self._shared_hashes_match(baseline_hashes, current_shared_hashes):
            messagebox.showerror(
                title,
                "Cannot update the shared package folder because this local copy is based on an older "
                "shared version.\n\n"
                f"Current shared update: {self._shared_entry_updated_at(entry) or '(unknown time)'}\n"
                f"Current shared owner: {self._shared_publication_owner_text(entry)}\n\n"
                "Open the latest shared package, then reapply your local changes.",
            )
            return False

        lock_hashes = lock_payload.get("sharedBaselineHashes") if isinstance(lock_payload, dict) else None
        if isinstance(lock_hashes, dict) and lock_hashes and not self._shared_hashes_match(lock_hashes, current_shared_hashes):
            messagebox.showerror(
                title,
                "Cannot update the shared package folder because the shared package changed after this edit lock was acquired.\n\n"
                "Open the latest shared package, then reapply your local changes.",
            )
            return False

        return True

    def _prompt_lock_and_open_shared_entry(self, entry: dict[str, object]) -> None:
        entry = self._refresh_shared_package_entry(entry) or entry
        package_dir = entry.get("package_dir")
        if not isinstance(package_dir, Path):
            messagebox.showerror("Open Package", "The selected package version is missing shared folder metadata.")
            return

        lock_path = self._shared_lock_path(package_dir)
        lock_payload = self._read_shared_lock(lock_path)
        owner = self._current_shared_user_identity()
        if lock_payload and not self._is_shared_lock_owner(lock_payload, owner):
            if messagebox.askyesno(
                "Open Package",
                "This package version was locked before it could be opened.\n\n"
                f"{self._format_shared_lock(lock_payload)}\n\n"
                "Open a local testing copy?",
            ):
                self._open_shared_entry_local_copy(entry, mode="testing")
            return

        if lock_payload and self._is_shared_lock_owner(lock_payload, owner):
            resume_dir = self._shared_edit_resume_dir(entry, lock_payload)
            if resume_dir is not None and messagebox.askyesno(
                "Open Package",
                "You already hold an edit lock for this package version.\n\n"
                f"{self._format_shared_lock(lock_payload)}\n\n"
                f"Resume the existing local edit session?\n\n{resume_dir}\n\n"
                "Choose No to create a fresh local copy.",
            ):
                if self._load_occs_bundle(str(resume_dir), shared_package_dir=package_dir, shared_mode="edit"):
                    self._show_temporary_status("Resumed package edit session", duration_ms=5000)
                return

        lock_for_edit = messagebox.askyesno(
            "Open Package",
            "Lock this package version for edit?\n\n"
            "Choose No to open a local testing copy only.",
        )
        mode = "edit" if lock_for_edit else "testing"
        if lock_for_edit:
            context = self._shared_context_from_entry(entry)
            try:
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                lock_write_mode = "w" if lock_payload else "x"
                with open(lock_path, lock_write_mode, encoding="utf-8") as target:
                    json.dump(self._build_shared_lock_payload(context, owner), target, indent=2)
            except FileExistsError:
                fresh_lock = self._read_shared_lock(lock_path)
                if fresh_lock and messagebox.askyesno(
                    "Open Package",
                    "This package version was locked by another user before the edit lock could be created.\n\n"
                    f"{self._format_shared_lock(fresh_lock)}\n\n"
                    "Open a local testing copy?",
                ):
                    self._open_shared_entry_local_copy(entry, mode="testing")
                return
            except OSError as error:
                messagebox.showerror(
                    "Open Package",
                    f"Could not write shared lock:\n{lock_path}\n\nDetails: {error}",
                )
                return

        self._open_shared_entry_local_copy(entry, mode=mode)

    def _open_shared_entry_local_copy(self, entry: dict[str, object], mode: str) -> bool:
        published_dir = entry.get("published_dir")
        package_dir = entry.get("package_dir")
        if not isinstance(published_dir, Path) or not isinstance(package_dir, Path):
            messagebox.showerror("Open Package", "The selected package version is missing shared folder metadata.")
            return False
        work_dir = Path(os.path.expanduser(self._get_occs_work_dir()))
        try:
            work_dir.mkdir(parents=True, exist_ok=True)
            local_dir = self._build_occs_local_copy_path(
                work_dir,
                str(entry.get("package_name", "")),
                str(entry.get("version_name", "")),
                mode,
            )
            shutil.copytree(published_dir, local_dir)
            self._write_shared_baseline_for_local_copy(local_dir, entry, reason=f"opened-{mode}")
            if mode == "edit":
                self._write_shared_edit_lock_for_local_copy(entry, local_dir)
        except OSError as error:
            messagebox.showerror(
                "Open Package",
                f"Could not create local package copy.\n\nDetails: {error}",
            )
            return False
        except ValueError as error:
            messagebox.showerror(
                "Open Package",
                f"Could not record shared package baseline.\n\nDetails: {error}",
            )
            return False

        if not self._load_occs_bundle(str(local_dir), shared_package_dir=package_dir, shared_mode=mode):
            return False
        if mode == "edit":
            self._show_temporary_status("Package version locked for edit", duration_ms=5000)
        elif mode == "publish":
            self._show_temporary_status("Loaded shared package version for Comms publish", duration_ms=5000)
        else:
            self._show_temporary_status("Opened local testing copy", duration_ms=5000)
        return True

    def _shared_edit_resume_dir(
        self,
        entry: dict[str, object],
        lock_payload: dict[str, object],
    ) -> Path | None:
        candidates: list[Path] = []
        bundle_dir_text = str(lock_payload.get("bundleDir", "")).strip()
        if bundle_dir_text:
            candidates.append(Path(os.path.expanduser(bundle_dir_text)))

        state = self._read_app_state()
        last_bundle = state.get("last_occs_bundle")
        if isinstance(last_bundle, str) and last_bundle.strip():
            candidates.append(Path(os.path.expanduser(last_bundle)))

        work_dir = Path(os.path.expanduser(self._get_occs_work_dir()))
        if work_dir.exists():
            try:
                local_dirs = [
                    bundle_dir
                    for bundle_dir in work_dir.iterdir()
                    if bundle_dir.is_dir() and (bundle_dir / "occs-package.json").exists()
                ]
            except OSError:
                local_dirs = []
            local_dirs.sort(key=lambda path: self._directory_modified_time(path), reverse=True)
            candidates.extend(local_dirs)

        seen: set[Path] = set()
        for candidate in candidates:
            resolved_candidate = self._resolved_path(candidate)
            if resolved_candidate in seen:
                continue
            seen.add(resolved_candidate)
            if self._is_shared_edit_resume_dir(candidate, entry):
                return candidate
        return None

    def _is_shared_edit_resume_dir(self, bundle_dir: Path, entry: dict[str, object]) -> bool:
        if not bundle_dir.exists() or not bundle_dir.is_dir():
            return False
        if not (bundle_dir / "occs-package.json").exists():
            return False

        published_dir = entry.get("published_dir")
        if isinstance(published_dir, Path) and self._resolved_path(bundle_dir) == self._resolved_path(published_dir):
            return False

        baseline = self._read_shared_baseline_for_local_copy(bundle_dir)
        if not isinstance(baseline, dict):
            return False
        if str(baseline.get("reason", "")).strip() != "opened-edit":
            return False
        if str(baseline.get("package", "")).strip() != str(entry.get("package_name", "")).strip():
            return False
        if str(baseline.get("version", "")).strip() != str(entry.get("version_name", "")).strip():
            return False

        try:
            manifest = self._read_occs_manifest(str(bundle_dir))
        except ValueError:
            return False
        return (
            self._occs_manifest_package_short_name(manifest) == str(entry.get("package_name", "")).strip()
            and self._occs_manifest_version_short_name(manifest) == str(entry.get("version_name", "")).strip()
        )

    def _write_shared_edit_lock_for_local_copy(self, entry: dict[str, object], local_dir: Path) -> None:
        package_dir = entry.get("package_dir")
        if not isinstance(package_dir, Path):
            return
        try:
            manifest = self._read_occs_manifest(str(local_dir))
        except ValueError:
            manifest = entry.get("manifest") if isinstance(entry.get("manifest"), dict) else {}
        context = {
            "workspace_dir": entry.get("workspace_dir"),
            "package_dir": package_dir,
            "package_name": str(entry.get("package_name", "")),
            "version_name": str(entry.get("version_name", "")),
            "bundle_dir": local_dir,
            "manifest": manifest,
        }
        lock_path = self._shared_lock_path(package_dir)
        owner = self._current_shared_user_identity()
        existing_lock = self._read_shared_lock(lock_path)
        payload = self._build_shared_lock_payload(context, owner)
        if isinstance(existing_lock, dict):
            created_at = str(existing_lock.get("createdAt", "")).strip()
            if created_at:
                payload["createdAt"] = created_at
        with open(lock_path, "w", encoding="utf-8") as target:
            json.dump(payload, target, indent=2)

    def _publish_shared_entry_to_comms(self, entry: dict[str, object]) -> None:
        if not self._prompt_save_if_dirty():
            return
        published_dir = entry.get("published_dir")
        package_dir = entry.get("package_dir")
        if not isinstance(published_dir, Path) or not isinstance(package_dir, Path):
            messagebox.showerror("Publish Package to Comms", "The selected package version is missing shared folder metadata.")
            return
        if self._load_occs_bundle(str(published_dir), shared_package_dir=package_dir, shared_mode="publish"):
            self._show_temporary_status("Loaded shared package version for Comms publish", duration_ms=5000)
            self.save_occs_package()

    def _on_occs_config_list_failed(self, error: Exception) -> None:
        if not messagebox.askyesno(
            "Publish Package to Comms",
            "Could not load open Config IDs from Comms.\n\n"
            f"Details: {error}\n\n"
            "Continue with manual Config ID entry?",
        ):
            return
        self._open_occs_save_dialog([])

    def _open_occs_save_dialog(self, configs: list[dict[str, str]]) -> None:
        if not self.current_occs_bundle_dir or not self.current_occs_manifest:
            messagebox.showinfo("Publish Package to Comms", "Open a package version first.")
            return

        dialog = self._create_toplevel(self.root)
        dialog.title("Publish Package to Comms")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.grab_set()

        container = ttk.Frame(dialog, padding=14)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)

        package_name = self._occs_manifest_package_short_name(self.current_occs_manifest)
        version_name = self._occs_manifest_version_short_name(self.current_occs_manifest)
        ttk.Label(container, text="Package:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Label(container, text=f"{package_name} {version_name}".strip() or "(unknown)").grid(
            row=0,
            column=1,
            sticky="w",
        )

        folder_label = "Shared Folder:" if self.current_occs_shared_mode == "publish" else "Local Folder:"
        ttk.Label(container, text=folder_label).grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        ttk.Label(
            container,
            text=str(self.current_occs_bundle_dir),
            wraplength=520,
            justify=tk.LEFT,
        ).grid(row=1, column=1, sticky="w", pady=(8, 0))

        labels = [self._format_occs_config_label(config) for config in configs]
        config_by_label = {
            label: config
            for label, config in zip(labels, configs)
            if label
        }
        config_var = tk.StringVar(value=self._initial_occs_config_selection(labels, configs))

        ttk.Label(container, text="Config ID:").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        config_combo = ttk.Combobox(
            container,
            textvariable=config_var,
            values=labels,
            state="normal",
            width=54,
        )
        config_combo.grid(row=2, column=1, sticky="ew", pady=(8, 0))

        buttons = ttk.Frame(container)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))

        def _submit() -> None:
            raw_value = config_var.get().strip()
            config_id = self._occs_config_id_from_selection(raw_value, config_by_label)
            if not config_id:
                messagebox.showerror("Publish Package to Comms", "Config ID is required.", parent=dialog)
                return
            self._set_last_occs_config_id(config_id)
            dialog.destroy()
            self._run_occs_save_dry_run(config_id)

        ttk.Button(buttons, text="Dry Run", command=_submit).grid(row=0, column=1)
        config_combo.focus_set()
        dialog.update_idletasks()
        x_pos = self.root.winfo_x() + max((self.root.winfo_width() - dialog.winfo_width()) // 2, 0)
        y_pos = self.root.winfo_y() + max((self.root.winfo_height() - dialog.winfo_height()) // 2, 0)
        dialog.geometry(f"+{x_pos}+{y_pos}")

    def _run_occs_save_dry_run(self, config_id: str) -> None:
        if not self.current_occs_bundle_dir:
            messagebox.showinfo("Publish Package to Comms", "Open a package version first.")
            return
        self._run_occs_json_command_async(
            [
                "package",
                "save",
                self.current_occs_bundle_dir,
                "--config-id",
                config_id,
                "--dry-run",
                "--timeout",
                str(self.OCCS_SPECIFIC_VERSION_TIMEOUT_MS),
            ],
            "Running Comms publish dry run...",
            lambda result, selected_config_id=config_id: self._on_occs_save_dry_run_complete(
                result,
                selected_config_id,
            ),
        )

    def _on_occs_save_dry_run_complete(self, result: dict[str, object], config_id: str) -> None:
        changes = result.get("changes")
        changed_surfaces = [
            str(name)
            for name, changed in (changes.items() if isinstance(changes, dict) else [])
            if changed
        ]
        if not changed_surfaces:
            messagebox.showinfo(
                "Publish Package to Comms",
                "Dry run complete. No package version changes were detected.",
            )
            self._show_temporary_status("Comms dry run complete: no changes", duration_ms=5000)
            return

        summary = self._format_occs_save_result(result, changed_surfaces)
        if not messagebox.askyesno(
            "Confirm Comms Publish",
            f"{summary}\n\nPublish these changes to Comms?",
        ):
            return
        self._run_occs_package_save(config_id)

    def _run_occs_package_save(self, config_id: str) -> None:
        if not self.current_occs_bundle_dir:
            messagebox.showinfo("Publish Package to Comms", "Open a package version first.")
            return
        self._run_occs_json_command_async(
            [
                "package",
                "save",
                self.current_occs_bundle_dir,
                "--config-id",
                config_id,
                "--timeout",
                str(self.OCCS_SPECIFIC_VERSION_TIMEOUT_MS),
            ],
            "Publishing package to Comms...",
            self._on_occs_package_save_complete,
        )

    def _on_occs_package_save_complete(self, result: dict[str, object]) -> None:
        if self.current_occs_bundle_dir:
            try:
                self.current_occs_manifest = self._read_occs_manifest(self.current_occs_bundle_dir)
            except ValueError:
                pass
        self._record_occs_package_mru_from_manifest(self.current_occs_manifest)
        shared_sync_warning = self._sync_shared_package_after_comms_publish()
        summary = self._format_occs_save_result(result)
        message = f"Package published to Comms.\n\n{summary}"
        if shared_sync_warning:
            message = f"{message}\n\nShared package folder warning:\n{shared_sync_warning}"
            messagebox.showwarning("Publish Package to Comms", message)
        else:
            messagebox.showinfo("Publish Package to Comms", message)
        self._show_temporary_status("Package published to Comms", duration_ms=5000)

    def _sync_shared_package_after_comms_publish(self) -> str:
        if (
            self.current_occs_shared_package_dir is None
            or not self.current_occs_bundle_dir
            or not self.current_occs_manifest
        ):
            return ""

        package_dir = self.current_occs_shared_package_dir
        bundle_dir = Path(self.current_occs_bundle_dir)
        published_dir = package_dir / "published" / "current"
        try:
            if bundle_dir.resolve() == published_dir.resolve():
                return ""
        except OSError:
            pass

        package_name = self._occs_manifest_package_short_name(self.current_occs_manifest)
        version_name = self._occs_manifest_version_short_name(self.current_occs_manifest)
        context = {
            "package_dir": package_dir,
            "package_name": package_name,
            "version_name": version_name,
            "bundle_dir": bundle_dir,
            "manifest": self.current_occs_manifest,
            "publicationReason": "publishedToComms",
        }
        lock_payload = self._read_shared_lock(self._shared_lock_path(package_dir))
        if not self._verify_shared_update_base(context, lock_payload, "Publish Package to Comms"):
            return "Shared package folder was not updated because the local copy is stale."
        owner = self._current_shared_user_identity()
        history_dir = package_dir / "published" / "history" / self._shared_publication_folder_name(owner)
        try:
            self._copy_occs_bundle_to_shared(context, published_dir)
            self._copy_occs_bundle_to_shared(context, history_dir)
        except OSError as error:
            return str(error)
        updated_entry = self._shared_package_entry_from_package_dir(package_dir)
        if updated_entry is not None:
            try:
                self._write_shared_baseline_for_local_copy(bundle_dir, updated_entry, reason="publishedToComms")
            except (OSError, ValueError) as error:
                return f"Shared package folder was updated, but baseline metadata could not be refreshed: {error}"
        return ""

    def _run_occs_command_async(
        self,
        args: list[str],
        status_message: str,
        on_success: object,
        on_failure: object | None = None,
    ) -> None:
        if self._occs_operation_in_progress:
            messagebox.showinfo("OCCS", "An OCCS operation is already in progress.")
            return

        self._occs_operation_in_progress = True
        if self._status_note_job:
            self.root.after_cancel(self._status_note_job)
            self._status_note_job = None
        self.status_text.set(status_message)
        self._debug_log(f"OCCS command started: {' '.join(args)}")

        def _worker() -> None:
            try:
                result = self._run_occs_command(args)
                self.root.after(0, lambda result=result: self._on_occs_command_success(result, on_success))
            except Exception as error:  # pragma: no cover - defensive runtime safety
                stack = traceback.format_exc()
                self.root.after(
                    0,
                    lambda error=error, stack=stack: self._on_occs_command_failure(error, stack, on_failure),
                )

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _run_occs_json_command_async(
        self,
        args: list[str],
        status_message: str,
        on_success: object,
        on_failure: object | None = None,
    ) -> None:
        if self._occs_operation_in_progress:
            messagebox.showinfo("OCCS", "An OCCS operation is already in progress.")
            return

        self._occs_operation_in_progress = True
        if self._status_note_job:
            self.root.after_cancel(self._status_note_job)
            self._status_note_job = None
        self.status_text.set(status_message)
        self._debug_log(f"OCCS command started: {' '.join(args)}")

        def _worker() -> None:
            try:
                result = self._run_occs_json_command(args)
                self.root.after(0, lambda result=result: self._on_occs_command_success(result, on_success))
            except Exception as error:  # pragma: no cover - defensive runtime safety
                stack = traceback.format_exc()
                self.root.after(
                    0,
                    lambda error=error, stack=stack: self._on_occs_command_failure(error, stack, on_failure),
                )

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _on_occs_command_success(self, result: dict[str, object], on_success: object) -> None:
        self._occs_operation_in_progress = False
        self._restore_default_status_text()
        if callable(on_success):
            on_success(result)

    def _on_occs_command_failure(
        self,
        error: Exception,
        stack: str,
        on_failure: object | None,
    ) -> None:
        self._occs_operation_in_progress = False
        self._restore_default_status_text()
        self._debug_log(f"OCCS command failed:\n{stack}")
        if callable(on_failure):
            on_failure(error)
            return
        messagebox.showerror("OCCS Error", str(error))

    def _run_occs_json_command(self, args: list[str]) -> dict[str, object]:
        command_args = [str(arg) for arg in args]
        if "--json" not in command_args:
            command_args.append("--json")
        login_attempted = False

        while True:
            completed = self._run_occs_cli(command_args)
            stdout = (completed.stdout or "").strip()
            stderr = (completed.stderr or "").strip()
            parsed = self._parse_occs_json_stdout(stdout)

            if completed.returncode != 0:
                message = self._occs_error_message(parsed, stderr, completed.returncode)
                if not login_attempted and self._should_retry_occs_after_login(command_args, message):
                    self._run_occs_login_for_retry(message)
                    login_attempted = True
                    continue
                raise RuntimeError(message)
            if parsed is None:
                detail = f"\n\nSTDERR:\n{stderr}" if stderr else ""
                raise RuntimeError(f"OCCS CLI did not return JSON on stdout.{detail}")
            if parsed.get("ok") is False:
                message = self._occs_error_message(parsed, stderr, completed.returncode)
                if not login_attempted and self._should_retry_occs_after_login(command_args, message):
                    self._run_occs_login_for_retry(message)
                    login_attempted = True
                    continue
                raise RuntimeError(message)
            return parsed

    def _run_occs_command(self, args: list[str]) -> dict[str, object]:
        command_args = [str(arg) for arg in args]
        login_attempted = False

        while True:
            completed = self._run_occs_cli(command_args)
            stdout = (completed.stdout or "").strip()
            stderr = (completed.stderr or "").strip()
            if completed.returncode != 0:
                message = stderr or stdout or f"OCCS CLI exited with status {completed.returncode}."
                if not login_attempted and self._should_retry_occs_after_login(command_args, message):
                    self._run_occs_login_for_retry(message)
                    login_attempted = True
                    continue
                raise RuntimeError(message)
            return {
                "stdout": stdout,
                "stderr": stderr,
                "returnCode": completed.returncode,
            }

    def _run_occs_cli(
        self,
        args: list[str],
        timeout_seconds: int = 600,
        stdin: object | None = None,
        timeout_message: str = "OCCS CLI command timed out.",
    ) -> subprocess.CompletedProcess[str]:
        command = self._build_occs_command(args)
        try:
            return subprocess.run(
                command,
                cwd=self._occs_cli_cwd(),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                stdin=stdin,
            )
        except OSError as error:
            raise RuntimeError(f"Could not run OCCS CLI: {error}") from error
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(timeout_message) from error

    def _run_occs_login_for_retry(self, original_error: str) -> None:
        self._debug_log("OCCS authorization failed; running `occs login` before retrying.")
        self.root.after(0, lambda: self.status_text.set("OCCS session expired. Running occs login..."))
        try:
            completed = self._run_occs_cli(
                ["login"],
                timeout_seconds=self.OCCS_LOGIN_TIMEOUT_SECONDS,
                stdin=subprocess.DEVNULL,
                timeout_message="Automatic `occs login` timed out.",
            )
        except RuntimeError as error:
            raise RuntimeError(f"{original_error}\n\nAutomatic `occs login` failed: {error}") from error

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if completed.returncode != 0:
            message = stderr or stdout or f"`occs login` exited with status {completed.returncode}."
            raise RuntimeError(f"{original_error}\n\nAutomatic `occs login` failed: {message}")
        self._debug_log("OCCS login completed; retrying original command.")

    def _should_retry_occs_after_login(self, command_args: list[str], message: str) -> bool:
        if not command_args or command_args[0] == "login":
            return False
        return self._is_occs_unauthorized_error(message)

    @staticmethod
    def _is_occs_unauthorized_error(message: str) -> bool:
        normalized = message.lower()
        if "401" in normalized and (
            "unauthorized" in normalized
            or "authorization required" in normalized
            or "status code 401" in normalized
            or "status: 401" in normalized
        ):
            return True
        if "unauthorized" not in normalized:
            return False
        return any(
            marker in normalized
            for marker in (
                "token may have expired",
                "session may have expired",
                "occs login",
                "please log in again",
            )
        )

    def _build_occs_command(self, args: list[str]) -> list[str]:
        cli_path = os.path.expanduser(self._get_occs_cli_path())
        args = self._occs_args_with_session_alias(args)
        if cli_path.endswith(".js") or os.path.basename(cli_path) == "occs.js":
            return ["node", cli_path, *args]
        return [cli_path, *args]

    def _occs_args_with_session_alias(self, args: list[str]) -> list[str]:
        command_args = [str(arg) for arg in args]
        session_alias = self._get_occs_session_alias()
        if not session_alias or "--session" in command_args:
            return command_args
        if not command_args:
            return command_args

        command_name = command_args[0]
        if command_name == "package":
            return [command_name, "--session", session_alias, *command_args[1:]]
        if command_name in {"preview", "convertxml", "list-configs"}:
            return [command_name, "--session", session_alias, *command_args[1:]]
        return command_args

    def _occs_cli_cwd(self) -> str | None:
        cli_path = Path(os.path.expanduser(self._get_occs_cli_path()))
        if not cli_path.exists():
            return None
        if cli_path.parent.name == "bin":
            return str(cli_path.parent.parent)
        return str(cli_path.parent)

    @staticmethod
    def _parse_occs_json_stdout(stdout: str) -> dict[str, object] | None:
        if not stdout:
            return None
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    @staticmethod
    def _occs_error_message(
        parsed: dict[str, object] | None,
        stderr: str,
        return_code: int,
    ) -> str:
        if parsed:
            error = parsed.get("error")
            if isinstance(error, dict):
                message = str(error.get("message", "")).strip()
                if message:
                    details = AToolApp._format_occs_error_details(error.get("details"))
                    return f"{message}{details}"
            message = str(parsed.get("message", "")).strip()
            if message:
                return message
        if stderr:
            return stderr
        return f"OCCS CLI exited with status {return_code}."

    @staticmethod
    def _format_occs_error_details(details: object) -> str:
        if not isinstance(details, dict) or not details:
            return ""

        lines: list[str] = []
        surface = str(details.get("surface", "")).strip()
        method = str(details.get("method", "")).strip()
        url = str(details.get("url", "")).strip()
        status = str(details.get("status", "")).strip()
        status_text = str(details.get("statusText", "")).strip()
        response = details.get("response")

        if surface:
            lines.append(f"Surface: {surface}")
        if method or url:
            lines.append(f"Request: {' '.join([method, url]).strip()}")
        if status or status_text:
            lines.append(f"Status: {' '.join([status, status_text]).strip()}")
        if response:
            response_text = str(response).strip()
            if len(response_text) > 2000:
                response_text = response_text[:2000] + "..."
            lines.append(f"Response: {response_text}")
        return "\n\n" + "\n".join(lines) if lines else ""

    def _on_occs_package_get_complete(self, result: dict[str, object], requested_bundle_dir: str) -> None:
        bundle_path = str(result.get("bundlePath") or requested_bundle_dir)
        if self._load_occs_bundle(bundle_path):
            self._show_temporary_status(f"Loaded package version: {os.path.basename(bundle_path)}", duration_ms=5000)

    def _on_occs_package_get_for_shared_complete(
        self,
        result: dict[str, object],
        requested_bundle_dir: str,
        open_after_publish_mode: str = "",
    ) -> None:
        bundle_path = Path(str(result.get("bundlePath") or requested_bundle_dir))
        try:
            manifest = self._read_occs_manifest(str(bundle_path))
            if open_after_publish_mode == "edit" and not self._can_get_shared_package_for_edit(manifest, bundle_path):
                return
            entry = self._publish_bundle_path_to_shared(bundle_path, manifest, reason="retrievedFromComms")
        except (OSError, ValueError) as error:
            messagebox.showerror(
                "Get Package from Comms",
                f"Retrieved the package version, but could not update the shared package folder.\n\nDetails: {error}",
            )
            return

        self._record_occs_package_mru_from_manifest(manifest)
        if open_after_publish_mode == "edit":
            self._open_shared_entry_for_edit(entry, title="Get Package from Comms")
            return

        self._show_temporary_status("Retrieved package version into shared folder", duration_ms=5000)
        workspace_dir = self._ensure_occs_shared_workspace_dir()
        if workspace_dir is None:
            return
        entries = self._list_shared_package_versions(workspace_dir)
        if entries:
            self._open_shared_package_selection_dialog(entries)

    def _load_occs_bundle(
        self,
        bundle_dir: str,
        shared_package_dir: Path | None = None,
        shared_mode: str = "local",
    ) -> bool:
        try:
            manifest = self._read_occs_manifest(bundle_dir)
            assembly_template_path = self._occs_bundle_assembly_template_path(bundle_dir, manifest)
        except ValueError as error:
            messagebox.showerror("Open Local Package", str(error))
            return False

        if not os.path.exists(assembly_template_path):
            messagebox.showerror(
                "Open Local Package",
                f"Assembly template file not found:\n{assembly_template_path}",
            )
            return False

        self._load_assembly_template(assembly_template_path)
        loaded_bundle_dir = Path(os.path.expanduser(bundle_dir)).resolve()
        if self.current_occs_bundle_dir and Path(self.current_occs_bundle_dir).resolve() == loaded_bundle_dir:
            self.current_occs_shared_package_dir = shared_package_dir
            self.current_occs_shared_mode = shared_mode
            self._restore_default_status_text()
            self._record_occs_package_mru_from_manifest(self.current_occs_manifest)
            return True
        return False

    def _read_occs_manifest(self, bundle_dir: str) -> dict[str, object]:
        manifest_path = Path(os.path.expanduser(bundle_dir)) / "occs-package.json"
        try:
            with open(manifest_path, "r", encoding="utf-8") as source:
                manifest = json.load(source)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Could not read OCCS bundle manifest:\n{manifest_path}\n\nDetails: {error}") from error
        if not isinstance(manifest, dict):
            raise ValueError(f"OCCS bundle manifest must be a JSON object:\n{manifest_path}")
        if str(manifest.get("schemaVersion", "")) != "occs-package-bundle/v1":
            raise ValueError(f"Unsupported OCCS bundle manifest:\n{manifest_path}")
        return manifest

    def _occs_bundle_assembly_template_path(self, bundle_dir: str, manifest: dict[str, object]) -> str:
        files = manifest.get("files")
        relative_path = "assembly-template.json"
        if isinstance(files, dict):
            relative_path = str(files.get("assemblyTemplate") or relative_path)
        candidate = Path(relative_path)
        if candidate.is_absolute():
            return str(candidate)
        return str(Path(os.path.expanduser(bundle_dir)) / candidate)

    def _occs_bundle_version_master_path(self, bundle_dir: str, manifest: dict[str, object]) -> str:
        files = manifest.get("files")
        relative_path = "version-master.json"
        if isinstance(files, dict):
            relative_path = str(files.get("versionMaster") or relative_path)
        candidate = Path(relative_path)
        if candidate.is_absolute():
            return str(candidate)
        return str(Path(os.path.expanduser(bundle_dir)) / candidate)

    def _detect_occs_bundle_for_file(self, loaded_path: str, source_path: str) -> None:
        self.current_occs_bundle_dir = None
        self.current_occs_manifest = None
        self.current_occs_shared_package_dir = None
        self.current_occs_shared_mode = "local"
        candidates = []
        for candidate_path in (loaded_path, source_path):
            if not candidate_path:
                continue
            parent = Path(candidate_path).resolve().parent
            if parent not in candidates:
                candidates.append(parent)

        source_candidates = {
            Path(path).resolve()
            for path in (loaded_path, source_path)
            if path
        }

        for bundle_dir in candidates:
            manifest_path = bundle_dir / "occs-package.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = self._read_occs_manifest(str(bundle_dir))
                assembly_template_path = Path(self._occs_bundle_assembly_template_path(str(bundle_dir), manifest)).resolve()
            except ValueError:
                continue
            if assembly_template_path not in source_candidates:
                continue
            self.current_occs_bundle_dir = str(bundle_dir)
            self.current_occs_manifest = manifest
            self._update_app_state({"last_occs_bundle": str(bundle_dir)})
            return

    def _build_occs_bundle_output_path(self, work_dir: Path, package_name: str, version_name: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        package_segment = self._safe_occs_path_segment(package_name)
        version_segment = self._safe_occs_path_segment(version_name or "latest")
        return work_dir / f"{package_segment}-{version_segment}-{timestamp}"

    def _occs_package_get_timeout_ms(self, version_name: str) -> int:
        normalized = str(version_name or "").strip().lower()
        if not normalized or normalized == "latest":
            return self.OCCS_LATEST_VERSION_TIMEOUT_MS
        return self.OCCS_SPECIFIC_VERSION_TIMEOUT_MS

    def _build_occs_local_copy_path(
        self,
        work_dir: Path,
        package_name: str,
        version_name: str,
        mode: str,
    ) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        package_segment = self._safe_occs_path_segment(package_name)
        version_segment = self._safe_occs_path_segment(version_name)
        mode_segment = self._safe_occs_path_segment(mode)
        return work_dir / f"{package_segment}-{version_segment}-{mode_segment}-{timestamp}"

    def _list_shared_package_versions(self, workspace_dir: Path) -> list[dict[str, object]]:
        packages_dir = workspace_dir / "packages"
        if not packages_dir.exists():
            return []
        entries: list[dict[str, object]] = []
        for package_dir in sorted(packages_dir.iterdir(), key=lambda item: item.name.lower()):
            if not package_dir.is_dir():
                continue
            for version_dir in sorted(package_dir.iterdir(), key=lambda item: item.name.lower()):
                if not version_dir.is_dir():
                    continue
                entry = self._shared_package_entry_from_package_dir(version_dir)
                if entry is not None:
                    entries.append(entry)
        return entries

    def _shared_package_entry_from_package_dir(self, package_dir: Path) -> dict[str, object] | None:
        published_dir = package_dir / "published" / "current"
        manifest_path = published_dir / "occs-package.json"
        if not manifest_path.exists():
            return None
        try:
            manifest = self._read_occs_manifest(str(published_dir))
        except ValueError:
            return None
        publication = self._read_json_object(published_dir / "publication.json")
        package_name = self._occs_manifest_package_short_name(manifest) or package_dir.parent.name
        version_name = self._occs_manifest_version_short_name(manifest) or package_dir.name
        lock_payload = self._read_shared_lock(self._shared_lock_path(package_dir))
        return {
            "workspace_dir": package_dir.parent.parent.parent,
            "package_dir": package_dir,
            "published_dir": published_dir,
            "package_name": package_name,
            "version_name": version_name,
            "manifest": manifest,
            "publication": publication,
            "lock": lock_payload,
        }

    def _refresh_shared_package_entry(self, entry: dict[str, object]) -> dict[str, object] | None:
        package_dir = entry.get("package_dir")
        if not isinstance(package_dir, Path):
            return None
        return self._shared_package_entry_from_package_dir(package_dir)

    @staticmethod
    def _read_json_object(path: Path) -> dict[str, object]:
        try:
            with open(path, "r", encoding="utf-8") as source:
                parsed = json.load(source)
        except (OSError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _shared_baseline_path(bundle_dir: Path) -> Path:
        return bundle_dir / ".atool-shared-baseline.json"

    def _read_shared_baseline_for_local_copy(self, bundle_dir: Path) -> dict[str, object]:
        return self._read_json_object(self._shared_baseline_path(bundle_dir))

    def _write_shared_baseline_for_local_copy(
        self,
        bundle_dir: Path,
        entry: dict[str, object],
        reason: str,
    ) -> None:
        payload = self._build_shared_baseline_payload(entry, reason)
        with open(self._shared_baseline_path(bundle_dir), "w", encoding="utf-8") as target:
            json.dump(payload, target, indent=2)

    def _build_shared_baseline_payload(self, entry: dict[str, object], reason: str) -> dict[str, object]:
        publication = entry.get("publication")
        published_at = ""
        if isinstance(publication, dict):
            published_at = str(publication.get("publishedAt", "")).strip()
        return {
            "schemaVersion": "atool-shared-baseline/v1",
            "capturedAt": self._current_timestamp(),
            "reason": reason,
            "package": str(entry.get("package_name", "")),
            "version": str(entry.get("version_name", "")),
            "publishedDir": str(entry.get("published_dir", "")),
            "publishedAt": published_at,
            "sharedHashes": self._shared_current_hashes_for_entry(entry),
        }

    def _shared_current_hashes_for_entry(self, entry: dict[str, object]) -> dict[str, str]:
        published_dir = entry.get("published_dir")
        manifest = entry.get("manifest")
        if not isinstance(published_dir, Path) or not isinstance(manifest, dict):
            raise ValueError("The shared package entry is missing published package metadata.")
        return self._occs_bundle_current_hashes(published_dir, manifest)

    @staticmethod
    def _shared_hashes_match(expected: dict[object, object], actual: dict[str, str]) -> bool:
        if set(str(key) for key in expected.keys()) != set(actual.keys()):
            return False
        return all(str(value) == str(actual.get(str(key), "")) for key, value in expected.items())

    def _shared_context_from_entry(self, entry: dict[str, object]) -> dict[str, object]:
        return {
            "workspace_dir": entry.get("workspace_dir"),
            "package_dir": entry.get("package_dir"),
            "package_name": str(entry.get("package_name", "")),
            "version_name": str(entry.get("version_name", "")),
            "bundle_dir": entry.get("published_dir"),
            "manifest": entry.get("manifest"),
        }

    def _publish_bundle_path_to_shared(
        self,
        bundle_path: Path,
        manifest: dict[str, object],
        reason: str,
    ) -> dict[str, object]:
        package_dir = self._shared_package_dir_for_manifest(manifest)
        package_name = self._occs_manifest_package_short_name(manifest)
        version_name = self._occs_manifest_version_short_name(manifest)
        context = {
            "workspace_dir": package_dir.parent.parent.parent,
            "package_dir": package_dir,
            "package_name": package_name,
            "version_name": version_name,
            "bundle_dir": bundle_path,
            "manifest": manifest,
            "publicationReason": reason,
        }
        owner = self._current_shared_user_identity()
        published_dir = package_dir / "published" / "current"
        history_dir = package_dir / "published" / "history" / self._shared_publication_folder_name(owner)
        self._copy_occs_bundle_to_shared(context, published_dir)
        self._copy_occs_bundle_to_shared(context, history_dir)
        entry = self._shared_package_entry_from_package_dir(package_dir)
        if entry is None:
            raise OSError("Shared package folder was updated but could not be reloaded.")
        return entry

    def _shared_package_dir_for_manifest(self, manifest: dict[str, object]) -> Path:
        workspace_dir = self._ensure_occs_shared_workspace_dir()
        if workspace_dir is None:
            raise OSError("Shared package folder is not configured.")
        package_name = self._occs_manifest_package_short_name(manifest)
        version_name = self._occs_manifest_version_short_name(manifest)
        if not package_name or not version_name:
            raise OSError("Package manifest is missing package or version metadata.")
        return (
            workspace_dir
            / "packages"
            / self._safe_occs_path_segment(package_name)
            / self._safe_occs_path_segment(version_name)
        )

    @staticmethod
    def _occs_source_hashes_match(
        first_manifest: dict[str, object],
        second_manifest: dict[str, object],
    ) -> bool:
        first_hashes = first_manifest.get("sourceHashes")
        second_hashes = second_manifest.get("sourceHashes")
        return isinstance(first_hashes, dict) and isinstance(second_hashes, dict) and first_hashes == second_hashes

    def _shared_entry_updated_at(self, entry: dict[str, object]) -> str:
        publication = entry.get("publication")
        if isinstance(publication, dict):
            published_at = str(publication.get("publishedAt", "")).strip()
            if published_at:
                return published_at
        manifest = entry.get("manifest")
        if isinstance(manifest, dict):
            created_at = str(manifest.get("createdAt", "")).strip()
            if created_at:
                return created_at
        return ""

    @staticmethod
    def _shared_publication_owner_text(entry: dict[str, object]) -> str:
        publication = entry.get("publication")
        owner = publication.get("owner") if isinstance(publication, dict) else None
        if isinstance(owner, dict):
            display_name = str(owner.get("displayName", "")).strip()
            user = str(owner.get("user", "")).strip()
            host = str(owner.get("host", "")).strip()
            if display_name:
                return display_name
            return f"{user}@{host}".strip("@") or "(unknown)"
        return "(unknown)"

    def _ensure_occs_shared_workspace_dir(self) -> Path | None:
        workspace_text = self._get_occs_shared_workspace_dir()
        if not workspace_text:
            messagebox.showinfo(
                "Shared Package Folder",
                "Set a shared package folder in User Settings first.",
            )
            return None
        workspace_dir = Path(os.path.expanduser(workspace_text))
        try:
            workspace_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            messagebox.showerror(
                "Shared Package Folder",
                f"Could not create shared package folder:\n{workspace_dir}\n\nDetails: {error}",
            )
            return None
        return workspace_dir

    def _current_occs_shared_context(self, show_errors: bool = True) -> dict[str, object] | None:
        if not self.current_occs_bundle_dir or not self.current_occs_manifest:
            if show_errors:
                messagebox.showinfo("Shared Package Folder", "Open a package version first.")
            return None
        workspace_dir = self._ensure_occs_shared_workspace_dir()
        if workspace_dir is None:
            return None
        package_name = self._occs_manifest_package_short_name(self.current_occs_manifest) or self.current_package_name
        version_name = self._occs_manifest_version_short_name(self.current_occs_manifest) or "unknown"
        package_dir = self.current_occs_shared_package_dir
        if package_dir is None:
            package_dir = (
                workspace_dir
                / "packages"
                / self._safe_occs_path_segment(package_name)
                / self._safe_occs_path_segment(version_name)
            )
        return {
            "workspace_dir": workspace_dir,
            "package_dir": package_dir,
            "package_name": package_name,
            "version_name": version_name,
            "bundle_dir": Path(self.current_occs_bundle_dir),
            "manifest": self.current_occs_manifest,
        }

    @staticmethod
    def _shared_lock_path(package_dir: Path) -> Path:
        return package_dir / "locks" / "package.lock.json"

    def _current_shared_user_identity(self) -> dict[str, str]:
        display_name = self._get_occs_user_name() or getpass.getuser()
        return {
            "user": getpass.getuser(),
            "displayName": display_name,
            "host": socket.gethostname(),
        }

    def _build_shared_lock_payload(
        self,
        context: dict[str, object],
        owner: dict[str, str],
    ) -> dict[str, object]:
        manifest = context.get("manifest")
        source_hashes = manifest.get("sourceHashes") if isinstance(manifest, dict) else {}
        package_name = str(context.get("package_name", ""))
        version_name = str(context.get("version_name", ""))
        package_dir = context.get("package_dir")
        shared_baseline_hashes: dict[str, str] = {}
        if isinstance(package_dir, Path):
            entry = self._shared_package_entry_from_package_dir(package_dir)
            if entry is not None:
                try:
                    shared_baseline_hashes = self._shared_current_hashes_for_entry(entry)
                except ValueError:
                    shared_baseline_hashes = {}
        now = self._current_timestamp()
        payload = {
            "schemaVersion": "atool-shared-lock/v1",
            "createdAt": now,
            "updatedAt": now,
            "scope": {
                "type": "package-version",
                "package": package_name,
                "version": version_name,
            },
            "lock": {
                "mode": "edit",
                "supportsFutureScopes": True,
            },
            "package": package_name,
            "version": version_name,
            "owner": owner,
            "bundleDir": str(context.get("bundle_dir", "")),
            "sourceHashes": source_hashes if isinstance(source_hashes, dict) else {},
        }
        if shared_baseline_hashes:
            payload["sharedBaselineHashes"] = shared_baseline_hashes
        return payload

    @staticmethod
    def _read_shared_lock(lock_path: Path) -> dict[str, object] | None:
        if not lock_path.exists():
            return None
        try:
            with open(lock_path, "r", encoding="utf-8") as source:
                payload = json.load(source)
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _is_shared_lock_owner(lock_payload: dict[str, object], owner: dict[str, str]) -> bool:
        lock_owner = lock_payload.get("owner")
        if not isinstance(lock_owner, dict):
            return False
        return (
            str(lock_owner.get("user", "")) == owner.get("user", "")
            and str(lock_owner.get("host", "")) == owner.get("host", "")
        )

    @staticmethod
    def _shared_lock_owner_text(lock_payload: dict[str, object]) -> str:
        owner = lock_payload.get("owner")
        if isinstance(owner, dict):
            display_name = str(owner.get("displayName", "")).strip()
            user = str(owner.get("user", "")).strip()
            host = str(owner.get("host", "")).strip()
            if display_name and host:
                return f"{display_name} ({user}@{host})" if user and user != display_name else f"{display_name}@{host}"
            return f"{user}@{host}".strip("@") or display_name or "(unknown)"
        return "(unknown)"

    @classmethod
    def _format_shared_lock(cls, lock_payload: dict[str, object]) -> str:
        owner_text = cls._shared_lock_owner_text(lock_payload)
        created_at = str(lock_payload.get("createdAt", "")).strip() or "(unknown time)"
        bundle_dir = str(lock_payload.get("bundleDir", "")).strip()
        lines = [f"Owner: {owner_text}", f"Created: {created_at}"]
        if bundle_dir:
            lines.append(f"Local Folder: {bundle_dir}")
        return "\n".join(lines)

    def _copy_occs_bundle_to_shared(self, context: dict[str, object], target_dir: Path) -> None:
        manifest = context.get("manifest")
        bundle_dir = context.get("bundle_dir")
        if not isinstance(manifest, dict) or not isinstance(bundle_dir, Path):
            raise OSError("Invalid package version context.")
        target_dir.mkdir(parents=True, exist_ok=True)
        source_files = {
            "occs-package.json": bundle_dir / "occs-package.json",
            "assembly-template.json": Path(self._occs_bundle_assembly_template_path(str(bundle_dir), manifest)),
            "version-master.json": Path(self._occs_bundle_version_master_path(str(bundle_dir), manifest)),
        }
        for target_name, source_path in source_files.items():
            if not source_path.exists():
                raise OSError(f"Missing package version file: {source_path}")
            shutil.copy2(source_path, target_dir / target_name)
        source_hashes = manifest.get("sourceHashes") if isinstance(manifest, dict) else {}
        source_info = manifest.get("source") if isinstance(manifest, dict) else {}
        package_name = str(context.get("package_name", ""))
        version_name = str(context.get("version_name", ""))
        publication = {
            "schemaVersion": "atool-publication/v1",
            "publishedAt": self._current_timestamp(),
            "scope": {
                "type": "package-version",
                "package": package_name,
                "version": version_name,
            },
            "operation": {
                "reason": str(context.get("publicationReason", "updateFromLocal")),
                "supportsFutureScopes": True,
            },
            "package": package_name,
            "version": version_name,
            "owner": self._current_shared_user_identity(),
            "sourceBundleDir": str(bundle_dir),
            "sourceManifest": {
                "createdAt": str(manifest.get("createdAt", "")),
                "bundlePath": str(manifest.get("bundlePath", "")),
                "source": source_info if isinstance(source_info, dict) else {},
                "sourceHashes": source_hashes if isinstance(source_hashes, dict) else {},
            },
        }
        with open(target_dir / "publication.json", "w", encoding="utf-8") as target:
            json.dump(publication, target, indent=2)

    def _shared_publication_folder_name(self, owner: dict[str, str]) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        user = self._safe_occs_path_segment(owner.get("user", "user"))
        return f"{timestamp}-{user}"

    @staticmethod
    def _safe_occs_path_segment(value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._-")
        return safe or "unnamed"

    def _open_occs_package_list_dialog(
        self,
        packages: list[dict[str, str]],
        query: str = "",
    ) -> None:
        if not packages:
            messagebox.showinfo("Get Packages from Comms", "No packages were found.")
            return

        packages = self._sort_occs_packages(packages)
        dialog = self._create_toplevel(self.root)
        dialog.title("Get Packages from Comms")
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.grab_set()

        container = ttk.Frame(dialog, padding=14)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        filter_row = ttk.Frame(container)
        filter_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        filter_row.columnconfigure(1, weight=1)

        ttk.Label(filter_row, text="Filter:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        filter_var = tk.StringVar(value=query)
        filter_entry = ttk.Entry(filter_row, textvariable=filter_var, width=48)
        filter_entry.grid(row=0, column=1, sticky="ew")

        def _clear_filter() -> None:
            filter_var.set("")
            filter_entry.focus_set()

        ttk.Button(filter_row, text="Clear", command=_clear_filter).grid(row=0, column=2, padx=(6, 0))

        tree = ttk.Treeview(
            container,
            columns=("name", "description"),
            show="tree headings",
            height=min(max(len(packages), 8), 18),
        )
        tree.heading("#0", text="Short Name")
        tree.heading("name", text="Name")
        tree.heading("description", text="Description")
        tree.column("#0", width=180, stretch=False)
        tree.column("name", width=260, stretch=True)
        tree.column("description", width=460, stretch=True)
        tree.grid(row=1, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        status_var = tk.StringVar(value="")
        ttk.Label(container, textvariable=status_var, anchor=tk.W).grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(8, 0),
        )

        package_by_id: dict[str, dict[str, str]] = {}

        def _package_matches(package: dict[str, str], filter_text: str) -> bool:
            if not filter_text:
                return True
            searchable = [
                package.get("shortName", ""),
                package.get("configId", ""),
                package.get("name", ""),
                package.get("description", ""),
                package.get("packageUuid", ""),
            ]
            return self._fuzzy_text_match(filter_text, " ".join(searchable))

        def _render_package_rows(*_args: object) -> None:
            package_by_id.clear()
            tree.delete(*tree.get_children())
            filter_text = filter_var.get().strip()
            visible_packages = [
                package
                for package in packages
                if _package_matches(package, filter_text)
            ]
            for package in visible_packages:
                item_id = tree.insert(
                    "",
                    tk.END,
                    text=package.get("shortName", ""),
                    values=(
                        package.get("name", ""),
                        package.get("description", ""),
                    ),
                )
                package_by_id[item_id] = package
            if package_by_id:
                first_item = next(iter(package_by_id))
                tree.selection_set(first_item)
                tree.focus(first_item)
            status_var.set(f"Showing {len(visible_packages)} of {len(packages)} packages.")

        filter_var.trace_add("write", _render_package_rows)

        buttons = ttk.Frame(container)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Close", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))

        def _selected_package() -> dict[str, str] | None:
            selection = tree.selection()
            if not selection:
                return None
            return package_by_id.get(selection[0])

        def _selected_short_name() -> str:
            package = _selected_package()
            if not package:
                messagebox.showinfo("Get Packages from Comms", "Select a package first.", parent=dialog)
                return ""
            short_name = package.get("shortName", "").strip()
            if not short_name:
                messagebox.showerror(
                    "Get Packages from Comms",
                    "The selected package is missing a short name.",
                    parent=dialog,
                )
                return ""
            return short_name

        def _get_selected_to_local() -> None:
            short_name = _selected_short_name()
            if not short_name:
                return
            dialog.destroy()
            self._select_occs_package_version_from_comms(short_name)

        def _get_selected_to_shared_edit() -> None:
            short_name = _selected_short_name()
            if not short_name:
                return
            dialog.destroy()
            self._select_occs_package_version_from_comms(
                short_name,
                publish_to_shared_after_get=True,
                open_shared_after_get_mode="edit",
            )

        ttk.Button(buttons, text="Get to Local...", command=_get_selected_to_local).grid(
            row=0,
            column=1,
            padx=(0, 8),
        )
        ttk.Button(buttons, text="Get to Shared/Edit...", command=_get_selected_to_shared_edit).grid(row=0, column=2)
        tree.bind("<Double-1>", lambda _event: _get_selected_to_local())

        _render_package_rows()
        filter_entry.focus_set()
        dialog.update_idletasks()
        width = max(dialog.winfo_width(), 900)
        height = max(dialog.winfo_height(), 440)
        x_pos = self.root.winfo_x() + max((self.root.winfo_width() - width) // 2, 0)
        y_pos = self.root.winfo_y() + max((self.root.winfo_height() - height) // 2, 0)
        dialog.geometry(f"{width}x{height}+{x_pos}+{y_pos}")

    def _select_occs_package_version_from_comms(
        self,
        package_name: str,
        publish_to_shared_after_get: bool = False,
        open_shared_after_get_mode: str = "",
    ) -> None:
        package_text = package_name.strip()
        if not package_text:
            messagebox.showerror("Get Packages from Comms", "Package is required.")
            return
        if self._occs_operation_in_progress:
            messagebox.showinfo("Get Packages from Comms", "An OCCS operation is already in progress.")
            return
        if publish_to_shared_after_get and self._ensure_occs_shared_workspace_dir() is None:
            return
        if not self._prompt_save_if_dirty():
            return

        self._run_occs_json_command_async(
            [
                "package",
                "list",
                package_text,
                "--timeout",
                str(self.OCCS_SPECIFIC_VERSION_TIMEOUT_MS),
            ],
            f"Loading Comms package versions for {package_text}...",
            lambda result, selected_package=package_text: self._open_or_probe_occs_package_version_dialog(
                selected_package,
                result,
                publish_to_shared_after_get=publish_to_shared_after_get,
                open_shared_after_get_mode=open_shared_after_get_mode,
            ),
            on_failure=lambda error: messagebox.showerror("Get Packages from Comms", str(error)),
        )

    def _open_or_probe_occs_package_version_dialog(
        self,
        package_name: str,
        result: dict[str, object],
        publish_to_shared_after_get: bool = False,
        open_shared_after_get_mode: str = "",
    ) -> None:
        versions = self._normalize_occs_package_versions(result, package_name)
        if versions:
            self._open_occs_package_version_dialog(
                package_name,
                versions,
                publish_to_shared_after_get=publish_to_shared_after_get,
                open_shared_after_get_mode=open_shared_after_get_mode,
            )
            return

        self._probe_occs_package_versions_from_comms(
            package_name,
            publish_to_shared_after_get=publish_to_shared_after_get,
            open_shared_after_get_mode=open_shared_after_get_mode,
        )

    def _probe_occs_package_versions_from_comms(
        self,
        package_name: str,
        publish_to_shared_after_get: bool = False,
        open_shared_after_get_mode: str = "",
    ) -> None:
        self._run_occs_package_versions_probe_async(
            package_name,
            lambda result, selected_package=package_name: self._open_occs_package_version_dialog(
                selected_package,
                self._normalize_occs_package_versions(result, selected_package),
                publish_to_shared_after_get=publish_to_shared_after_get,
                open_shared_after_get_mode=open_shared_after_get_mode,
            ),
            on_failure=lambda _error: self._open_occs_package_version_dialog(
                package_name,
                [],
                publish_to_shared_after_get=publish_to_shared_after_get,
                open_shared_after_get_mode=open_shared_after_get_mode,
            ),
        )

    def _run_occs_package_versions_probe_async(
        self,
        package_name: str,
        on_success: object,
        on_failure: object | None = None,
    ) -> None:
        if self._occs_operation_in_progress:
            messagebox.showinfo("Get Packages from Comms", "An OCCS operation is already in progress.")
            return

        self._occs_operation_in_progress = True
        if self._status_note_job:
            self.root.after_cancel(self._status_note_job)
            self._status_note_job = None
        self.status_text.set(f"Loading Comms package versions for {package_name}...")
        self._debug_log(f"OCCS package version probe started: {package_name}")

        def _worker() -> None:
            try:
                result = self._run_occs_package_versions_probe(package_name)
                self.root.after(0, lambda result=result: self._on_occs_command_success(result, on_success))
            except Exception as error:  # pragma: no cover - defensive runtime safety
                stack = traceback.format_exc()
                self.root.after(
                    0,
                    lambda error=error, stack=stack: self._on_occs_command_failure(error, stack, on_failure),
                )

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _run_occs_package_versions_probe(self, package_name: str) -> dict[str, object]:
        probe_version = f"__atool_version_probe_{int(time.time())}__"
        probe_output = Path(os.environ.get("TMPDIR") or "/tmp") / f"atool-version-probe-{int(time.time())}"
        command_args = [
            "package",
            "get",
            package_name,
            "--package-version",
            probe_version,
            "--output",
            str(probe_output),
            "--timeout",
            str(self.OCCS_SPECIFIC_VERSION_TIMEOUT_MS),
            "--json",
        ]
        login_attempted = False

        while True:
            completed = self._run_occs_cli(command_args)
            stdout = (completed.stdout or "").strip()
            stderr = (completed.stderr or "").strip()
            parsed = self._parse_occs_json_stdout(stdout)

            if parsed is not None:
                available_versions = self._available_versions_from_occs_error(parsed)
                if available_versions:
                    return {"versions": available_versions}

            if completed.returncode != 0:
                message = self._occs_error_message(parsed, stderr, completed.returncode)
                if not login_attempted and self._should_retry_occs_after_login(command_args, message):
                    self._run_occs_login_for_retry(message)
                    login_attempted = True
                    continue
                raise RuntimeError(message)

            return {"versions": []}

    @staticmethod
    def _available_versions_from_occs_error(parsed: dict[str, object]) -> list[object]:
        error = parsed.get("error")
        details = error.get("details") if isinstance(error, dict) else None
        if not isinstance(details, dict):
            return []
        available_versions = details.get("availableVersions")
        return available_versions if isinstance(available_versions, list) else []

    def _open_occs_package_version_dialog(
        self,
        package_name: str,
        versions: list[dict[str, str]],
        publish_to_shared_after_get: bool = False,
        open_shared_after_get_mode: str = "",
    ) -> None:
        sorted_versions = self._sort_occs_package_versions(versions)
        used_latest_fallback = False
        if not sorted_versions:
            sorted_versions = [
                {
                    "shortName": "latest",
                    "description": "Current version from Comms",
                    "effectiveAt": "",
                    "versionUuid": "",
                    "configId": "",
                }
            ]
            used_latest_fallback = True

        dialog = self._create_toplevel(self.root)
        dialog.title("Select Package Version")
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.grab_set()

        container = ttk.Frame(dialog, padding=14)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        ttk.Label(container, text=package_name, font=("TkDefaultFont", 11, "bold")).grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 8),
        )

        tree = ttk.Treeview(
            container,
            columns=("effective", "description"),
            show="tree headings",
            height=min(max(len(sorted_versions), 5), 14),
        )
        tree.heading("#0", text="Version")
        tree.heading("effective", text="Effective")
        tree.heading("description", text="Description")
        tree.column("#0", width=160, stretch=False)
        tree.column("effective", width=170, stretch=False)
        tree.column("description", width=420, stretch=True)
        tree.grid(row=1, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        version_by_id: dict[str, dict[str, str]] = {}
        for version in sorted_versions:
            item_id = tree.insert(
                "",
                tk.END,
                text=version.get("shortName", ""),
                values=(
                    version.get("effectiveAt", ""),
                    version.get("description", ""),
                ),
            )
            version_by_id[item_id] = version

        if version_by_id:
            first_item = next(iter(version_by_id))
            tree.selection_set(first_item)
            tree.focus(first_item)

        status_text = f"Showing {len(sorted_versions)} package versions."
        if used_latest_fallback:
            status_text = "Comms did not return a version list; latest will request the current version."
        ttk.Label(container, text=status_text, anchor=tk.W).grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(8, 0),
        )

        buttons = ttk.Frame(container)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))

        def _selected_version_name() -> str:
            selection = tree.selection()
            if not selection:
                messagebox.showinfo("Select Package Version", "Select a package version first.", parent=dialog)
                return ""
            version = version_by_id.get(selection[0])
            if not version:
                return ""
            version_name = version.get("shortName", "").strip()
            if not version_name:
                messagebox.showerror(
                    "Select Package Version",
                    "The selected package version is missing a short name.",
                    parent=dialog,
                )
                return ""
            return version_name

        def _submit() -> None:
            version_name = _selected_version_name()
            if not version_name:
                return
            dialog.destroy()
            self._download_occs_package_version(
                package_name,
                version_name,
                publish_to_shared_after_get=publish_to_shared_after_get,
                open_shared_after_get_mode=open_shared_after_get_mode,
            )

        submit_label = "Get to Local"
        if publish_to_shared_after_get:
            submit_label = "Get to Shared/Edit" if open_shared_after_get_mode == "edit" else "Get to Shared"
        ttk.Button(buttons, text=submit_label, command=_submit).grid(row=0, column=1)
        tree.bind("<Double-1>", lambda _event: _submit())

        dialog.update_idletasks()
        width = max(dialog.winfo_width(), 820)
        height = max(dialog.winfo_height(), 360)
        x_pos = self.root.winfo_x() + max((self.root.winfo_width() - width) // 2, 0)
        y_pos = self.root.winfo_y() + max((self.root.winfo_height() - height) // 2, 0)
        dialog.geometry(f"{width}x{height}+{x_pos}+{y_pos}")

    def _download_occs_package_version(
        self,
        package_name: str,
        version_name: str,
        publish_to_shared_after_get: bool = False,
        open_shared_after_get_mode: str = "",
    ) -> None:
        package_text = package_name.strip()
        version_text = version_name.strip() or "latest"
        if not package_text:
            messagebox.showerror("Get Package from Comms", "Package is required.")
            return
        if self._occs_operation_in_progress:
            messagebox.showinfo("Get Package from Comms", "An OCCS operation is already in progress.")
            return

        work_dir = Path(os.path.expanduser(self._get_occs_work_dir()))
        try:
            work_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            messagebox.showerror(
                "Get Package from Comms",
                "Could not create the configured Local Package Folder.\n\n"
                f"Folder:\n{work_dir}\n\n"
                "Update it in Settings > User Settings.\n\n"
                f"Details: {error}",
            )
            return

        bundle_dir = self._build_occs_bundle_output_path(work_dir, package_text, version_text)
        if publish_to_shared_after_get:
            completion = lambda result, requested_bundle_dir=str(bundle_dir): self._on_occs_package_get_for_shared_complete(
                result,
                requested_bundle_dir,
                open_after_publish_mode=open_shared_after_get_mode,
            )
        else:
            completion = lambda result, requested_bundle_dir=str(bundle_dir): self._on_occs_package_get_complete(
                result,
                requested_bundle_dir,
            )
        self._run_occs_json_command_async(
            [
                "package",
                "get",
                package_text,
                "--package-version",
                version_text,
                "--output",
                str(bundle_dir),
                "--timeout",
                str(self._occs_package_get_timeout_ms(version_text)),
            ],
            f"Getting Comms package {package_text} {version_text}...",
            completion,
        )

    @staticmethod
    def _normalize_occs_packages(result: dict[str, object]) -> list[dict[str, str]]:
        packages = result.get("packages")
        if not isinstance(packages, list):
            return []
        normalized: list[dict[str, str]] = []
        for package in packages:
            if not isinstance(package, dict):
                continue
            item = {
                "shortName": str(package.get("shortName", "")).strip(),
                "name": str(package.get("name", "")).strip(),
                "description": str(package.get("description", "")).strip(),
                "packageUuid": str(package.get("packageUuid", "")).strip(),
                "configId": AToolApp._occs_package_config_id(package),
            }
            if item["shortName"]:
                normalized.append(item)
        return AToolApp._sort_occs_packages(normalized)

    @staticmethod
    def _occs_package_config_id(package: dict[object, object]) -> str:
        for key in ("configId", "id", "packageId", "ConfigId", "PackageId"):
            value = package.get(key)
            text = str(value).strip() if value is not None else ""
            if text:
                return text
        configuration = package.get("configuration")
        if isinstance(configuration, dict):
            value = configuration.get("id")
            text = str(value).strip() if value is not None else ""
            if text:
                return text
        return ""

    @staticmethod
    def _sort_occs_packages(packages: list[dict[str, str]]) -> list[dict[str, str]]:
        return sorted(packages, key=AToolApp._occs_package_sort_key)

    @staticmethod
    def _occs_package_sort_key(package: dict[str, str]) -> tuple[int, int, str, str, str]:
        config_id = AToolApp._safe_int(package.get("configId"))
        if config_id is None:
            return (
                1,
                0,
                package.get("shortName", "").lower(),
                package.get("name", "").lower(),
                package.get("packageUuid", "").lower(),
            )
        return (
            0,
            -config_id,
            package.get("shortName", "").lower(),
            package.get("name", "").lower(),
            package.get("packageUuid", "").lower(),
        )

    @staticmethod
    def _normalize_occs_package_versions(
        result: dict[str, object],
        package_name: str = "",
    ) -> list[dict[str, str]]:
        raw_versions: list[object] = []

        root_versions = result.get("versions")
        if isinstance(root_versions, list):
            raw_versions.extend(root_versions)

        root_package = result.get("package")
        if isinstance(root_package, dict):
            raw_versions.extend(AToolApp._raw_occs_package_versions(root_package))

        packages = result.get("packages")
        if isinstance(packages, list):
            package_key = package_name.strip().lower()
            selected_packages: list[dict[object, object]] = []
            for package in packages:
                if not isinstance(package, dict):
                    continue
                short_name = str(package.get("shortName", "")).strip().lower()
                if not package_key or short_name == package_key:
                    selected_packages.append(package)
            if not selected_packages and len(packages) == 1 and isinstance(packages[0], dict):
                selected_packages.append(packages[0])
            for package in selected_packages:
                raw_versions.extend(AToolApp._raw_occs_package_versions(package))

        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw_version in raw_versions:
            item = AToolApp._normalize_occs_package_version(raw_version)
            if item is None:
                continue
            key = item["shortName"].lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(item)
        return AToolApp._sort_occs_package_versions(normalized)

    @staticmethod
    def _raw_occs_package_versions(package: dict[object, object]) -> list[object]:
        versions: list[object] = []
        for key in (
            "versions",
            "packageVersions",
            "package_versions",
            "CommunicationPackageMasterVersions",
            "CommunicationPackageConfigVersions",
        ):
            value = package.get(key)
            if isinstance(value, list):
                versions.extend(value)
        return versions

    @staticmethod
    def _normalize_occs_package_version(raw_version: object) -> dict[str, str] | None:
        if isinstance(raw_version, str):
            short_name = raw_version.strip()
            if not short_name:
                return None
            return {
                "shortName": short_name,
                "description": "",
                "effectiveAt": "",
                "versionUuid": "",
                "configId": "",
            }
        if not isinstance(raw_version, dict):
            return None

        rec = raw_version.get("CommunicationPackageVersionConfigRec")
        if not isinstance(rec, dict):
            rec = raw_version
        info = rec.get("CommunicationPackageVersionConfigInfo") if isinstance(rec, dict) else None
        if not isinstance(info, dict):
            nested_info = raw_version.get("CommunicationPackageVersionConfigInfo")
            info = nested_info if isinstance(nested_info, dict) else {}

        short_name = AToolApp._first_nonempty_text(
            info.get("ShortName"),
            raw_version.get("shortName"),
            raw_version.get("version"),
            raw_version.get("versionName"),
            raw_version.get("name"),
        )
        if not short_name:
            return None

        return {
            "shortName": short_name,
            "description": AToolApp._first_nonempty_text(
                info.get("Desc"),
                raw_version.get("description"),
                raw_version.get("desc"),
            ),
            "effectiveAt": AToolApp._first_nonempty_text(
                raw_version.get("effectiveAt"),
                raw_version.get("effectiveDate"),
                raw_version.get("EffDtTm"),
                raw_version.get("createdAt"),
                AToolApp._occs_version_status_effective_at(raw_version),
                AToolApp._occs_version_status_effective_at(rec),
            ),
            "versionUuid": AToolApp._first_nonempty_text(
                rec.get("CommunicationPackageVersionConfigUuid") if isinstance(rec, dict) else "",
                raw_version.get("versionUuid"),
                raw_version.get("uuid"),
            ),
            "configId": AToolApp._first_nonempty_text(
                info.get("ConfigId"),
                rec.get("ConfigId") if isinstance(rec, dict) else "",
                raw_version.get("configId"),
                raw_version.get("id"),
            ),
        }

    @staticmethod
    def _occs_version_status_effective_at(version: object) -> str:
        if not isinstance(version, dict):
            return ""
        for status_key in ("ConfigurationStatus", "CommunicationPackageVersionConfigStatus", "status"):
            status = version.get(status_key)
            if not isinstance(status, dict):
                continue
            items = status.get("Items")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        effective = AToolApp._first_nonempty_text(item.get("EffDtTm"), item.get("effectiveAt"))
                        if effective:
                            return effective
            effective = AToolApp._first_nonempty_text(status.get("EffDtTm"), status.get("effectiveAt"))
            if effective:
                return effective
        return ""

    @staticmethod
    def _sort_occs_package_versions(versions: list[dict[str, str]]) -> list[dict[str, str]]:
        return sorted(versions, key=AToolApp._occs_package_version_sort_key)

    @staticmethod
    def _occs_package_version_sort_key(version: dict[str, str]) -> tuple[object, ...]:
        effective_at = AToolApp._occs_effective_sort_value(version.get("effectiveAt", ""))
        version_parts = AToolApp._parse_occs_version_number(version.get("shortName", ""))
        padded_version = tuple(-(part or 0) for part in (version_parts or ())[:8])
        padded_version = padded_version + tuple(0 for _ in range(max(0, 8 - len(padded_version))))
        return (
            0 if version_parts else 1,
            padded_version,
            0 if effective_at is not None else 1,
            -effective_at if effective_at is not None else 0,
            version.get("shortName", "").lower(),
        )

    @staticmethod
    def _parse_occs_version_number(value: object) -> tuple[int, ...] | None:
        match = re.search(r"\d+(?:\.\d+)*", str(value or ""))
        if not match:
            return None
        return tuple(int(part) for part in match.group(0).split("."))

    @staticmethod
    def _occs_effective_sort_value(value: object) -> float | None:
        text = str(value or "").strip()
        if not text:
            return None
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            numeric = float(text)
            return numeric / 1000 if numeric > 100000000000 else numeric
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            pass
        for date_format in ("%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, date_format).timestamp()
            except ValueError:
                continue
        return None

    @staticmethod
    def _first_nonempty_text(*values: object) -> str:
        for value in values:
            text = str(value).strip() if value is not None else ""
            if text:
                return text
        return ""

    @staticmethod
    def _normalize_occs_configs(result: dict[str, object]) -> list[dict[str, str]]:
        configs = result.get("configs")
        if not isinstance(configs, list):
            return []
        normalized: list[dict[str, str]] = []
        for config in configs:
            if not isinstance(config, dict):
                continue
            item = {
                "id": str(config.get("id", "")).strip(),
                "shortName": str(config.get("shortName", "")).strip(),
                "name": str(config.get("name", "")).strip(),
                "description": str(config.get("description", "")).strip(),
                "status": str(config.get("status", "")).strip(),
                "effectiveAt": str(config.get("effectiveAt", "")).strip(),
            }
            if item["id"]:
                normalized.append(item)
        return normalized

    @staticmethod
    def _format_occs_config_label(config: dict[str, str]) -> str:
        parts = [
            config.get("shortName", ""),
            config.get("name", ""),
            config.get("id", ""),
        ]
        return " - ".join([part for part in parts if part])

    def _initial_occs_config_selection(
        self,
        labels: list[str],
        configs: list[dict[str, str]],
    ) -> str:
        last_config_id = self._get_last_occs_config_id()
        if not last_config_id:
            return labels[0] if labels else ""
        lowered = last_config_id.lower()
        for label, config in zip(labels, configs):
            if lowered in {
                config.get("id", "").lower(),
                config.get("shortName", "").lower(),
                config.get("name", "").lower(),
            }:
                return label
        return last_config_id

    @staticmethod
    def _occs_config_id_from_selection(
        selection: str,
        config_by_label: dict[str, dict[str, str]],
    ) -> str:
        config = config_by_label.get(selection)
        if config:
            return config.get("id") or config.get("shortName") or selection
        return selection.strip()

    def _format_occs_save_result(
        self,
        result: dict[str, object],
        changed_surfaces: list[str] | None = None,
    ) -> str:
        config = result.get("configId")
        config_text = ""
        if isinstance(config, dict):
            config_bits = [
                str(config.get("shortName", "")).strip(),
                str(config.get("name", "")).strip(),
                str(config.get("resolved", "")).strip(),
            ]
            config_text = " - ".join([bit for bit in config_bits if bit])

        changes = changed_surfaces
        if changes is None:
            raw_changes = result.get("changes")
            changes = [
                str(name)
                for name, changed in (raw_changes.items() if isinstance(raw_changes, dict) else [])
                if changed
            ]

        lines = [
            f"Package: {result.get('package', self._occs_manifest_package_short_name(self.current_occs_manifest))}",
            f"Version: {result.get('version', self._occs_manifest_version_short_name(self.current_occs_manifest))}",
        ]
        if config_text:
            lines.append(f"Config ID: {config_text}")
        lines.append(f"Changed: {', '.join(changes) if changes else 'none'}")
        return "\n".join(lines)

    def _default_preview_timeout_seconds(self, render_types: list[str]) -> int:
        total = sum(
            self.OCCS_PREVIEW_TIMEOUT_SECONDS.get(render_type, 20)
            for render_type in render_types
        )
        return min(max(total, 1), self.OCCS_PREVIEW_MAX_TIMEOUT_SECONDS)

    def _build_occs_preview_output_base(self, data_file_path: Path, package_name: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        package_segment = self._safe_occs_path_segment(package_name)
        return data_file_path.parent / f"{data_file_path.stem}-{package_segment}-preview-{timestamp}"

    def _on_occs_preview_complete(
        self,
        result: dict[str, object],
        render_types: list[str],
        open_after_generation: bool,
    ) -> None:
        stdout = str(result.get("stdout", "")).strip()
        outputs = self._preview_output_paths_from_stdout(stdout)
        if outputs:
            output_text = "\n".join(
                f"{item.get('renderType', '')}: {item.get('path', '')}"
                for item in outputs
            )
        else:
            output_text = stdout or ", ".join(render_types)
        self._show_temporary_status("Package preview complete", duration_ms=5000)

        if not open_after_generation or not outputs:
            messagebox.showinfo("Preview Package", f"Preview complete.\n\nOutput:\n{output_text}")
            return
        open_errors: list[str] = []
        for output in outputs:
            render_type = str(output.get("renderType", ""))
            output_path = Path(str(output.get("path", "")))
            try:
                self._open_occs_preview_output(render_type, output_path)
            except OSError as error:
                open_errors.append(f"{render_type or output_path.name}: {error}")
        if open_errors:
            messagebox.showwarning(
                "Open Preview",
                "Preview files were generated, but one or more files could not be opened.\n\n"
                + "\n".join(open_errors),
            )

    @classmethod
    def _preview_output_paths_from_stdout(cls, stdout: str) -> list[dict[str, str]]:
        outputs: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for raw_line in stdout.splitlines():
            line = cls._strip_ansi_sequences(raw_line).strip()
            match = re.search(r"Preview written \[([A-Z]+)\](?:\s+\[[^\]]+\])?\s+to\s+(.+)$", line)
            if not match:
                continue
            render_type = match.group(1).strip()
            output_path = match.group(2).strip()
            key = (render_type, output_path)
            if not output_path or key in seen:
                continue
            seen.add(key)
            outputs.append({"renderType": render_type, "path": output_path})
        return outputs

    @staticmethod
    def _strip_ansi_sequences(text: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    def _open_occs_preview_output(self, render_type: str, output_path: Path) -> None:
        if not output_path.exists():
            raise OSError(f"File not found: {output_path}")
        program = self._get_occs_preview_open_program(render_type)
        system = platform.system()
        if program:
            if system == "Darwin":
                command = ["open", "-a", program, str(output_path)]
            else:
                command = [program, str(output_path)]
        elif system == "Darwin":
            command = ["open", str(output_path)]
        elif system == "Windows":
            startfile = getattr(os, "startfile", None)
            if not callable(startfile):
                raise OSError("System default opener is unavailable.")
            startfile(str(output_path))
            return
        else:
            command = ["xdg-open", str(output_path)]
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _occs_preview_unpublished_change_reasons(self) -> list[str]:
        reasons: list[str] = []
        if self.is_dirty:
            reasons.append("Current package has unsaved local edits.")

        if self.current_occs_bundle_dir and self.current_occs_manifest:
            try:
                if self._occs_bundle_differs_from_source_hashes(
                    Path(self.current_occs_bundle_dir),
                    self.current_occs_manifest,
                ):
                    reasons.append("Local package copy differs from the last Comms publish.")
            except ValueError as error:
                reasons.append(f"Could not verify local package copy: {error}")

        if self.current_occs_shared_package_dir:
            published_dir = self.current_occs_shared_package_dir / "published" / "current"
            manifest_path = published_dir / "occs-package.json"
            if manifest_path.exists():
                try:
                    shared_manifest = self._read_occs_manifest(str(published_dir))
                    if self._occs_bundle_differs_from_source_hashes(published_dir, shared_manifest):
                        reasons.append("Shared package folder differs from the last Comms publish.")
                except (ValueError, OSError) as error:
                    reasons.append(f"Could not verify shared package folder: {error}")

        deduped: list[str] = []
        seen: set[str] = set()
        for reason in reasons:
            if reason in seen:
                continue
            deduped.append(reason)
            seen.add(reason)
        return deduped

    def _occs_bundle_differs_from_source_hashes(self, bundle_dir: Path, manifest: dict[str, object]) -> bool:
        source_hashes = manifest.get("sourceHashes")
        if not isinstance(source_hashes, dict) or not source_hashes:
            return False
        current_hashes = self._occs_bundle_current_hashes(bundle_dir, manifest)
        for key, source_hash in source_hashes.items():
            current_hash = current_hashes.get(str(key))
            if current_hash is not None and current_hash != str(source_hash):
                return True
        return False

    def _occs_bundle_current_hashes(self, bundle_dir: Path, manifest: dict[str, object]) -> dict[str, str]:
        files = manifest.get("files")
        manifest_path = bundle_dir / "occs-package.json"
        if isinstance(files, dict):
            manifest_candidate = Path(str(files.get("manifest") or "occs-package.json"))
            manifest_path = manifest_candidate if manifest_candidate.is_absolute() else bundle_dir / manifest_candidate
        assembly_template_path = Path(self._occs_bundle_assembly_template_path(str(bundle_dir), manifest))
        version_master_path = Path(self._occs_bundle_version_master_path(str(bundle_dir), manifest))
        return {
            "manifest": self._semantic_json_hash_for_file(manifest_path),
            "assemblyTemplate": self._semantic_json_hash_for_file(assembly_template_path),
            "versionMaster": self._semantic_json_hash_for_file(version_master_path),
        }

    @classmethod
    def _semantic_json_hash_for_file(cls, path: Path) -> str:
        try:
            with open(path, "r", encoding="utf-8") as source:
                payload = json.load(source)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"{path} ({error})") from error
        stable_text = cls._stable_json_string(payload)
        return hashlib.sha256(stable_text.encode("utf-8")).hexdigest()

    @classmethod
    def _stable_json_string(cls, value: object) -> str:
        if isinstance(value, list):
            return "[" + ",".join(cls._stable_json_string(item) for item in value) + "]"
        if isinstance(value, dict):
            parts = []
            for key in sorted(value.keys(), key=str):
                key_text = json.dumps(str(key), ensure_ascii=False, separators=(",", ":"))
                parts.append(f"{key_text}:{cls._stable_json_string(value[key])}")
            return "{" + ",".join(parts) + "}"
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _occs_manifest_package_short_name(manifest: dict[str, object] | None) -> str:
        package_info = manifest.get("package") if isinstance(manifest, dict) else None
        if not isinstance(package_info, dict):
            return ""
        return str(package_info.get("shortName") or package_info.get("name") or "").strip()

    @staticmethod
    def _occs_manifest_version_short_name(manifest: dict[str, object] | None) -> str:
        version_info = manifest.get("version") if isinstance(manifest, dict) else None
        if not isinstance(version_info, dict):
            return ""
        return str(version_info.get("shortName") or "").strip()

    def convert_and_map_data_file(self) -> None:
        if self.current_payload is None:
            messagebox.showinfo("Map", "Open an assembly template first.")
            return
        if self._mapping_in_progress:
            messagebox.showinfo("Map", "A mapping run is already in progress.")
            return
        if self._mapping_dialog_in_progress:
            return
        self.convert_xml_data_file(map_after_generation=True)

    def convert_xml_data_file(self, *, map_after_generation: bool = False) -> None:
        dialog_title = "Convert and Map" if map_after_generation else "Convert XML"
        submit_label = "Convert and Map" if map_after_generation else "Convert"
        if self._occs_operation_in_progress:
            messagebox.showinfo(dialog_title, "An OCCS operation is already in progress.")
            return

        dialog = self._create_toplevel(self.root)
        dialog.title(dialog_title)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.grab_set()

        container = ttk.Frame(dialog, padding=14)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)

        xml_file_var = tk.StringVar(value="")
        reroot_var = tk.StringVar(value="billPrint")
        bill_id_var = tk.StringVar(value="All")
        bill_id_values: list[str] = []

        ttk.Label(container, text="XML File:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        xml_file_entry = ttk.Entry(container, textvariable=xml_file_var, width=58)
        xml_file_entry.grid(row=0, column=1, sticky="ew")

        def _browse_xml_file() -> None:
            selected_path = filedialog.askopenfilename(
                parent=dialog,
                title="Select XML File",
                filetypes=[
                    ("XML Files", "*.xml *.XML"),
                    ("All Files", "*.*"),
                ],
            )
            if selected_path:
                xml_file_var.set(selected_path)
                _refresh_bill_id_picker(selected_path)

        ttk.Button(container, text="Browse...", command=_browse_xml_file).grid(
            row=0,
            column=2,
            sticky="e",
            padx=(6, 0),
        )

        ttk.Label(container, text="Reroot:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        reroot_entry = ttk.Entry(container, textvariable=reroot_var, width=58)
        reroot_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(8, 0))

        ttk.Label(container, text="Bill ID:").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        bill_id_combo = ttk.Combobox(
            container,
            textvariable=bill_id_var,
            values=["All"],
            state="normal",
            width=56,
        )
        bill_id_combo.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(8, 0))

        def _refresh_bill_id_picker(xml_file_text: str) -> None:
            nonlocal bill_id_values
            bill_id_values = []
            xml_path = Path(os.path.expanduser(str(xml_file_text or "").strip()))
            if not xml_path.exists() or not xml_path.is_file():
                bill_id_combo.configure(values=["All"])
                bill_id_var.set("All")
                return
            bill_id_values = self._extract_xml_bill_ids(xml_path)
            values = ["All", *bill_id_values] if bill_id_values else ["All"]
            bill_id_combo.configure(values=values)
            if len(bill_id_values) == 1:
                bill_id_var.set(bill_id_values[0])
            else:
                bill_id_var.set("All")

        def _on_xml_file_changed(*_args: object) -> None:
            _refresh_bill_id_picker(xml_file_var.get())

        xml_file_var.trace_add("write", _on_xml_file_changed)

        buttons = ttk.Frame(container)
        buttons.grid(row=3, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))

        def _submit() -> None:
            xml_file_text = xml_file_var.get().strip()
            reroot = reroot_var.get().strip()
            bill_id = bill_id_var.get().strip()
            if bill_id.lower() == "all":
                bill_id = ""

            if not xml_file_text:
                messagebox.showerror(dialog_title, "XML file is required.", parent=dialog)
                return
            xml_path = Path(os.path.expanduser(xml_file_text))
            if not xml_path.exists() or not xml_path.is_file():
                messagebox.showerror(
                    dialog_title,
                    f"XML file not found:\n{xml_path}",
                    parent=dialog,
                )
                return

            if not bill_id and len(bill_id_values) > 1:
                preview_values = ", ".join(bill_id_values[:8])
                if len(bill_id_values) > 8:
                    preview_values = f"{preview_values}, ..."
                if not messagebox.askokcancel(
                    dialog_title,
                    f"File contains multiple Bill IDs ({len(bill_id_values)}):\n{preview_values}\n\nConvert all?",
                    parent=dialog,
                ):
                    return

            output_path = self._build_convert_xml_output_path(xml_path)
            if output_path.exists() and not messagebox.askyesno(
                dialog_title,
                f"Output file already exists:\n{output_path}\n\nOverwrite it?",
                parent=dialog,
            ):
                return

            args = [
                "convertxml",
                "--input",
                str(xml_path),
                "--output",
                str(output_path),
                "--timeout",
                str(self.OCCS_CONVERT_XML_TIMEOUT_MS),
            ]
            if reroot:
                args.extend(["--reroot", reroot])
            if bill_id:
                extract_expression = bill_id if "=" in bill_id else f"billId={bill_id}"
                args.extend(["--extract", extract_expression])

            dialog.destroy()
            self._run_occs_command_async(
                args,
                f"Converting XML: {xml_path.name}...",
                lambda result, selected_output_path=output_path: self._on_convert_xml_complete(
                    result,
                    selected_output_path,
                    map_after_generation=map_after_generation,
                ),
                on_failure=lambda error: messagebox.showerror(dialog_title, str(error)),
            )

        ttk.Button(buttons, text=submit_label, command=_submit).grid(row=0, column=1)

        xml_file_entry.focus_set()
        dialog.update_idletasks()
        x_pos = self.root.winfo_x() + max((self.root.winfo_width() - dialog.winfo_width()) // 2, 0)
        y_pos = self.root.winfo_y() + max((self.root.winfo_height() - dialog.winfo_height()) // 2, 0)
        dialog.geometry(f"+{x_pos}+{y_pos}")

    @staticmethod
    def _build_convert_xml_output_path(xml_path: Path) -> Path:
        return xml_path.with_suffix(".json")

    @staticmethod
    def _extract_xml_bill_ids(xml_path: Path) -> list[str]:
        bill_ids: list[str] = []
        seen: set[str] = set()
        try:
            for _event, element in ElementTree.iterparse(xml_path, events=("end",)):
                if AToolApp._xml_local_name(element.tag) == "billId":
                    value = (element.text or "").strip()
                    if value and value not in seen:
                        bill_ids.append(value)
                        seen.add(value)
                element.clear()
        except ElementTree.ParseError:
            return []
        return bill_ids

    @staticmethod
    def _xml_local_name(tag: object) -> str:
        text = str(tag or "")
        if "}" in text:
            return text.rsplit("}", 1)[1]
        return text

    def _on_convert_xml_complete(
        self,
        result: dict[str, object],
        output_path: Path,
        *,
        map_after_generation: bool = False,
    ) -> None:
        stdout = str(result.get("stdout", "")).strip()
        converted_paths = self._converted_json_paths_from_stdout(stdout)
        if not converted_paths and output_path.exists():
            converted_paths = [str(output_path)]
        output_text = "\n".join(converted_paths) if converted_paths else str(output_path.parent)
        if map_after_generation:
            self._map_converted_json_output(converted_paths, output_path, output_text)
            return
        messagebox.showinfo("Convert XML", f"XML conversion complete.\n\nOutput:\n{output_text}")
        self._show_temporary_status("XML conversion complete", duration_ms=5000)

    def _map_converted_json_output(
        self,
        converted_paths: list[str],
        output_path: Path,
        output_text: str,
    ) -> None:
        if self.current_payload is None:
            messagebox.showerror(
                "Convert and Map",
                "XML conversion completed, but no assembly template is open for mapping.",
            )
            return
        if self._mapping_in_progress:
            messagebox.showerror(
                "Convert and Map",
                "XML conversion completed, but a mapping run is already in progress.",
            )
            return
        if self._mapping_dialog_in_progress:
            messagebox.showerror(
                "Convert and Map",
                "XML conversion completed, but a mapping file dialog is already open.",
            )
            return

        data_file_path = self._first_existing_converted_json_path(converted_paths, output_path)
        if data_file_path is None:
            messagebox.showerror(
                "Convert and Map",
                "XML conversion completed, but the generated JSON file could not be found for mapping.\n\n"
                f"Output:\n{output_text}",
            )
            return

        self._show_temporary_status(f"XML conversion complete; mapping {data_file_path.name}", duration_ms=5000)
        self._map_data_file_path(str(data_file_path))

    @staticmethod
    def _first_existing_converted_json_path(converted_paths: list[str], output_path: Path) -> Path | None:
        candidates: list[Path] = []
        for path_text in converted_paths:
            candidate = Path(os.path.expanduser(str(path_text).strip()))
            if not candidate.is_absolute():
                candidate = output_path.parent / candidate
            candidates.append(candidate)
        candidates.append(output_path)

        seen: set[Path] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _converted_json_paths_from_stdout(stdout: str) -> list[str]:
        paths: list[str] = []
        for line in stdout.splitlines():
            match = re.search(r"Converted XML to JSON(?:\s+\[[^\]]+\])?:\s+(.+\.json)\s*$", line)
            if match:
                paths.append(match.group(1).strip())
        return paths

    def map_data_file(self) -> None:
        if self.current_payload is None:
            messagebox.showinfo("Map", "Open an assembly template first.")
            return
        if self._mapping_in_progress:
            messagebox.showinfo("Map", "A mapping run is already in progress.")
            return
        if self._mapping_dialog_in_progress:
            return

        initial_dir = ""
        initial_file = ""
        if self.current_data_file_path:
            initial_dir = os.path.dirname(self.current_data_file_path)
            initial_file = os.path.basename(self.current_data_file_path)
        else:
            state = self._read_app_state()
            previous_data_file = state.get("last_data_file")
            if isinstance(previous_data_file, str) and previous_data_file:
                initial_dir = os.path.dirname(previous_data_file)
                initial_file = os.path.basename(previous_data_file)

        self._mapping_dialog_in_progress = True
        self.mapping_status_text.set("Mapping: Opening file dialog")
        self._update_mapping_controls()
        self.root.update_idletasks()
        self.root.after(25, lambda: self._open_data_file_dialog(initial_dir, initial_file))

    def _open_data_file_dialog(self, initial_dir: str, initial_file: str) -> None:
        data_file_path = ""
        try:
            data_file_path = filedialog.askopenfilename(
                title="Open Data File",
                filetypes=[
                    ("JSON Files", "*.json"),
                    ("All Files", "*.*"),
                ],
                initialdir=initial_dir or None,
                initialfile=initial_file or None,
            )
        finally:
            self._mapping_dialog_in_progress = False
        if not data_file_path:
            self.mapping_status_text.set("Mapping: Idle")
            self._update_mapping_controls()
            return

        self._map_data_file_path(data_file_path)

    def _map_data_file_path(self, data_file_path: str) -> None:
        self.current_data_file_path = data_file_path
        self._update_app_state({"last_data_file": data_file_path})
        self._apply_mapping_async(data_file_path=data_file_path)

    def _toggle_mapping_file(self) -> None:
        if self.current_data_file_path is not None:
            self.clear_mapping()
            return
        self.map_data_file()

    def clear_mapping(self) -> None:
        self._mapping_job_id += 1
        self._mapping_in_progress = False
        self.current_data_payload = None
        self.current_data_file_path = None
        self._show_triggered_documents_only = False
        self._triggered_document_names = set()
        self.data_status_text.set("Data: (none)")
        self.mapping_status_text.set("Mapping: Idle")
        for field in self._loaded_fields:
            field.pop("mapped_values", None)
        for document in self._loaded_documents:
            document.pop("triggered", None)
            document.pop("condition_warnings", None)
            document.pop("condition_breakdown", None)
        self._render_documents_tree()
        self._render_fields_tree()
        self.document_count_text.set(f"Documents: {len(self._loaded_documents)}")
        if self._active_layout_node_id:
            details = self._layout_node_details.get(self._active_layout_node_id)
            if isinstance(details, dict):
                self._set_layout_details(details)
        self._update_mapping_controls()

    def save_assembly_template(self) -> bool:
        if not self.current_file_path or self.current_payload is None:
            messagebox.showinfo("Save", "No assembly template is currently loaded.")
            return False

        if not self._sync_active_field_form_to_model():
            return False
        self._sync_active_document_form_to_model()
        self._sync_active_layout_form_to_model()
        self._sync_all_fields_to_payload()
        self._sync_condition_library_to_payload()
        backup_path = self._build_backup_path(self.current_file_path)
        source_backup_path: str | None = None
        wrote_source_file = False
        source_write_error: OSError | None = None
        try:
            with open(backup_path, "w", encoding="utf-8") as backup_target:
                json.dump(self.current_payload, backup_target, indent=2)
            with open(self.current_file_path, "w", encoding="utf-8") as output_target:
                json.dump(self.current_payload, output_target, indent=2)
        except OSError as error:
            messagebox.showerror(
                "Save Error",
                f"Could not save file:\n{self.current_file_path}\n\nDetails: {error}",
            )
            return False

        if (
            self.current_source_file_path
            and self.current_source_file_path != self.current_file_path
        ):
            source_backup_path = self._build_backup_path(self.current_source_file_path)
            try:
                with open(source_backup_path, "w", encoding="utf-8") as backup_target:
                    json.dump(self.current_payload, backup_target, indent=2)
                with open(self.current_source_file_path, "w", encoding="utf-8") as source_target:
                    json.dump(self.current_payload, source_target, indent=2)
                wrote_source_file = True
            except OSError as error:
                source_write_error = error

        self._set_dirty(False)
        if self.current_package_name and self.current_source_file_path:
            document_names = [str(document["name"]) for document in self._loaded_documents]
            self._write_metadata(
                package_name=self.current_package_name,
                source_path=self.current_source_file_path,
                loaded_path=self.current_file_path,
                documents=document_names,
                fields=self._loaded_fields,
            )
        if source_write_error and self.current_source_file_path:
            self._show_temporary_status(
                f"Saved with warning: could not update {os.path.basename(self.current_source_file_path)}",
                duration_ms=7000,
            )
        else:
            self._show_temporary_status(
                f"Saved. Backup: {os.path.basename(backup_path)}",
                duration_ms=5000,
            )
        return True

    def _sync_all_fields_to_payload(self) -> None:
        for field in self._loaded_fields:
            self._sync_field_to_payload(field)

    def _sync_active_field_form_to_model(self) -> bool:
        if self._updating_field_form:
            return True
        if not self._active_field_node_id:
            return True
        return self._apply_field_form_change(path=self.edit_field_path_var.get())

    def _sync_active_layout_form_to_model(self) -> None:
        if self._updating_layout_form:
            return
        if not self._active_layout_node_id:
            return
        self._apply_layout_form_change(name=self.layout_name_edit_var.get())
        self._apply_layout_form_change(condition=self.layout_condition_edit_var.get())
        self._apply_layout_form_change(iteration=self.layout_iteration_edit_var.get())
        self._apply_layout_form_change(path=self.layout_path_edit_var.get())
        self._apply_layout_form_change(type_value=self.layout_type_edit_var.get())
        self._apply_layout_form_change(mandatory=bool(self.layout_mandatory_var.get()))

    def _open_last_assembly_template(self) -> None:
        state = self._read_app_state()
        last_opened_file = state.get("last_opened_file")
        if not isinstance(last_opened_file, str) or not last_opened_file.strip():
            return

        if not os.path.exists(last_opened_file):
            return

        self._load_assembly_template(last_opened_file)

    def _restore_window_geometry(self) -> None:
        state = self._read_app_state()
        geometry = state.get("window_geometry")
        if isinstance(geometry, dict):
            width = self._safe_int(geometry.get("width"))
            height = self._safe_int(geometry.get("height"))
            x_pos = self._safe_int(geometry.get("x"))
            y_pos = self._safe_int(geometry.get("y"))
            if all(value is not None for value in [width, height, x_pos, y_pos]):
                self.root.geometry(f"{width}x{height}+{x_pos}+{y_pos}")
                return

        self._center_default_window()

    def _center_default_window(self) -> None:
        self.root.update_idletasks()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x_pos = max((screen_width - self.DEFAULT_WIDTH) // 2, 0)
        y_pos = max((screen_height - self.DEFAULT_HEIGHT) // 2, 0)
        self.root.geometry(f"{self.DEFAULT_WIDTH}x{self.DEFAULT_HEIGHT}+{x_pos}+{y_pos}")

    def _load_assembly_template(self, file_path: str) -> None:
        try:
            payload, loaded_path, correction_message = self._load_json_payload(file_path)
        except ValueError as error:
            messagebox.showerror(
                "Invalid JSON",
                f"Could not parse JSON in:\n{file_path}\n\nDetails: {error}",
            )
            return
        except OSError as error:
            messagebox.showerror(
                "Open Error",
                f"Could not open file:\n{file_path}\n\nDetails: {error}",
            )
            return

        package_name = str(payload.get("$$Id", "(unknown)"))
        self.current_payload = payload
        self.current_file_path = loaded_path
        self.current_source_file_path = file_path
        self.current_package_name = package_name
        self._detect_occs_bundle_for_file(loaded_path=loaded_path, source_path=file_path)
        self._condition_library_entries = self._load_condition_library(package_name, payload)
        self._active_condition_library_index = None
        self._render_condition_library_list()
        self._populate_condition_library_form(None)
        self._mapping_job_id += 1
        self._mapping_in_progress = False
        self.current_data_payload = None
        self.current_data_file_path = None
        self._show_triggered_documents_only = False
        self._triggered_document_names = set()
        documents = self._extract_documents(payload)
        fields = self._extract_fields(payload)
        fields = self._hydrate_fields_with_cached_paths(package_name, fields)
        self._loaded_documents = documents
        self._loaded_fields = fields

        self._render_documents_tree()
        self._render_fields_tree()

        file_name = os.path.basename(loaded_path)
        self.status_text.set(self._default_status_text())
        self.data_status_text.set("Data: (none)")
        self.mapping_status_text.set("Mapping: Idle")
        self.document_count_text.set(f"Documents: {len(documents)}")
        self.field_count_text.set(f"Fields: {len(fields)}")
        self.root.title(f"ATool - {file_name}")
        self._update_mapping_controls()
        document_names = [str(document["name"]) for document in documents]
        self._write_metadata(
            package_name=package_name,
            source_path=file_path,
            loaded_path=loaded_path,
            documents=document_names,
            fields=fields,
        )
        self._write_app_state(last_opened_file=loaded_path, package_name=package_name)
        self._set_dirty(False)

        if correction_message:
            messagebox.showwarning("JSON Auto-Correction Applied", correction_message)

    def _load_data_payload_or_raise(self, file_path: str) -> object:
        try:
            with open(file_path, "r", encoding="utf-8-sig") as source:
                raw = source.read()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                sanitized = self._strip_trailing_commas(raw)
                return json.loads(sanitized)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Could not parse data file: {error}") from error

    def _apply_mapping_async(self, data_file_path: str | None = None) -> None:
        target_data_file = data_file_path or self.current_data_file_path
        if not target_data_file:
            return
        self._mapping_in_progress = True
        self._mapping_job_id += 1
        mapping_job_id = self._mapping_job_id
        start_time = time.perf_counter()
        self.mapping_status_text.set("Mapping: Running")
        self._update_mapping_controls()

        selected_field = None
        if self._active_field_node_id:
            selected_field = self._field_node_details.get(self._active_field_node_id)

        data_file_name = os.path.basename(target_data_file)
        self.data_status_text.set(
            f"Data: {data_file_name} (loading/map...)" if data_file_name else "Data: (loading/map...)"
        )
        self._debug_log(
            "Mapping started: "
            f"data_file={target_data_file} "
            f"fields={len(self._loaded_fields)}, documents={len(self._loaded_documents)}"
        )

        field_paths = [
            str(field.get("true_path") or field.get("path") or "")
            for field in self._loaded_fields
        ]
        doc_conditions = [
            str(document.get("condition", ""))
            for document in self._loaded_documents
        ]
        condition_library_entries = copy.deepcopy(self._condition_library_entries)

        def _worker() -> None:
            try:
                parse_start_time = time.perf_counter()
                data_payload = self._load_data_payload_or_raise(target_data_file)
                parse_duration = time.perf_counter() - parse_start_time
                self._debug_log(f"Data parse complete: elapsed={parse_duration:.3f}s")

                mapped_values_by_index: dict[int, list[object]] = {}
                for index, path_expr in enumerate(field_paths):
                    mapped_values_by_index[index] = self._extract_values_by_path(data_payload, path_expr)
                    if index and index % 250 == 0:
                        self._debug_log(f"Field mapping progress: {index}/{len(field_paths)}")

                triggered_docs_by_index: dict[int, bool] = {}
                condition_warnings_by_index: dict[int, list[str]] = {}
                condition_breakdowns_by_index: dict[int, list[str]] = {}
                condition_match_details_by_index: dict[int, list[dict[str, object]]] = {}
                for index, condition in enumerate(doc_conditions):
                    condition_warnings: list[str] = []
                    is_triggered = self._evaluate_document_condition(
                        condition,
                        data_payload,
                        warnings=condition_warnings,
                    )
                    triggered_docs_by_index[index] = is_triggered
                    if condition_warnings:
                        condition_warnings_by_index[index] = condition_warnings
                    if is_triggered:
                        condition_breakdowns_by_index[index] = ["PASS Document condition matched."]
                    else:
                        condition_breakdowns_by_index[index] = self._build_document_condition_breakdown(
                            condition,
                            data_payload,
                            is_triggered=is_triggered,
                            entries=condition_library_entries,
                        )
                    condition_match_details_by_index[index] = self._build_document_condition_match_details(
                        condition,
                        data_payload,
                        entries=condition_library_entries,
                    )
                    if index and index % 250 == 0:
                        self._debug_log(f"Document condition progress: {index}/{len(doc_conditions)}")

                duration = time.perf_counter() - start_time
                self.root.after(
                    0,
                    lambda: self._on_mapping_complete(
                        mapping_job_id,
                        data_payload,
                        mapped_values_by_index,
                        triggered_docs_by_index,
                        condition_warnings_by_index,
                        condition_breakdowns_by_index,
                        condition_match_details_by_index,
                        selected_field,
                        duration,
                    ),
                )
            except Exception as error:  # pragma: no cover - defensive runtime safety
                stack = traceback.format_exc()
                self.root.after(
                    0,
                    lambda: self._on_mapping_failed(mapping_job_id, error, stack),
                )

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _on_mapping_complete(
        self,
        mapping_job_id: int,
        data_payload: object,
        mapped_values_by_index: dict[int, list[object]],
        triggered_docs_by_index: dict[int, bool],
        condition_warnings_by_index: dict[int, list[str]],
        condition_breakdowns_by_index: dict[int, list[str]],
        condition_match_details_by_index: dict[int, list[dict[str, object]]],
        selected_field: dict[str, object] | None,
        duration_seconds: float,
    ) -> None:
        if mapping_job_id != self._mapping_job_id:
            return
        self._mapping_in_progress = False
        self.mapping_status_text.set("Mapping: Idle")
        self.current_data_payload = data_payload
        self._show_triggered_documents_only = True

        for index, mapped_values in mapped_values_by_index.items():
            if 0 <= index < len(self._loaded_fields):
                self._loaded_fields[index]["mapped_values"] = mapped_values

        triggered_docs: set[str] = set()
        warning_docs = 0
        for index, is_triggered in triggered_docs_by_index.items():
            if 0 <= index < len(self._loaded_documents):
                document = self._loaded_documents[index]
                document["triggered"] = is_triggered
                warnings = condition_warnings_by_index.get(index, [])
                if warnings:
                    document["condition_warnings"] = warnings
                    warning_docs += 1
                else:
                    document.pop("condition_warnings", None)
                breakdown = condition_breakdowns_by_index.get(index, [])
                if breakdown:
                    document["condition_breakdown"] = breakdown
                else:
                    document.pop("condition_breakdown", None)
                match_details = condition_match_details_by_index.get(index, [])
                if match_details:
                    document["condition_match_details"] = match_details
                else:
                    document.pop("condition_match_details", None)
                if is_triggered:
                    triggered_docs.add(str(document["name"]))
        self._triggered_document_names = triggered_docs
        data_file_name = os.path.basename(self.current_data_file_path or "")
        self.data_status_text.set(f"Data: {data_file_name}" if data_file_name else "Data: (none)")
        self.document_count_text.set(f"Documents: {len(self._loaded_documents)} ({len(triggered_docs)} matched)")
        self._render_documents_tree()
        self._render_fields_tree(selected_field=selected_field)
        if self._active_layout_node_id:
            details = self._layout_node_details.get(self._active_layout_node_id)
            if isinstance(details, dict):
                self._set_layout_details(details)
        self._update_mapping_controls()
        self._debug_log(
            "Mapping complete: "
            f"triggered_docs={len(triggered_docs)} "
            f"warning_docs={warning_docs} "
            f"elapsed={duration_seconds:.3f}s"
        )

    def _refresh_document_condition_mapping(self, document: dict[str, object]) -> None:
        if self.current_data_payload is None:
            return

        document_name = str(document.get("name", ""))
        condition = str(document.get("condition", ""))
        warnings: list[str] = []
        try:
            is_triggered = self._evaluate_document_condition(
                condition,
                self.current_data_payload,
                warnings=warnings,
            )
        except Exception as error:  # pragma: no cover - defensive UI safety
            self._debug_log(f"Could not re-evaluate document trigger '{document_name}': {error}")
            document["triggered"] = False
            document["condition_warnings"] = [f"Could not evaluate condition: {error}"]
            document["condition_breakdown"] = [f"FAIL Could not evaluate document condition: {error}"]
            document["condition_match_details"] = [
                {
                    "label": "Document condition",
                    "passed": False,
                    "details": [f"Reason: could not evaluate ({error})"],
                }
            ]
            self._triggered_document_names.discard(document_name)
            self.document_count_text.set(
                f"Documents: {len(self._loaded_documents)} ({len(self._triggered_document_names)} matched)"
            )
            return

        document["triggered"] = is_triggered
        if warnings:
            document["condition_warnings"] = warnings
        else:
            document.pop("condition_warnings", None)
        if is_triggered:
            document["condition_breakdown"] = ["PASS Document condition matched."]
            self._triggered_document_names.add(document_name)
        else:
            document["condition_breakdown"] = self._build_document_condition_breakdown(
                condition,
                self.current_data_payload,
                is_triggered=is_triggered,
            )
            self._triggered_document_names.discard(document_name)
        document["condition_match_details"] = self._build_document_condition_match_details(
            condition,
            self.current_data_payload,
        )
        self.document_count_text.set(
            f"Documents: {len(self._loaded_documents)} ({len(self._triggered_document_names)} matched)"
        )

    def _on_mapping_failed(self, mapping_job_id: int, error: Exception, stack: str) -> None:
        if mapping_job_id != self._mapping_job_id:
            return
        self._mapping_in_progress = False
        self.mapping_status_text.set("Mapping: Idle")
        data_file_name = os.path.basename(self.current_data_file_path or "")
        self.data_status_text.set(f"Data: {data_file_name}" if data_file_name else "Data: (none)")
        self._update_mapping_controls()
        self._debug_log(f"Mapping failed: {error}\n{stack}")
        messagebox.showerror(
            "Mapping Error",
            f"Mapping failed.\n\nDetails: {error}",
        )

    def _load_json_payload(self, file_path: str) -> tuple[dict, str, str | None]:
        with open(file_path, "r", encoding="utf-8-sig") as source:
            raw = source.read()

        try:
            parsed = json.loads(raw)
            corrected_path = file_path
            correction_message = None
        except json.JSONDecodeError as first_error:
            sanitized = self._strip_trailing_commas(raw)
            try:
                parsed = json.loads(sanitized)
            except json.JSONDecodeError:
                raise ValueError(str(first_error)) from first_error
            corrected_path = self._build_corrected_path(file_path)
            try:
                with open(corrected_path, "w", encoding="utf-8") as target:
                    target.write(sanitized)
            except OSError as write_error:
                raise ValueError(
                    "Found a fixable JSON issue but could not write corrected file. "
                    f"Details: {write_error}"
                ) from write_error
            correction_message = (
                "The selected file had invalid JSON and was auto-corrected.\n\n"
                f"Original parse error: {first_error}\n\n"
                f"Corrected file saved as:\n{corrected_path}"
            )

        if not isinstance(parsed, dict):
            raise ValueError("Top-level JSON value must be an object.")
        return parsed, corrected_path, correction_message

    @staticmethod
    def _build_corrected_path(file_path: str) -> str:
        directory, file_name = os.path.split(file_path)
        stem, ext = os.path.splitext(file_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        extension = ext or ".json"
        return os.path.join(directory, f"{stem}_corrected_{timestamp}{extension}")

    @staticmethod
    def _build_backup_path(file_path: str) -> str:
        directory, file_name = os.path.split(file_path)
        stem, ext = os.path.splitext(file_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        extension = ext or ".json"
        return os.path.join(directory, f"{stem}_backup_{timestamp}{extension}")

    def _write_metadata(
        self,
        package_name: str,
        source_path: str,
        loaded_path: str,
        documents: list[str],
        fields: list[dict[str, object]],
    ) -> None:
        metadata_dir = Path.home() / ".atool"
        metadata_file = metadata_dir / f".{self._slugify(package_name)}.meta.json"
        serialized_clauses = self._serialize_condition_library_entries(self._condition_library_entries)
        payload = {
            "package_name": package_name,
            "source_file": source_path,
            "loaded_file": loaded_path,
            "corrected_file_created": source_path != loaded_path,
            "document_count": len(documents),
            "field_count": len(fields),
            "documents": documents,
            "fields": self._serialize_fields_for_metadata(fields),
            "clause_library": serialized_clauses,
            "clause_library_updated_at": self._current_timestamp(),
            "loaded_at": self._current_timestamp(),
        }

        try:
            metadata_dir.mkdir(parents=True, exist_ok=True)
            with open(metadata_file, "w", encoding="utf-8") as target:
                json.dump(payload, target, indent=2)
        except OSError as error:
            messagebox.showwarning(
                "Metadata Write Warning",
                "The AT loaded, but metadata could not be saved.\n\n"
                f"Target file:\n{metadata_file}\n\nDetails: {error}",
            )

    @staticmethod
    def _serialize_fields_for_metadata(fields: list[dict[str, object]]) -> list[dict[str, object]]:
        serialized: list[dict[str, object]] = []
        for field in fields:
            serialized.append(
                {
                    "name": str(field["name"]),
                    "path": str(field["path"]),
                    "mandatory": bool(field["mandatory"]),
                    "true_path": str(field.get("true_path", "")),
                    "updated": str(field.get("updated", "")),
                    "descr": str(field.get("descr", "")),
                    "path_segments": [
                        str(segment)
                        for segment in field.get("path_segments", [])
                        if isinstance(segment, str)
                    ],
                }
            )
        return serialized

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
        return normalized or "unknown"

    @staticmethod
    def _strip_trailing_commas(text: str) -> str:
        chars: list[str] = []
        index = 0
        in_string = False
        escaped = False

        while index < len(text):
            ch = text[index]

            if in_string:
                chars.append(ch)
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                index += 1
                continue

            if ch == '"':
                in_string = True
                chars.append(ch)
                index += 1
                continue

            if ch == ",":
                lookahead = index + 1
                while lookahead < len(text) and text[lookahead] in " \t\r\n":
                    lookahead += 1
                if lookahead < len(text) and text[lookahead] in "]}":
                    index += 1
                    continue

            chars.append(ch)
            index += 1

        return "".join(chars)

    def _render_documents_tree(self) -> None:
        self.documents_tree.delete(*self.documents_tree.get_children())
        self._document_node_details = {}
        self._clear_document_details()
        self._set_empty_layouts_tree("No document selected")
        self._update_document_context_buttons()
        self._update_document_view_buttons()
        documents = self._get_filtered_documents()
        if not documents:
            empty_message = "No documents found"
            if self.documents_filter_var.get().strip():
                empty_message = "No matching documents"
            elif self.current_data_payload is not None and self._show_triggered_documents_only:
                empty_message = "No triggered documents"
            self._set_empty_documents_tree(empty_message)
            return

        if self.document_view_mode == "hierarchy":
            self._populate_documents_tree_collapsed(documents)
            return

        for document in documents:
            doc_name = str(document["name"])
            tags = self._document_mapping_tags(document)
            node_id = self.documents_tree.insert("", "end", text=doc_name)
            if tags:
                self.documents_tree.item(node_id, tags=tags)
            self._document_node_details[node_id] = {
                "name": doc_name,
                "parent": "",
                "child_count": 0,
                "triggered": bool(document.get("triggered")),
                "updated": str(document.get("updated", "")),
                "descr": str(document.get("descr", "")),
                "condition": str(document.get("condition", "")),
                "condition_warnings": list(document.get("condition_warnings", []))
                if isinstance(document.get("condition_warnings"), list)
                else [],
                "condition_breakdown": list(document.get("condition_breakdown", []))
                if isinstance(document.get("condition_breakdown"), list)
                else [],
                "condition_match_details": list(document.get("condition_match_details", []))
                if isinstance(document.get("condition_match_details"), list)
                else [],
                "path_index": str(document.get("path_index", "")),
                "document_ref": document,
            }

    def _document_mapping_tags(self, document: dict[str, object]) -> tuple[str, ...]:
        if self.current_data_payload is None:
            return ()
        if bool(document.get("triggered")):
            return ("triggered_doc",)
        return ("untriggered_doc",)

    def _set_empty_documents_tree(self, message: str) -> None:
        self.documents_tree.delete(*self.documents_tree.get_children())
        self._document_node_details = {}
        self._clear_document_details()
        self.documents_tree.insert("", "end", text=message)

    def _populate_documents_tree_collapsed(self, documents: list[dict[str, object]]) -> None:
        doc_lookup = {str(document["name"]): document for document in documents}
        doc_set = set(doc_lookup.keys())
        children: dict[str, list[str]] = {}
        roots: list[str] = []

        for doc_name in [str(document["name"]) for document in documents]:
            parent = self._find_document_parent(doc_name, doc_set)
            if parent is None:
                roots.append(doc_name)
                continue
            children.setdefault(parent, []).append(doc_name)

        for root in roots:
            self._insert_document_node_recursive("", root, children, doc_lookup=doc_lookup)

    def _insert_document_node_recursive(
        self,
        parent_node: str,
        doc_name: str,
        children: dict[str, list[str]],
        parent_name: str = "",
        doc_lookup: dict[str, dict[str, object]] | None = None,
    ) -> None:
        node_id = self.documents_tree.insert(parent_node, "end", text=doc_name)
        child_docs = children.get(doc_name, [])
        document = doc_lookup.get(doc_name, {}) if doc_lookup else {}
        tags = self._document_mapping_tags(document)
        if tags:
            self.documents_tree.item(node_id, tags=tags)
        self._document_node_details[node_id] = {
            "name": doc_name,
            "parent": parent_name,
            "child_count": len(child_docs),
            "triggered": bool(document.get("triggered")),
            "updated": str(document.get("updated", "")),
            "descr": str(document.get("descr", "")),
            "condition": str(document.get("condition", "")),
            "condition_warnings": list(document.get("condition_warnings", []))
            if isinstance(document.get("condition_warnings"), list)
            else [],
            "condition_breakdown": list(document.get("condition_breakdown", []))
            if isinstance(document.get("condition_breakdown"), list)
            else [],
            "condition_match_details": list(document.get("condition_match_details", []))
            if isinstance(document.get("condition_match_details"), list)
            else [],
            "path_index": str(document.get("path_index", "")),
            "document_ref": document,
        }
        for child in child_docs:
            self._insert_document_node_recursive(node_id, child, children, doc_name, doc_lookup)

    @staticmethod
    def _find_document_parent(doc_name: str, doc_set: set[str]) -> str | None:
        candidate = doc_name
        while "_" in candidate:
            candidate = candidate.rsplit("_", 1)[0]
            if candidate in doc_set:
                return candidate
        return None

    def _get_filtered_documents(self) -> list[dict[str, object]]:
        base_documents = self._loaded_documents
        if self.current_data_payload is not None and self._show_triggered_documents_only:
            base_documents = [
                document
                for document in base_documents
                if bool(document.get("triggered"))
            ]

        query = self.documents_filter_var.get().strip()
        if not query:
            return base_documents

        matching_names = {
            str(document["name"])
            for document in base_documents
            if self._document_matches_query(document, query)
        }
        if self.document_view_mode == "hierarchy" and matching_names:
            all_names = {str(document["name"]) for document in base_documents}
            for matched_name in list(matching_names):
                ancestor = self._find_document_parent(matched_name, all_names)
                while ancestor:
                    matching_names.add(ancestor)
                    ancestor = self._find_document_parent(ancestor, all_names)

        return [
            document
            for document in base_documents
            if str(document["name"]) in matching_names
        ]

    def _document_matches_query(self, document: dict[str, object], query: str) -> bool:
        searchable = " ".join(
            [
                str(document.get("name", "")),
                str(document.get("updated", "")),
                str(document.get("descr", "")),
                str(document.get("condition", "")),
                str(document.get("path_index", "")),
            ]
        )
        return self._fuzzy_text_match(query, searchable)

    def _extract_documents(self, payload: dict) -> list[dict[str, object]]:
        documents = payload.get("Documents", [])
        if not isinstance(documents, list):
            return []

        extracted: list[dict[str, object]] = []
        for document in documents:
            if not isinstance(document, dict) or not document.get("$$Id"):
                continue
            path_values: list[str] = []
            self._collect_path_values(document, path_values)
            extracted.append(
                {
                    "name": str(document["$$Id"]),
                    "updated": str(document.get("Updated", "")),
                    "descr": str(document.get("Descr", "")),
                    "condition": str(document.get("Condition", "")),
                    "path_index": " ".join(path_values),
                    "source": document,
                }
            )
        return extracted

    def _collect_path_values(self, node: object, collector: list[str]) -> None:
        if isinstance(node, dict):
            path_value = node.get("Path")
            if isinstance(path_value, str) and path_value.strip():
                collector.append(path_value.strip())
            for value in node.values():
                self._collect_path_values(value, collector)
            return
        if isinstance(node, list):
            for item in node:
                self._collect_path_values(item, collector)

    def _extract_fields(self, payload: dict) -> list[dict[str, object]]:
        fields: list[dict[str, object]] = []
        top_level_fields = payload.get("Fields")
        if isinstance(top_level_fields, list):
            self._collect_fields_from_list(top_level_fields, fields)

        deduplicated: list[dict[str, object]] = []
        seen: set[tuple[str, str, bool]] = set()
        for field in fields:
            key = (
                str(field["name"]),
                str(field["path"]),
                bool(field["mandatory"]),
            )
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(field)
        return deduplicated

    def _hydrate_fields_with_cached_paths(
        self,
        package_name: str,
        fields: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        cache = self._load_cached_field_paths(package_name)
        hydrated: list[dict[str, object]] = []

        for field in fields:
            path = str(field["path"])
            cache_key = self._field_cache_key(field)
            cached_entry = cache.get(cache_key)
            if cached_entry:
                true_path = str(cached_entry.get("true_path", path))
                segments = cached_entry.get("path_segments")
                if isinstance(segments, list) and segments:
                    path_segments = [str(segment) for segment in segments]
                else:
                    path_segments = self._path_to_segments(true_path)
            else:
                true_path = self._normalize_true_path(path)
                path_segments = self._path_to_segments(true_path)

            hydrated.append(
                {
                    "name": str(field["name"]),
                    "path": path,
                    "mandatory": bool(field["mandatory"]),
                    "true_path": true_path,
                    "path_segments": path_segments,
                    "updated": str(field.get("updated", "-")),
                    "descr": str(field.get("descr", "")),
                    "source": field.get("source"),
                }
            )

        return hydrated

    def _load_cached_field_paths(self, package_name: str) -> dict[str, dict[str, object]]:
        metadata_file = self._metadata_file_for_package(package_name)
        if not metadata_file.exists():
            return {}

        try:
            with open(metadata_file, "r", encoding="utf-8") as source:
                metadata = json.load(source)
        except (OSError, json.JSONDecodeError):
            return {}

        field_items = metadata.get("fields")
        if not isinstance(field_items, list):
            return {}

        cache: dict[str, dict[str, object]] = {}
        for item in field_items:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            path = item.get("path")
            mandatory = item.get("mandatory")
            if name is None or path is None:
                continue
            key = self._field_cache_key(
                {
                    "name": str(name),
                    "path": str(path),
                    "mandatory": bool(mandatory),
                }
            )
            cache[key] = item
        return cache

    @staticmethod
    def _field_cache_key(field: dict[str, object]) -> str:
        return f'{field["name"]}|{field["path"]}|{int(bool(field["mandatory"]))}'

    def _metadata_file_for_package(self, package_name: str) -> Path:
        return Path.home() / ".atool" / f".{self._slugify(package_name)}.meta.json"

    @staticmethod
    def _app_state_file() -> Path:
        return Path.home() / ".atool" / ".atool.state.json"

    def _update_app_state(self, updates: dict[str, object]) -> None:
        state_file = self._app_state_file()
        payload = self._read_app_state()
        payload.update(updates)
        payload["updated_at"] = datetime.now().isoformat(timespec="seconds")

        try:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(state_file, "w", encoding="utf-8") as target:
                json.dump(payload, target, indent=2)
        except OSError:
            # Non-fatal: app can continue even if state persistence fails.
            return

    def _on_window_configure(self, event: tk.Event) -> None:
        if event.widget is not self.root:
            return
        if self._geometry_write_job:
            self.root.after_cancel(self._geometry_write_job)
        self._geometry_write_job = self.root.after(300, self._persist_window_geometry)
        self._schedule_documents_controls_layout()

    def _persist_window_geometry(self) -> None:
        self._geometry_write_job = None
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x_pos = self.root.winfo_x()
        y_pos = self.root.winfo_y()
        if width <= 1 or height <= 1:
            return
        self._update_app_state(
            {
                "window_geometry": {
                    "width": width,
                    "height": height,
                    "x": x_pos,
                    "y": y_pos,
                }
            }
        )

    def _default_status_text(self) -> str:
        file_name = os.path.basename(self.current_file_path) if self.current_file_path else "(none)"
        package_name = self.current_package_name if self.current_package_name else "(none)"
        occs_suffix = ""
        if self.current_occs_manifest:
            occs_package = self._occs_manifest_package_short_name(self.current_occs_manifest)
            occs_version = self._occs_manifest_version_short_name(self.current_occs_manifest)
            if occs_package or occs_version:
                occs_suffix = f" | Package Version: {occs_package} {occs_version}".rstrip()
                if self.current_occs_shared_package_dir is not None and self.current_occs_shared_mode != "local":
                    occs_suffix = f"{occs_suffix} ({self.current_occs_shared_mode})"
        return f"File: {file_name} | Package: {package_name}{occs_suffix}"

    def _restore_default_status_text(self) -> None:
        self._status_note_job = None
        self.status_text.set(self._default_status_text())

    def _show_temporary_status(self, message: str, duration_ms: int = 5000) -> None:
        if self._status_note_job:
            self.root.after_cancel(self._status_note_job)
            self._status_note_job = None
        self.status_text.set(message)
        self._status_note_job = self.root.after(duration_ms, self._restore_default_status_text)

    def _on_close(self) -> None:
        if not self._prompt_save_if_dirty():
            return
        self._persist_window_geometry()
        self._persist_documents_panel_width()
        self._persist_layouts_panel_width()
        self._persist_fields_window_geometry()
        self._persist_clause_manager_split()
        self._persist_condition_library_window_geometry()
        if self.fields_window is not None and self.fields_window.winfo_exists():
            self.fields_window.destroy()
        if self.condition_usage_window is not None and self.condition_usage_window.winfo_exists():
            self.condition_usage_window.destroy()
        if self.condition_library_window is not None and self.condition_library_window.winfo_exists():
            self.condition_library_window.destroy()
        self.root.destroy()

    def _prompt_save_if_dirty(self) -> bool:
        if not self.is_dirty:
            return True
        choice = messagebox.askyesnocancel(
            "Unsaved Changes",
            "You have unsaved changes. Save before continuing?",
        )
        if choice is None:
            return False
        if choice:
            return self.save_assembly_template()
        return True

    @staticmethod
    def _safe_int(value: object) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _write_app_state(self, last_opened_file: str, package_name: str) -> None:
        self._update_app_state(
            {
                "last_opened_file": last_opened_file,
                "last_package_name": package_name,
            }
        )

    def _read_app_state(self) -> dict[str, object]:
        state_file = self._app_state_file()
        if not state_file.exists():
            return {}
        try:
            with open(state_file, "r", encoding="utf-8") as source:
                parsed = json.load(source)
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(parsed, dict):
            return {}
        return parsed

    def _collect_fields_from_list(
        self,
        field_items: list[object],
        fields: list[dict[str, object]],
    ) -> None:
        for field in field_items:
            if not isinstance(field, dict):
                continue
            name = field.get("Name")
            path = field.get("Path")
            if not name or not path:
                continue
            normalized_path = self._normalize_path_expression(str(path))
            field["Path"] = normalized_path
            fields.append(
                {
                    "name": str(name),
                    "path": normalized_path,
                    "mandatory": self._mandatory_to_bool(field.get("Mandatory")),
                    "updated": str(field.get("Updated", "-")),
                    "descr": str(field.get("Descr", "")),
                    "source": field,
                }
            )

    @staticmethod
    def _mandatory_to_bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes"}
        return bool(value)

    def _populate_fields_tree(self, fields: list[dict[str, object]]) -> None:
        self.fields_tree.delete(*self.fields_tree.get_children())
        self._field_node_details = {}
        self._clear_field_details()
        if not fields:
            empty_message = "No fields found"
            if self.fields_filter_var.get().strip():
                empty_message = "No matching fields"
            self._set_empty_fields_tree(empty_message)
            return
        if self.field_view_mode == "name":
            self._populate_fields_tree_by_name(fields)
            return
        self._populate_fields_tree_by_path(fields)

    def _populate_fields_tree_by_path(self, fields: list[dict[str, object]]) -> None:
        path_nodes: dict[tuple[str, str], str] = {}
        for field in fields:
            parent = ""
            path_segments = field.get("path_segments")
            if not isinstance(path_segments, list) or not path_segments:
                true_path = str(field.get("true_path") or field["path"])
                path_segments = self._path_to_segments(true_path)
            for segment in path_segments:
                key = (parent, segment)
                node_id = path_nodes.get(key)
                if node_id is None:
                    node_id = self.fields_tree.insert(parent, "end", text=segment, open=True)
                    path_nodes[key] = node_id
                parent = node_id
            self._insert_field_leaf(parent, field)

    def _populate_fields_tree_by_name(self, fields: list[dict[str, object]]) -> None:
        sorted_fields = sorted(
            fields,
            key=lambda field: (
                str(field["name"]).casefold(),
                str(field.get("true_path") or field["path"]).casefold(),
            ),
        )
        for field in sorted_fields:
            self._insert_field_leaf("", field)

    def _insert_field_leaf(self, parent: str, field: dict[str, object]) -> None:
        mandatory = bool(field["mandatory"])
        tag = "mandatory_true" if mandatory else "mandatory_false"
        suffix = " [mandatory]" if mandatory else ""
        field_node_id = self.fields_tree.insert(
            parent,
            "end",
            text=f'{field["name"]}{suffix}',
            tags=(tag,),
        )
        self._field_node_details[field_node_id] = field

    def _render_fields_tree(self, selected_field: dict[str, object] | None = None) -> None:
        self._update_view_toggle_label()
        filtered_fields = self._get_filtered_fields()
        self._populate_fields_tree(filtered_fields)
        if selected_field is not None:
            self._select_field_node_for_field(selected_field)

    def _toggle_field_view(self) -> None:
        self.field_view_mode = "name" if self.field_view_mode == "path" else "path"
        self._render_fields_tree()

    def add_field(self) -> None:
        if self.current_payload is None:
            messagebox.showinfo("Add Field", "Open an assembly template first.")
            return
        top_fields = self.current_payload.get("Fields")
        if not isinstance(top_fields, list):
            top_fields = []
            self.current_payload["Fields"] = top_fields

        existing_names = {str(field.get("name", "")) for field in self._loaded_fields}
        counter = 1
        while True:
            candidate = f"NewField{counter}"
            if candidate not in existing_names:
                break
            counter += 1

        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        source_field = {
            "Name": candidate,
            "Mandatory": False,
            "Path": "$",
            "Updated": now_text,
            "Descr": "",
        }
        top_fields.append(source_field)

        new_field = {
            "name": candidate,
            "path": "$",
            "mandatory": False,
            "true_path": "$",
            "path_segments": self._path_to_segments("$"),
            "updated": now_text,
            "descr": "",
            "source": source_field,
        }
        if self.current_data_payload is not None:
            new_field["mapped_values"] = self._extract_values_by_path(self.current_data_payload, "$")
        self._loaded_fields.append(new_field)
        self.field_count_text.set(f"Fields: {len(self._loaded_fields)}")
        self._set_dirty(True)
        self._render_fields_tree(selected_field=new_field)

    def _update_view_toggle_label(self) -> None:
        if not hasattr(self, "view_toggle_button"):
            return
        next_mode_label = "Name" if self.field_view_mode == "path" else "Path"
        self.view_toggle_button.config(text=f"View: {next_mode_label}")

    def _expand_all_fields(self) -> None:
        self._set_all_tree_nodes_open(True)

    def _collapse_all_fields(self) -> None:
        self._set_all_tree_nodes_open(False)

    def _set_all_tree_nodes_open(self, open_state: bool) -> None:
        for node_id in self.fields_tree.get_children(""):
            self._set_tree_node_open_recursive(node_id, open_state)

    def _set_tree_node_open_recursive(self, node_id: str, open_state: bool) -> None:
        self.fields_tree.item(node_id, open=open_state)
        for child_id in self.fields_tree.get_children(node_id):
            self._set_tree_node_open_recursive(child_id, open_state)

    def _get_filtered_fields(self) -> list[dict[str, object]]:
        base_fields = self._loaded_fields
        if self.current_data_payload is not None:
            base_fields = [
                field
                for field in base_fields
                if isinstance(field.get("mapped_values"), list) and len(field.get("mapped_values", [])) > 0
            ]

        query = self.fields_filter_var.get().strip()
        if not query:
            return base_fields
        return [
            field
            for field in base_fields
            if self._field_matches_query(field, query)
        ]

    def _field_matches_query(self, field: dict[str, object], query: str) -> bool:
        searchable = " ".join(
            [
                str(field.get("name", "")),
                str(field.get("descr", "")),
                str(field.get("path", "")),
            ]
        )
        return self._fuzzy_text_match(query, searchable)

    def _fuzzy_text_match(self, query: str, text: str) -> bool:
        normalized_query = query.strip().casefold()
        normalized_text = text.casefold()
        if not normalized_query:
            return True
        tokens = [token for token in normalized_query.split() if token]
        if not tokens:
            return True
        words = [word for word in re.split(r"[^a-z0-9]+", normalized_text) if word]
        for token in tokens:
            if token in normalized_text:
                continue
            if len(token) <= 2 and self._is_subsequence(token, normalized_text):
                continue
            if any(token in word for word in words):
                continue
            if len(token) <= 2 and any(self._is_subsequence(token, word) for word in words):
                continue
            return False
        return True

    @staticmethod
    def _is_subsequence(token: str, text: str) -> bool:
        if token in text:
            return True
        start = 0
        for character in token:
            index = text.find(character, start)
            if index < 0:
                return False
            start = index + 1
        return True

    @staticmethod
    def _stringify_mapping_value(value: object) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _format_field_mapped_value(self, field: dict[str, object], mapped_values: list[object]) -> str:
        values_display = self._format_mapped_nodeset_preview(mapped_values)
        if self._field_uses_length_or_count(field):
            return f"{len(mapped_values)} {values_display}"
        return values_display

    def _field_uses_length_or_count(self, field: dict[str, object]) -> bool:
        expression = str(field.get("path", "")).casefold()
        return (
            ".length(" in expression
            or expression.startswith("$.length(")
            or ".count(" in expression
            or expression.startswith("$.count(")
        )

    def _format_mapped_nodeset_preview(self, mapped_values: list[object]) -> str:
        preview_items = mapped_values[:5]
        preview_json = json.dumps(preview_items, ensure_ascii=False)
        if len(mapped_values) > 5:
            return f"{preview_json} (+{len(mapped_values) - 5} more)"
        return preview_json

    def _build_document_condition_breakdown(
        self,
        condition: str,
        data_payload: object,
        *,
        is_triggered: bool | None = None,
        entries: list[dict[str, str]] | None = None,
    ) -> list[str]:
        condition_body = self._extract_condition_body(condition)
        if not condition_body:
            return ["PASS No condition; document always matches."]

        triggered = (
            is_triggered
            if is_triggered is not None
            else self._evaluate_condition_expression(condition_body, data_payload)
        )
        lines = [
            f"Overall: {self._condition_status_text(triggered)}",
        ]
        library_entries = entries if entries is not None else self._condition_library_entries
        parse_error = ""

        try:
            compose_text, _exact, unmatched_count = self._compose_expression_from_raw_condition_with_entries(
                condition,
                library_entries,
            )
            if compose_text:
                parsed_tree = self._parse_composed_condition_tree(compose_text)
                _passed, leaf_results = self._collect_condition_leaf_results(
                    parsed_tree,
                    data_payload,
                    library_entries,
                )
                lines.extend(self._format_condition_leaf_summary(parsed_tree, leaf_results))
                if unmatched_count:
                    suffix = "s" if unmatched_count != 1 else ""
                    lines.append(f"INFO {unmatched_count} raw fragment{suffix} did not match a saved clause.")
                return self._limit_condition_breakdown_lines(lines)
        except ValueError as error:
            parse_error = str(error)

        if parse_error:
            lines.append(f"INFO Clause breakdown unavailable: {parse_error}")
        raw_leaf_results = self._collect_raw_condition_leaf_results(condition_body, data_payload)
        lines.extend(self._format_condition_leaf_summary(("RAW", condition_body), raw_leaf_results))
        return self._limit_condition_breakdown_lines(lines)

    def _build_document_condition_match_details(
        self,
        condition: str,
        data_payload: object,
        *,
        entries: list[dict[str, str]] | None = None,
    ) -> list[dict[str, object]]:
        condition_body = self._extract_condition_body(condition)
        if not condition_body:
            return [
                {
                    "label": "No condition",
                    "passed": True,
                    "details": ["Document always matches."],
                }
            ]

        library_entries = entries if entries is not None else self._condition_library_entries
        try:
            compose_text, _exact, _unmatched_count = self._compose_expression_from_raw_condition_with_entries(
                condition,
                library_entries,
            )
            if compose_text:
                parsed_tree = self._parse_composed_condition_tree(compose_text)
                _passed, leaf_results = self._collect_condition_leaf_results(
                    parsed_tree,
                    data_payload,
                    library_entries,
                )
                return leaf_results
        except ValueError:
            pass

        return self._collect_raw_condition_leaf_results(condition_body, data_payload)

    @staticmethod
    def _condition_status_text(passed: bool) -> str:
        return "PASS" if passed else "FAIL"

    def _parse_composed_condition_tree(self, compose_text: str) -> tuple[str, object]:
        tokens = self._tokenize_clause_expression(compose_text)
        if not tokens:
            raise ValueError("Composed expression is empty.")
        position = 0

        def parse_or() -> tuple[str, object]:
            nonlocal position
            parts: list[tuple[str, object]] = [parse_and()]
            while position < len(tokens) and tokens[position][0] == "OR":
                position += 1
                parts.append(parse_and())
            if len(parts) == 1:
                return parts[0]
            return ("OR", parts)

        def parse_and() -> tuple[str, object]:
            nonlocal position
            parts: list[tuple[str, object]] = [parse_term()]
            while position < len(tokens) and tokens[position][0] == "AND":
                position += 1
                parts.append(parse_term())
            if len(parts) == 1:
                return parts[0]
            return ("AND", parts)

        def parse_term() -> tuple[str, object]:
            nonlocal position
            if position >= len(tokens):
                raise ValueError("Unexpected end of expression.")
            token_type, token_value = tokens[position]
            if token_type == "LPAREN":
                position += 1
                inner = parse_or()
                if position >= len(tokens) or tokens[position][0] != "RPAREN":
                    raise ValueError("Missing closing parenthesis in composed expression.")
                position += 1
                return inner
            if token_type == "RAW":
                position += 1
                return ("RAW", token_value)
            if token_type == "NAME":
                position += 1
                return ("NAME", token_value)
            raise ValueError(f"Unexpected token '{token_value}'.")

        parsed_tree = parse_or()
        if position != len(tokens):
            raise ValueError("Unexpected trailing tokens in composed expression.")
        return parsed_tree

    def _collect_condition_leaf_results(
        self,
        node: tuple[str, object],
        data_payload: object,
        entries: list[dict[str, str]],
    ) -> tuple[bool, list[dict[str, object]]]:
        kind, value = node
        if kind in {"AND", "OR"}:
            assert isinstance(value, list)
            child_results = [
                self._collect_condition_leaf_results(child, data_payload, entries)
                for child in value
            ]
            passed = all(result for result, _leaves in child_results) if kind == "AND" else any(
                result for result, _leaves in child_results
            )
            leaves: list[dict[str, object]] = []
            for _result, child_leaves in child_results:
                leaves.extend(child_leaves)
            return passed, leaves

        if kind == "NAME":
            clause_name = str(value)
            try:
                clause_expression = self._resolve_clause_expression_by_name_from_entries(entries, clause_name)
            except ValueError as error:
                return False, [
                    {
                        "label": clause_name,
                        "passed": False,
                        "details": [f"Reason: {error}"],
                    }
                ]
            return self._collect_condition_leaf_result(clause_name, clause_expression, data_payload)

        if kind == "RAW":
            leaves = self._collect_raw_condition_leaf_results(str(value), data_payload)
            passed = all(bool(leaf.get("passed")) for leaf in leaves) if leaves else True
            return passed, leaves

        return False, [
            {
                "label": f"Unknown condition node: {kind}",
                "passed": False,
                "details": [],
            }
        ]

    def _collect_raw_condition_leaf_results(
        self,
        expression: str,
        data_payload: object,
    ) -> list[dict[str, object]]:
        atomic_clauses = self._collect_atomic_condition_clauses(expression)
        if not atomic_clauses:
            _passed, leaves = self._collect_condition_leaf_result("RAW condition", expression, data_payload)
            return leaves
        leaves: list[dict[str, object]] = []
        for clause in atomic_clauses:
            passed, details = self._describe_atomic_condition_result(clause, data_payload)
            leaves.append(
                {
                    "label": clause,
                    "passed": passed,
                    "details": details,
                }
            )
        return leaves

    def _collect_condition_leaf_result(
        self,
        label: str,
        expression: str,
        data_payload: object,
    ) -> tuple[bool, list[dict[str, object]]]:
        body = self._extract_condition_body(expression).strip()
        if not body:
            return True, [{"label": label, "passed": True, "details": ["No condition; always matches."]}]

        try:
            passed = self._evaluate_condition_expression(body, data_payload)
        except Exception as error:  # pragma: no cover - defensive diagnostic guard
            return False, [{"label": label, "passed": False, "details": [f"Reason: could not evaluate ({error})"]}]

        atomic_clauses = self._collect_atomic_condition_clauses(body)
        failing_details: list[str] = []
        all_details: list[str] = []
        fallback_details: list[str] = []
        for clause in atomic_clauses:
            atomic_passed, atomic_details = self._describe_atomic_condition_result(clause, data_payload)
            if atomic_details:
                status = self._condition_status_text(atomic_passed)
                all_details.append(f"{status} {clause}")
                all_details.extend(atomic_details)
                if not atomic_passed:
                    failing_details.append(f"{status} {clause}")
                    failing_details.extend(atomic_details)
            else:
                all_details.append(f"{self._condition_status_text(atomic_passed)} {clause}")
                if not atomic_passed:
                    fallback_details.append(f"Check: {clause}")

        if passed:
            return True, [{"label": label, "passed": True, "details": all_details}]
        return False, [
            {
                "label": label,
                "passed": False,
                "details": failing_details or fallback_details or all_details,
            }
        ]

    def _format_condition_leaf_summary(
        self,
        root_node: tuple[str, object],
        leaf_results: list[dict[str, object]],
    ) -> list[str]:
        lines: list[str] = []
        logic_text = self._condition_logic_text(root_node)
        if logic_text:
            lines.append(f"Logic: {logic_text}")

        failed = [result for result in leaf_results if not bool(result.get("passed"))]
        passed = [result for result in leaf_results if bool(result.get("passed"))]

        if failed:
            lines.append("")
            lines.append("Failed clauses:")
            for result in failed:
                lines.append(f"- {result.get('label', '(unnamed clause)')}")
                details = result.get("details", [])
                if isinstance(details, list):
                    for detail in details:
                        lines.append(f"  {detail}")
        else:
            lines.append("")
            lines.append("Failed clauses: none")

        if passed:
            lines.append("")
            lines.append("Passed clauses:")
            for result in passed:
                lines.append(f"- {result.get('label', '(unnamed clause)')}")
        return lines

    def _condition_logic_text(self, node: tuple[str, object]) -> str:
        kind, value = node
        if kind == "AND":
            assert isinstance(value, list)
            count = len(value)
            item_text = "clause" if count == 1 else "clauses"
            return f"AND - all {count} {item_text} must pass."
        if kind == "OR":
            assert isinstance(value, list)
            count = len(value)
            item_text = "clause" if count == 1 else "clauses"
            return f"OR - at least one of {count} {item_text} must pass."
        return ""

    def _describe_atomic_condition_result(
        self,
        expression: str,
        data_payload: object,
    ) -> tuple[bool, list[str]]:
        expr = self._strip_outer_parens(expression)
        passed, details = self._evaluate_atomic_condition_with_detail(expr, data_payload)

        empty_match = re.match(r"^(.*?)\s+empty\s+(true|false)\s*$", expr, flags=re.IGNORECASE)
        if empty_match:
            path = empty_match.group(1).strip()
            expect_empty = empty_match.group(2).lower() == "true"
            expected = (
                f"{path} should be empty or missing."
                if expect_empty
                else f"{path} should be present and non-empty."
            )
            return passed, [
                f"Check: {expr}",
                f"Expected: {expected}",
                f"Found: {self._humanize_condition_detail(details)}",
            ]

        size_match = self._find_top_level_word_operator(expr, "size")
        if size_match is not None:
            path, expected_size = size_match
            return passed, [
                f"Check: {expr}",
                f"Expected: {path} should resolve to {expected_size} value(s).",
                f"Found: {self._humanize_condition_detail(details)}",
            ]

        comparison = self._find_top_level_comparison(expr)
        if comparison is not None:
            lhs, operator, rhs = comparison
            return passed, [
                f"Check: {expr}",
                f"Expected: {lhs} {operator} {rhs}",
                f"Found: {self._humanize_condition_detail(details)}",
            ]

        return passed, [
            f"Check: {expr}",
            "Expected: path/expression should find at least one value.",
            f"Found: {self._humanize_condition_detail(details)}",
        ]

    @staticmethod
    def _humanize_condition_detail(details: str) -> str:
        text = str(details or "").strip()
        if text == "values=[]":
            return "no values."
        if text.startswith("values="):
            return f"values found: {text[len('values='):]}"
        size_match = re.match(r"^size=(\d+)\s+values=(.*?)\s+expected=(.*)$", text)
        if size_match:
            return (
                f"size {size_match.group(1)}; "
                f"values found: {size_match.group(2)}; "
                f"expected sizes: {size_match.group(3)}"
            )
        left_right_match = re.match(r"^left=(.*?)\s+right=(.*)$", text)
        if left_right_match:
            return f"left values: {left_right_match.group(1)}; right values: {left_right_match.group(2)}"
        if text.startswith("parent path missing:"):
            return text + "."
        if text.startswith("filtered parent path missing:"):
            return text + "."
        return text

    def _limit_condition_breakdown_lines(self, lines: list[str]) -> list[str]:
        max_lines = 80
        max_line_length = 320
        limited = [self._truncate_ui_text(str(line), max_line_length) for line in lines[:max_lines]]
        if len(lines) > max_lines:
            limited.append(f"... {len(lines) - max_lines} more diagnostic line(s)")
        return limited

    def _evaluate_document_condition(
        self,
        condition: str,
        data_payload: object,
        *,
        comms_compatible: bool = True,
        warnings: list[str] | None = None,
    ) -> bool:
        text = self._extract_condition_body(condition)
        if not text:
            return True
        return self._evaluate_condition_expression(
            text,
            data_payload,
            comms_compatible=comms_compatible,
            warnings=warnings,
        )

    def _evaluate_condition_expression(
        self,
        expression: str,
        data_payload: object,
        *,
        comms_compatible: bool = True,
        warnings: list[str] | None = None,
    ) -> bool:
        expr = self._strip_outer_parens(expression)
        if not expr:
            return True

        or_parts = self._split_top_level_operator(expr, "||")
        if len(or_parts) > 1:
            return any(
                self._evaluate_condition_expression(
                    part,
                    data_payload,
                    comms_compatible=comms_compatible,
                    warnings=warnings,
                )
                for part in or_parts
            )

        and_parts = self._split_top_level_operator(expr, "&&")
        if len(and_parts) > 1:
            return all(
                self._evaluate_condition_expression(
                    part,
                    data_payload,
                    comms_compatible=comms_compatible,
                    warnings=warnings,
                )
                for part in and_parts
            )

        return self._evaluate_atomic_condition(
            expr,
            data_payload,
            comms_compatible=comms_compatible,
            warnings=warnings,
        )

    def _evaluate_atomic_condition(
        self,
        expression: str,
        data_payload: object,
        *,
        comms_compatible: bool = True,
        warnings: list[str] | None = None,
    ) -> bool:
        expr = self._strip_outer_parens(expression)
        if not expr:
            return True

        empty_match = re.match(r"^(.*?)\s+empty\s+(true|false)\s*$", expr, flags=re.IGNORECASE)
        if empty_match:
            path = empty_match.group(1).strip()
            expect_empty = empty_match.group(2).lower() == "true"
            return self._evaluate_empty_check(
                data_payload,
                path,
                expect_empty,
                comms_compatible=comms_compatible,
                warnings=warnings,
            )

        size_match = self._find_top_level_word_operator(expr, "size")
        if size_match is not None:
            path, expected_size = size_match
            values = self._evaluate_condition_operand(data_payload, path)
            expected_values = self._evaluate_condition_operand(data_payload, expected_size)
            if not expected_values:
                return False
            return self._compare_condition_operand_values([len(values)], "==", expected_values)

        comparison = self._find_top_level_comparison(expr)
        if comparison is not None:
            lhs, operator, rhs = comparison
            left_values = self._evaluate_condition_operand(data_payload, lhs)
            right_values = self._evaluate_condition_operand(data_payload, rhs)
            if operator in {"==", "!="}:
                missing_result = self._compare_missing_condition_operand_values(
                    left_values,
                    operator,
                    right_values,
                    comms_compatible=comms_compatible,
                )
                if missing_result is not None:
                    return bool(missing_result[0])
            if not left_values or not right_values:
                return False
            return self._compare_condition_operand_values(left_values, operator, right_values)

        values = self._evaluate_condition_operand(data_payload, expr)
        return len(values) > 0

    def _evaluate_empty_check(
        self,
        data_payload: object,
        path_expression: str,
        expect_empty: bool,
        *,
        comms_compatible: bool = True,
        warnings: list[str] | None = None,
    ) -> bool:
        normalized_full_path = self._normalize_condition_path(path_expression)
        parent_path = self._get_empty_check_parent_path(normalized_full_path)
        parent_values = self._extract_values_by_path(data_payload, parent_path)
        if len(parent_values) == 0:
            if comms_compatible and expect_empty and self._path_has_filter(normalized_full_path):
                if warnings is not None:
                    self._append_condition_warning(
                        warnings,
                        "Filtered empty check has a missing parent path: "
                        f"{parent_path}. Comms may require an explicit null/empty guard or an empty array.",
                    )
                return False
            return expect_empty

        full_values = self._extract_values_by_path(data_payload, normalized_full_path)
        is_empty = len(full_values) == 0
        return is_empty if expect_empty else not is_empty

    @staticmethod
    def _path_has_filter(path_expression: str) -> bool:
        return "[?(" in path_expression

    @staticmethod
    def _append_condition_warning(warnings: list[str], warning: str) -> None:
        if warning not in warnings:
            warnings.append(warning)

    @staticmethod
    def _get_empty_check_parent_path(path_expression: str) -> str:
        normalized = path_expression.strip()
        filter_index = normalized.find("[?(")
        if filter_index >= 0:
            return normalized[:filter_index].strip()
        dot_index = normalized.rfind(".")
        if dot_index > 0:
            return normalized[:dot_index].strip()
        return normalized

    def _evaluate_condition_operand(self, data_payload: object, expression: str) -> list[object]:
        literal_value, is_literal = self._parse_condition_literal(expression)
        if is_literal:
            return [literal_value]
        path = self._normalize_condition_path(expression)
        return self._extract_values_by_path(data_payload, path)

    def _compare_condition_operand_values(
        self, left_values: list[object], operator: str, right_values: list[object]
    ) -> bool:
        if operator == "!=":
            for left in left_values:
                for right in right_values:
                    if self._compare_single_condition_value(left, "==", right):
                        return False
            return True

        for left in left_values:
            for right in right_values:
                if self._compare_single_condition_value(left, operator, right):
                    return True
        return False

    def _compare_missing_condition_operand_values(
        self,
        left_values: list[object],
        operator: str,
        right_values: list[object],
        *,
        comms_compatible: bool,
    ) -> tuple[bool, str, list[object]] | None:
        if bool(left_values) == bool(right_values):
            return None

        missing_side = "left" if not left_values else "right"
        present_values = right_values if not left_values else left_values

        if operator == "!=":
            return self._missing_left_satisfies_not_equal(present_values), missing_side, present_values

        if operator == "==" and comms_compatible:
            return all(value is None for value in present_values), missing_side, present_values

        return None

    @staticmethod
    def _missing_left_satisfies_not_equal(right_values: list[object]) -> bool:
        return all(value is not None for value in right_values)

    @staticmethod
    def _compare_single_condition_value(value: object, operator: str, rhs: object) -> bool:
        if operator in (">", "<", ">=", "<="):
            try:
                left = float(value)
                right = float(rhs)
            except (TypeError, ValueError):
                return False
            if operator == ">":
                return left > right
            if operator == "<":
                return left < right
            if operator == ">=":
                return left >= right
            return left <= right

        if operator == "==":
            return AToolApp._js_like_strict_equals(value, rhs)
        if operator == "!=":
            return not AToolApp._js_like_strict_equals(value, rhs)
        return False

    @staticmethod
    def _js_like_strict_equals(left: object, right: object) -> bool:
        if left is None or right is None:
            return left is right
        left_is_bool = isinstance(left, bool)
        right_is_bool = isinstance(right, bool)
        if left_is_bool or right_is_bool:
            return left_is_bool and right_is_bool and (left is right)

        number_types = (int, float)
        if isinstance(left, number_types) and isinstance(right, number_types):
            return float(left) == float(right)

        if isinstance(left, str) and isinstance(right, str):
            return left == right

        if isinstance(left, (dict, list)) or isinstance(right, (dict, list)):
            return left is right

        if type(left) is not type(right):
            return False
        return left == right

    @staticmethod
    def _parse_condition_literal(text: str) -> tuple[object, bool]:
        stripped = text.strip()
        if (stripped.startswith("'") and stripped.endswith("'")) or (
            stripped.startswith('"') and stripped.endswith('"')
        ):
            return stripped[1:-1], True
        lowered = stripped.lower()
        if lowered == "true":
            return True, True
        if lowered == "false":
            return False, True
        if lowered == "null":
            return None, True
        try:
            if re.match(r"^-?\d+(\.\d+)?$", stripped):
                return float(stripped), True
        except ValueError:
            pass
        return None, False

    @staticmethod
    def _first_integral_condition_value(values: list[object]) -> int | None:
        if not values:
            return None
        value = values[0]
        if isinstance(value, bool):
            return None
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None
        if not numeric_value.is_integer():
            return None
        return int(numeric_value)

    @staticmethod
    def _find_top_level_comparison(expression: str) -> tuple[str, str, str] | None:
        text = expression
        operators = ("==", "!=", "<=", ">=", "<", ">")
        paren_depth = 0
        bracket_depth = 0
        quote = ""
        escaped = False
        index = 0
        while index < len(text):
            char = text[index]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = ""
                index += 1
                continue

            if char in {"'", '"'}:
                quote = char
                index += 1
                continue
            if char == "(":
                paren_depth += 1
                index += 1
                continue
            if char == ")":
                paren_depth = max(0, paren_depth - 1)
                index += 1
                continue
            if char == "[":
                bracket_depth += 1
                index += 1
                continue
            if char == "]":
                bracket_depth = max(0, bracket_depth - 1)
                index += 1
                continue

            if paren_depth == 0 and bracket_depth == 0:
                for operator in operators:
                    if text[index : index + len(operator)] == operator:
                        left = text[:index].strip()
                        right = text[index + len(operator) :].strip()
                        return left, operator, right
            index += 1
        return None

    @staticmethod
    def _find_top_level_word_operator(expression: str, operator: str) -> tuple[str, str] | None:
        text = expression
        operator_text = operator.strip()
        if not text or not operator_text:
            return None

        paren_depth = 0
        bracket_depth = 0
        quote = ""
        escaped = False
        index = 0
        while index < len(text):
            char = text[index]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = ""
                index += 1
                continue

            if char in {"'", '"'}:
                quote = char
                index += 1
                continue
            if char == "(":
                paren_depth += 1
                index += 1
                continue
            if char == ")":
                paren_depth = max(0, paren_depth - 1)
                index += 1
                continue
            if char == "[":
                bracket_depth += 1
                index += 1
                continue
            if char == "]":
                bracket_depth = max(0, bracket_depth - 1)
                index += 1
                continue

            if paren_depth == 0 and bracket_depth == 0:
                candidate = text[index : index + len(operator_text)]
                if candidate.lower() == operator_text.lower():
                    before = text[index - 1] if index > 0 else ""
                    after_index = index + len(operator_text)
                    after = text[after_index] if after_index < len(text) else ""
                    if (not before or before.isspace()) and (not after or after.isspace()):
                        left = text[:index].strip()
                        right = text[after_index:].strip()
                        if left and right:
                            return left, right
            index += 1
        return None

    @staticmethod
    def _split_top_level_operator(expression: str, operator: str) -> list[str]:
        parts: list[str] = []
        current: list[str] = []
        paren_depth = 0
        bracket_depth = 0
        quote = ""
        escaped = False
        index = 0
        while index < len(expression):
            char = expression[index]
            if quote:
                current.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = ""
                index += 1
                continue

            if char in {"'", '"'}:
                quote = char
                current.append(char)
                index += 1
                continue
            if char == "(":
                paren_depth += 1
                current.append(char)
                index += 1
                continue
            if char == ")":
                paren_depth -= 1
                current.append(char)
                index += 1
                continue
            if char == "[":
                bracket_depth += 1
                current.append(char)
                index += 1
                continue
            if char == "]":
                bracket_depth -= 1
                current.append(char)
                index += 1
                continue

            is_split = (
                paren_depth == 0
                and bracket_depth == 0
                and expression[index : index + len(operator)] == operator
            )
            if is_split:
                token = "".join(current).strip()
                if token:
                    parts.append(token)
                current = []
                index += len(operator)
                continue

            current.append(char)
            index += 1

        tail = "".join(current).strip()
        if tail:
            parts.append(tail)
        return parts

    @staticmethod
    def _strip_outer_parens(text: str) -> str:
        expression = str(text or "").strip()
        while expression.startswith("(") and expression.endswith(")"):
            depth = 0
            valid = True
            quote = ""
            escaped = False
            for index, char in enumerate(expression):
                if quote:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == quote:
                        quote = ""
                    continue
                if char in {"'", '"'}:
                    quote = char
                    continue
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                if depth == 0 and index < len(expression) - 1:
                    valid = False
                    break
                if depth < 0:
                    valid = False
                    break
            if not valid:
                break
            expression = expression[1:-1].strip()
        return expression

    @staticmethod
    def _extract_condition_body(condition: str) -> str:
        raw = str(condition or "").strip()
        match = re.match(r"^\$\s*\[\s*\?\s*\((.*)\)\s*\]\s*$", raw, flags=re.DOTALL)
        return match.group(1).strip() if match else raw

    def _normalize_condition_path(self, path: str) -> str:
        normalized = self._strip_outer_parens(path)
        if normalized.startswith("@"):
            normalized = "$" + normalized[1:]
        return normalized

    def _extract_values_by_path(self, payload: object, path: str) -> list[object]:
        normalized_path = path.strip()
        if not normalized_path:
            return []

        if normalized_path.startswith("$.."):
            return self._extract_values_by_deep_path(payload, normalized_path[3:])

        segments = self._path_to_segments(normalized_path)
        if not segments:
            return []
        nodes: list[object] = [payload]
        for segment in segments[1:]:
            next_nodes: list[object] = []
            for node in nodes:
                next_nodes.extend(self._resolve_path_segment(node, segment))
            nodes = next_nodes
            if not nodes:
                break
        return nodes

    def _extract_values_by_deep_path(self, payload: object, deep_expression: str) -> list[object]:
        expression = deep_expression.strip(".")
        if not expression:
            return []
        first_segment, tail = self._split_first_path_segment(expression)
        first_segment = first_segment.strip()
        if not first_segment:
            return []

        base_name, brackets = self._split_path_segment(first_segment)
        base_name = base_name.strip()
        if not base_name:
            return []
        base_values = self._deep_find_values(payload, base_name)
        resolved_first_segment = self._apply_segment_brackets(base_values, brackets)
        if not tail:
            return resolved_first_segment
        results: list[object] = []
        for value in resolved_first_segment:
            results.extend(self._extract_values_by_path(value, "$." + tail))
        return results

    def _deep_find_values(self, node: object, key: str) -> list[object]:
        matches: list[object] = []
        if isinstance(node, dict):
            if key in node:
                matches.append(node[key])
            for value in node.values():
                matches.extend(self._deep_find_values(value, key))
            return matches
        if isinstance(node, list):
            for item in node:
                matches.extend(self._deep_find_values(item, key))
        return matches

    def _resolve_path_segment(self, node: object, segment: str) -> list[object]:
        base_name, brackets = self._split_path_segment(segment)
        current_nodes: list[object] = [node]

        if base_name and base_name != "*":
            next_nodes: list[object] = []
            for current in current_nodes:
                if isinstance(current, dict) and base_name in current:
                    next_nodes.append(current[base_name])
            current_nodes = next_nodes
        elif base_name == "*":
            wildcard_nodes: list[object] = []
            for current in current_nodes:
                if isinstance(current, dict):
                    wildcard_nodes.extend(current.values())
                elif isinstance(current, list):
                    wildcard_nodes.extend(current)
            current_nodes = wildcard_nodes

        return self._apply_segment_brackets(current_nodes, brackets)

    def _apply_segment_brackets(self, current_nodes: list[object], brackets: list[str]) -> list[object]:
        nodes = list(current_nodes)
        for bracket in brackets:
            content = bracket[1:-1].strip()
            next_nodes: list[object] = []
            if content == "*":
                for current in nodes:
                    if isinstance(current, list):
                        next_nodes.extend(current)
                    elif isinstance(current, dict):
                        next_nodes.extend(current.values())
            elif (content.startswith("'") and content.endswith("'")) or (
                content.startswith('"') and content.endswith('"')
            ):
                key_name = content[1:-1]
                for current in nodes:
                    if isinstance(current, dict) and key_name in current:
                        next_nodes.append(current[key_name])
            elif content.startswith("?(") and content.endswith(")"):
                filter_expression = content[2:-1].strip()
                for current in nodes:
                    candidates: list[object] = []
                    if isinstance(current, list):
                        candidates = list(current)
                    elif isinstance(current, dict):
                        candidates = list(current.values())
                    for candidate in candidates:
                        if self._evaluate_condition_expression(filter_expression, candidate):
                            next_nodes.append(candidate)
            else:
                try:
                    index_value = int(content)
                except ValueError:
                    # Unsupported index/filter syntax; abort this branch.
                    return []
                for current in nodes:
                    if isinstance(current, list):
                        if -len(current) <= index_value < len(current):
                            next_nodes.append(current[index_value])
            nodes = next_nodes
            if not nodes:
                break
        return nodes

    @staticmethod
    def _split_path_segment(segment: str) -> tuple[str, list[str]]:
        if "[" not in segment:
            return segment, []
        first_bracket = segment.find("[")
        base = segment[:first_bracket]
        bracket_part = segment[first_bracket:]
        brackets = re.findall(r"\[[^\]]*\]", bracket_part)
        return base, brackets

    @staticmethod
    def _split_first_path_segment(path_expression: str) -> tuple[str, str]:
        text = str(path_expression or "").strip()
        if not text:
            return "", ""
        bracket_depth = 0
        paren_depth = 0
        quote = ""
        escaped = False
        for index, char in enumerate(text):
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = ""
                continue
            if char in {"'", '"'}:
                quote = char
                continue
            if char == "[":
                bracket_depth += 1
                continue
            if char == "]":
                bracket_depth = max(0, bracket_depth - 1)
                continue
            if char == "(":
                paren_depth += 1
                continue
            if char == ")":
                paren_depth = max(0, paren_depth - 1)
                continue
            if char == "." and bracket_depth == 0 and paren_depth == 0:
                first = text[:index].strip()
                tail = text[index + 1 :].strip()
                return first, tail
        return text, ""

    def _select_field_node_for_field(self, field: dict[str, object]) -> None:
        for node_id, mapped_field in self._field_node_details.items():
            if mapped_field is field:
                self.fields_tree.selection_set(node_id)
                self.fields_tree.focus(node_id)
                self.fields_tree.see(node_id)
                self._active_field_node_id = node_id
                self._set_field_details(field)
                return

    def _normalize_true_path(self, path: str) -> str:
        candidate = self._normalize_path_expression(path.strip())
        if not candidate:
            return "$"

        previous = ""
        while candidate != previous:
            previous = candidate
            candidate = self._strip_wrapper_function(candidate, "length")
            candidate = self._strip_wrapper_function(candidate, "concat")
            candidate = candidate.replace(".length()", "")
            candidate = candidate.strip()

        if candidate.startswith("$.length("):
            candidate = self._strip_wrapper_function(candidate[2:], "length")
        if candidate.startswith("$.concat("):
            candidate = self._strip_wrapper_function(candidate[2:], "concat")

        if not candidate.startswith("$"):
            extracted = self._extract_first_jsonpath(candidate)
            if extracted:
                candidate = extracted

        extracted = self._extract_first_jsonpath(candidate)
        return extracted or candidate or "$"

    @staticmethod
    def _normalize_path_expression(path: str) -> str:
        text = path.strip()
        if not text:
            return text
        # Some payloads preserve JSON-escaped quotes (e.g. \"\") in Path values.
        # Normalize those escape sequences before syntax validation and path parsing.
        return text.replace('\\"', '"').replace("\\'", "'")

    def _strip_wrapper_function(self, expression: str, function_name: str) -> str:
        expr = expression.strip()
        direct = self._unwrap_named_call(expr, function_name)
        if direct is not None:
            if function_name == "concat":
                return self._select_concat_path(direct)
            return direct.strip()

        prefixed = self._unwrap_named_call(expr[2:], function_name) if expr.startswith("$.") else None
        if prefixed is not None:
            if function_name == "concat":
                return self._select_concat_path(prefixed)
            return prefixed.strip()
        return expr

    def _select_concat_path(self, args_text: str) -> str:
        args = self._split_top_level(args_text)
        best = ""
        for arg in args:
            normalized = self._normalize_true_path(arg)
            if "$" in normalized and len(normalized) > len(best):
                best = normalized
        return best or args_text.strip()

    def _extract_first_jsonpath(self, expression: str) -> str:
        expr = expression.strip()
        if not expr:
            return ""

        in_string = ""
        escaped = False
        paren_depth = 0
        bracket_depth = 0
        start = -1

        for index, char in enumerate(expr):
            if in_string:
                if escaped:
                    escaped = False
                    continue
                if char == "\\":
                    escaped = True
                    continue
                if char == in_string:
                    in_string = ""
                continue

            if char in {"'", '"'}:
                in_string = char
                continue

            if char == "[":
                bracket_depth += 1
            elif char == "]":
                if bracket_depth > 0:
                    bracket_depth -= 1
            elif char == "(":
                paren_depth += 1
            elif char == ")":
                if paren_depth > 0:
                    paren_depth -= 1

            if start < 0 and char == "$":
                start = index
                continue

            if start >= 0 and paren_depth == 0 and bracket_depth == 0 and char in {",", "+"}:
                break

        if start < 0:
            return ""
        end = len(expr)
        for index in range(start, len(expr)):
            char = expr[index]
            if char in {",", "+"}:
                end = index
                break
        return expr[start:end].strip()

    def _unwrap_named_call(self, expression: str, function_name: str) -> str | None:
        expr = expression.strip()
        prefix = f"{function_name}("
        if not expr.startswith(prefix) or not expr.endswith(")"):
            return None
        if not self._is_balanced_parenthesized(expr[len(function_name):]):
            return None
        return expr[len(prefix) : -1]

    @staticmethod
    def _is_balanced_parenthesized(text: str) -> bool:
        depth = 0
        in_string = ""
        escaped = False
        for char in text:
            if in_string:
                if escaped:
                    escaped = False
                    continue
                if char == "\\":
                    escaped = True
                    continue
                if char == in_string:
                    in_string = ""
                continue

            if char in {"'", '"'}:
                in_string = char
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth < 0:
                    return False
        return depth == 0 and not in_string

    def _split_top_level(self, text: str) -> list[str]:
        parts: list[str] = []
        current: list[str] = []
        paren_depth = 0
        bracket_depth = 0
        in_string = ""
        escaped = False

        for char in text:
            if in_string:
                current.append(char)
                if escaped:
                    escaped = False
                    continue
                if char == "\\":
                    escaped = True
                    continue
                if char == in_string:
                    in_string = ""
                continue

            if char in {"'", '"'}:
                in_string = char
                current.append(char)
                continue

            if char == "(":
                paren_depth += 1
            elif char == ")":
                if paren_depth > 0:
                    paren_depth -= 1
            elif char == "[":
                bracket_depth += 1
            elif char == "]":
                if bracket_depth > 0:
                    bracket_depth -= 1

            if char == "," and paren_depth == 0 and bracket_depth == 0:
                token = "".join(current).strip()
                if token:
                    parts.append(token)
                current = []
                continue

            current.append(char)

        tail = "".join(current).strip()
        if tail:
            parts.append(tail)
        return parts

    def _set_empty_fields_tree(self, message: str) -> None:
        self.fields_tree.delete(*self.fields_tree.get_children())
        self._field_node_details = {}
        self._clear_field_details()
        self.fields_tree.insert("", "end", text=message)

    @staticmethod
    def _path_to_segments(path: str) -> list[str]:
        cleaned = path.strip()
        if not cleaned:
            return ["(no path)"]

        segments = ["$"]
        if cleaned == "$":
            return segments

        remaining = cleaned[1:] if cleaned.startswith("$") else cleaned
        remaining = remaining.lstrip(".")
        if not remaining:
            return segments

        current: list[str] = []
        bracket_depth = 0
        paren_depth = 0
        quote_char = ""
        escaped = False
        for character in remaining:
            if quote_char:
                current.append(character)
                if escaped:
                    escaped = False
                    continue
                if character == "\\":
                    escaped = True
                    continue
                if character == quote_char:
                    quote_char = ""
                continue

            if character in {"'", '"'}:
                quote_char = character
                current.append(character)
                continue
            if character == "[":
                bracket_depth += 1
                current.append(character)
                continue
            if character == "]":
                if bracket_depth > 0:
                    bracket_depth -= 1
                current.append(character)
                continue
            if character == "(":
                paren_depth += 1
                current.append(character)
                continue
            if character == ")":
                if paren_depth > 0:
                    paren_depth -= 1
                current.append(character)
                continue
            if character == "." and bracket_depth == 0 and paren_depth == 0:
                token = "".join(current).strip()
                if token:
                    segments.append(token)
                current = []
                continue
            current.append(character)

        tail = "".join(current).strip()
        if tail:
            segments.append(tail)
        return segments

    @staticmethod
    def _is_macos() -> bool:
        return platform.system() == "Darwin"


def main() -> None:
    root = tk.Tk()
    AToolApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
