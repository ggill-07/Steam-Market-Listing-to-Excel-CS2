from __future__ import annotations

import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
import steam_market_to_excel as sme
import third_party_market_support as tpms

from smte_desktop_support import (
    AUTOCOMPLETE_MIN_CHARS,
    DEFAULT_DESKTOP_LIMIT,
    MarketAutocompleteCache,
    MarketSuggestion,
    DesktopQuery,
    DesktopSettings,
    QueryExecutionResult,
    QueryValidationResult,
    WEAR_OPTIONS,
    apply_manual_price_override,
    build_query_label,
    describe_runtime_provider_mode,
    create_query_from_form,
    execute_desktop_query,
    load_desktop_settings,
    load_desktop_query_queue,
    save_desktop_settings,
    save_desktop_query_queue,
    strip_wear_suffix,
    query_matches_suggestion,
    validate_query_against_market,
)

SORT_OPTIONS = ["price", "float", "paint_seed", "sticker_count", "page"]
APP_BACKGROUND = "#f3efe7"
CARD_BACKGROUND = "#fffaf3"
ACCENT_COLOR = "#215f4e"
ACCENT_SOFT = "#dcece5"
TEXT_PRIMARY = "#223127"
TEXT_MUTED = "#5c6a62"
TABLE_ALT_ROW = "#f7f1e7"
RESULT_TABS_PER_ROW = 20
RESULT_TAB_BAR_MAX_HEIGHT = 44
RESULT_TAB_MAX_LABEL_CHARS = 12
RESULT_TAB_MIN_WIDTH_CHARS = 3
RESULT_TAB_STRIP_BACKGROUND = "#d8cfbf"
RESULT_TAB_ACTIVE_BACKGROUND = CARD_BACKGROUND
RESULT_TAB_ACTIVE_FOREGROUND = TEXT_PRIMARY
RESULT_TAB_INACTIVE_BACKGROUND = "#e8dfcf"
RESULT_TAB_INACTIVE_FOREGROUND = TEXT_MUTED
RESULT_TAB_BORDER_COLOR = "#b9ae9a"


def get_resource_path(*parts: str) -> Path:
    """Resolve asset paths for both source runs and frozen desktop builds."""

    if getattr(sys, "frozen", False):
        base_path = Path(getattr(sys, "_MEIPASS", Path.cwd()))
    else:
        base_path = Path(__file__).resolve().parents[1]
    return base_path.joinpath(*parts)


class SMTEDesktopApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SMTE Desktop")
        self.root.geometry("1580x980")
        self.root.minsize(1320, 840)
        self.root.configure(background=APP_BACKGROUND)
        self.icon_image: Optional[tk.PhotoImage] = None
        self._apply_window_icon()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.settings = load_desktop_settings()
        self.autocomplete_cache = MarketAutocompleteCache()
        self.query_items: List[DesktopQuery] = load_desktop_query_queue()
        self.query_validation_statuses: Dict[int, str] = {}
        self.left_query_row_mappings: Dict[str, int] = {}
        self.right_query_row_mappings: Dict[str, int] = {}
        self.current_suggestions: List[MarketSuggestion] = []
        self.worker_thread: Optional[threading.Thread] = None
        self.worker_events: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self.autocomplete_request_id = 0
        self.active_vertical_scroll_handler: Optional[Callable[[int], None]] = None
        self.active_horizontal_scroll_handler: Optional[Callable[[int], None]] = None
        self.result_tabs: List[Dict[str, Any]] = []
        self.active_result_tab_index: Optional[int] = None

        self._build_variables()
        self._build_ui()
        self._bind_events()
        self._poll_worker_events()
        self._refresh_query_tree()
        if self.query_items:
            restored_message = (
                f"Restored {len(self.query_items)} queued search"
                f"{'es' if len(self.query_items) != 1 else ''} from the last session."
            )
            self.status_var.set(restored_message)
            self._append_log(restored_message)

    def _apply_window_icon(self) -> None:
        """Prefer the custom SMTE icon instead of the generic Python one."""

        icon_png_path = get_resource_path("assets", "smte_desktop_icon.png")
        icon_ico_path = get_resource_path("assets", "smte_desktop_icon.ico")

        try:
            if icon_png_path.exists():
                self.icon_image = tk.PhotoImage(file=str(icon_png_path))
                self.root.iconphoto(True, self.icon_image)
        except tk.TclError:
            self.icon_image = None

        try:
            if icon_ico_path.exists():
                self.root.iconbitmap(default=str(icon_ico_path))
        except tk.TclError:
            pass

    def _build_variables(self) -> None:
        self.item_name_var = tk.StringVar()
        self.max_float_var = tk.StringVar()
        self.max_price_var = tk.StringVar()
        self.paint_seed_var = tk.StringVar()
        self.min_sticker_count_var = tk.StringVar()
        self.max_sticker_count_var = tk.StringVar()
        self.limit_var = tk.StringVar(value=str(DEFAULT_DESKTOP_LIMIT))
        self.sort_by_var = tk.StringVar(value="price")
        self.descending_var = tk.BooleanVar(value=False)
        self.has_stickers_var = tk.BooleanVar(value=False)
        self.no_stickers_var = tk.BooleanVar(value=False)
        self.no_wear_item_var = tk.BooleanVar(value=False)

        self.settings_page_delay_var = tk.StringVar(value=str(self.settings.steam_page_delay))
        self.settings_retries_var = tk.StringVar(value=str(self.settings.steam_max_retries))
        self.settings_pause_var = tk.StringVar(value=str(self.settings.pause_between_queries))
        self.settings_continue_var = tk.BooleanVar(value=self.settings.continue_on_error)
        self.settings_combine_case_exports_var = tk.BooleanVar(value=self.settings.combine_case_exports)
        self.settings_enable_third_party_support_var = tk.BooleanVar(value=self.settings.enable_third_party_support)
        self.provider_label_to_key = tpms.get_provider_choice_mapping()
        self.provider_key_to_label = {
            provider_key: provider_label
            for provider_label, provider_key in self.provider_label_to_key.items()
        }
        self.settings_third_party_provider_var = tk.StringVar(
            value=self.provider_key_to_label.get(
                self.settings.third_party_provider,
                tpms.get_provider_label(tpms.PROVIDER_SKINPORT),
            )
        )
        self.provider_summary_var = tk.StringVar()
        self.editor_summary_var = tk.StringVar(value="Start by typing an item name, then choose wear and any filters you care about.")
        self.queue_summary_var = tk.StringVar(value="No searches queued yet.")
        self.results_summary_var = tk.StringVar(value="Run a search to open result tabs here.")

        self.wear_vars = {
            wear_name: tk.BooleanVar(value=False)
            for wear_name in WEAR_OPTIONS
        }

        traced_variables: List[tk.Variable] = [
            self.item_name_var,
            self.max_float_var,
            self.max_price_var,
            self.paint_seed_var,
            self.min_sticker_count_var,
            self.max_sticker_count_var,
            self.limit_var,
            self.sort_by_var,
            self.descending_var,
            self.has_stickers_var,
            self.no_stickers_var,
            self.no_wear_item_var,
            self.settings_enable_third_party_support_var,
            self.settings_third_party_provider_var,
        ]
        traced_variables.extend(self.wear_vars.values())
        for variable in traced_variables:
            variable.trace_add("write", self._on_editor_state_changed)

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self._configure_styles(style)

        shell = ttk.Frame(self.root, style="App.TFrame")
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        self.main_canvas = tk.Canvas(
            shell,
            background=APP_BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
        )
        self.main_canvas.grid(row=0, column=0, sticky="nsew")

        canvas_scrollbar = ttk.Scrollbar(shell, orient="vertical", command=self.main_canvas.yview)
        canvas_scrollbar.grid(row=0, column=1, sticky="ns")
        canvas_x_scrollbar = ttk.Scrollbar(shell, orient="horizontal", command=self.main_canvas.xview)
        canvas_x_scrollbar.grid(row=1, column=0, sticky="ew")
        self.main_canvas.configure(yscrollcommand=canvas_scrollbar.set)
        self.main_canvas.configure(xscrollcommand=canvas_x_scrollbar.set)

        outer = ttk.Frame(self.main_canvas, padding=16, style="App.TFrame")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=0)
        outer.rowconfigure(3, weight=6)
        self.canvas_window = self.main_canvas.create_window((0, 0), window=outer, anchor="nw")
        outer.bind("<Configure>", self._on_outer_configure)
        self.main_canvas.bind("<Configure>", self._on_canvas_configure)
        self.root.bind_all("<MouseWheel>", self._dispatch_mousewheel, add="+")
        self.root.bind_all("<Shift-MouseWheel>", self._dispatch_shift_mousewheel, add="+")

        header_card = ttk.Frame(outer, style="Card.TFrame", padding=18)
        header_card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header_card.columnconfigure(0, weight=1)
        header_card.columnconfigure(1, weight=0)

        title_label = ttk.Label(
            header_card,
            text="Steam Market Search Desktop",
            style="HeroTitle.TLabel",
        )
        title_label.grid(row=0, column=0, sticky="w")

        hero_badge = ttk.Label(
            header_card,
            text="Safer Desktop Batch Search",
            style="Badge.TLabel",
        )
        hero_badge.grid(row=0, column=1, sticky="e")

        subtitle_label = ttk.Label(
            header_card,
            text=(
                "Type part of a skin name, pick the right wear, add the filters you care about, "
                "then queue searches and review each result set in its own tab."
            ),
            style="Subhero.TLabel",
            wraplength=980,
            justify="left",
        )
        subtitle_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        builder_frame = ttk.LabelFrame(outer, text=" Query Builder ", padding=8, style="Card.TLabelframe")
        builder_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        builder_frame.columnconfigure(0, weight=4)
        builder_frame.columnconfigure(1, weight=2)
        builder_frame.columnconfigure(2, weight=2)
        builder_frame.columnconfigure(3, weight=2)
        builder_frame.columnconfigure(4, weight=2)
        builder_frame.rowconfigure(2, weight=0)
        builder_frame.rowconfigure(4, weight=1)

        ttk.Label(builder_frame, text="Item Name", style="SectionLabel.TLabel").grid(row=0, column=0, sticky="w")
        self.item_entry = tk.Text(
            builder_frame,
            height=2,
            wrap="word",
            font=("Segoe UI", 10),
            background="#ffffff",
            foreground=TEXT_PRIMARY,
            relief="solid",
            borderwidth=1,
        )
        self.item_entry.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        self.item_entry.insert("1.0", self.item_name_var.get())

        self.refresh_suggestions_button = ttk.Button(
            builder_frame,
            text="Refresh Suggestions",
            style="Secondary.TButton",
            command=lambda: self._trigger_autocomplete(force_refresh=True),
        )
        self.refresh_suggestions_button.grid(row=1, column=1, sticky="ew", padx=(0, 8))

        ttk.Label(builder_frame, text="Sort By", style="SectionLabel.TLabel").grid(row=0, column=2, sticky="w")
        self.sort_by_combo = ttk.Combobox(
            builder_frame,
            textvariable=self.sort_by_var,
            values=SORT_OPTIONS,
            state="readonly",
        )
        self.sort_by_combo.grid(row=1, column=2, sticky="ew", padx=(0, 8))

        self.descending_check = ttk.Checkbutton(
            builder_frame,
            text="Descending",
            variable=self.descending_var,
        )
        self.descending_check.grid(row=1, column=3, sticky="w", padx=(0, 6))

        ttk.Label(builder_frame, text="Show Limit", style="SectionLabel.TLabel").grid(row=0, column=4, sticky="w")
        self.limit_entry = ttk.Entry(builder_frame, textvariable=self.limit_var)
        self.limit_entry.grid(row=1, column=4, sticky="ew")

        suggestion_frame = ttk.Frame(builder_frame, style="InnerCard.TFrame", padding=3)
        suggestion_frame.grid(row=2, column=0, columnspan=3, sticky="nsew", padx=(0, 8), pady=(4, 0))
        suggestion_frame.columnconfigure(0, weight=1)
        suggestion_frame.rowconfigure(2, weight=1)

        ttk.Label(
            suggestion_frame,
            text="Autocomplete Suggestions",
            style="SectionLabel.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            suggestion_frame,
            text=f"Suggestions start after {AUTOCOMPLETE_MIN_CHARS} characters and reuse a local cache for speed. For cases or stickers, you can paste one item per line and add them all at once. For skins, you can also paste full exact market names with the wear already included, one per line.",
            style="InnerHelper.TLabel",
            wraplength=500,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(1, 2))

        self.suggestion_tree = ttk.Treeview(
            suggestion_frame,
            columns=("base_name", "wears"),
            show="headings",
            height=4,
            selectmode="browse",
        )
        self.suggestion_tree.heading("base_name", text="Item Name")
        self.suggestion_tree.heading("wears", text="Wears / Type")
        self.suggestion_tree.column("base_name", width=280, anchor="w", stretch=True)
        self.suggestion_tree.column("wears", width=145, anchor="w", stretch=True)
        self.suggestion_tree.grid(row=2, column=0, sticky="nsew")
        suggestion_scrollbar = ttk.Scrollbar(
            suggestion_frame,
            orient="vertical",
            command=self.suggestion_tree.yview,
        )
        suggestion_scrollbar.grid(row=2, column=1, sticky="ns")
        suggestion_x_scrollbar = ttk.Scrollbar(
            suggestion_frame,
            orient="horizontal",
            command=self.suggestion_tree.xview,
        )
        suggestion_x_scrollbar.grid(row=3, column=0, sticky="ew", pady=(2, 0))
        self.suggestion_tree.configure(
            yscrollcommand=suggestion_scrollbar.set,
            xscrollcommand=suggestion_x_scrollbar.set,
        )

        filters_frame = ttk.LabelFrame(builder_frame, text=" Search Filters ", padding=6, style="Card.TLabelframe")
        filters_frame.grid(row=2, column=3, columnspan=2, sticky="new", pady=(4, 0))
        for column_index in range(4):
            filters_frame.columnconfigure(column_index, weight=1)

        ttk.Label(filters_frame, text="Max Float", style="SectionLabel.TLabel").grid(row=0, column=0, sticky="w")
        self.max_float_entry = ttk.Entry(filters_frame, textvariable=self.max_float_var)
        self.max_float_entry.grid(row=1, column=0, sticky="ew", padx=(0, 6))

        ttk.Label(filters_frame, text="Max Price", style="SectionLabel.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Entry(filters_frame, textvariable=self.max_price_var).grid(row=1, column=1, sticky="ew", padx=(0, 6))

        ttk.Label(filters_frame, text="Paint Seed", style="SectionLabel.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Entry(filters_frame, textvariable=self.paint_seed_var).grid(row=1, column=2, sticky="ew", padx=(0, 6))

        sticker_mode_frame = ttk.Frame(filters_frame, style="InnerCard.TFrame", padding=4)
        sticker_mode_frame.grid(row=1, column=3, sticky="w")
        self.sticker_mode_frame = sticker_mode_frame
        ttk.Label(sticker_mode_frame, text="Sticker Preference", style="SectionLabel.TLabel").pack(anchor="w", pady=(0, 4))
        self.has_stickers_check = ttk.Checkbutton(
            sticker_mode_frame,
            text="Has stickers",
            variable=self.has_stickers_var,
            command=self._toggle_sticker_mode,
        )
        self.has_stickers_check.pack(anchor="w")
        self.no_stickers_check = ttk.Checkbutton(
            sticker_mode_frame,
            text="No stickers",
            variable=self.no_stickers_var,
            command=self._toggle_sticker_mode,
        )
        self.no_stickers_check.pack(anchor="w")

        wear_frame = ttk.LabelFrame(filters_frame, text=" Wear Selection ", padding=4, style="Card.TLabelframe")
        wear_frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        wear_frame.columnconfigure(0, weight=1)
        wear_frame.columnconfigure(1, weight=1)
        ttk.Label(
            wear_frame,
            text="Pick one or more wears, or mark the item as no-wear for cases, stickers, and other non-float items. In no-wear mode, you can also paste multiple case or sticker names, one per line, and add them all at once. If you paste multiple skin lines, include the exact wear in each line, like (Factory New).",
            style="Body.TLabel",
            wraplength=360,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 2))
        self.no_wear_check = ttk.Checkbutton(
            wear_frame,
            text="No wear / no float item",
            variable=self.no_wear_item_var,
            command=self._on_no_wear_toggled,
        )
        self.no_wear_check.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.select_all_wears_button = ttk.Button(
            wear_frame,
            text="Select All Wears",
            style="Secondary.TButton",
            command=lambda: self._set_all_wears(True),
        )
        self.select_all_wears_button.grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(0, 4))
        self.clear_wears_button = ttk.Button(
            wear_frame,
            text="Clear Wears",
            style="Secondary.TButton",
            command=lambda: self._set_all_wears(False),
        )
        self.clear_wears_button.grid(row=2, column=1, sticky="w", pady=(0, 4))
        self.wear_checkbuttons: List[ttk.Checkbutton] = []
        for index, wear_name in enumerate(WEAR_OPTIONS):
            wear_checkbutton = ttk.Checkbutton(
                wear_frame,
                text=wear_name,
                variable=self.wear_vars[wear_name],
            )
            wear_checkbutton.grid(row=3 + (index // 2), column=index % 2, sticky="w", padx=(0, 10), pady=1)
            self.wear_checkbuttons.append(wear_checkbutton)

        actions_frame = ttk.Frame(builder_frame, style="App.TFrame")
        actions_frame.grid(row=3, column=0, columnspan=5, sticky="ew", pady=(6, 0))
        for column_index in range(8):
            actions_frame.columnconfigure(column_index, weight=1)

        ttk.Button(actions_frame, text="Add Query", style="Primary.TButton", command=self._add_queries_from_editor).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(actions_frame, text="Populate From Selected", style="Secondary.TButton", command=self._populate_editor_from_selected_query).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(actions_frame, text="Remove Selected", style="Secondary.TButton", command=self._remove_selected_queries).grid(row=0, column=2, sticky="ew", padx=(0, 8))
        ttk.Button(actions_frame, text="Clear Queue", style="Secondary.TButton", command=self._clear_query_queue).grid(row=0, column=3, sticky="ew", padx=(0, 8))
        ttk.Button(actions_frame, text="Validate Queue", style="Secondary.TButton", command=self._validate_queue_from_ui).grid(row=0, column=4, sticky="ew", padx=(0, 8))
        ttk.Button(actions_frame, text="Run Selected", style="Primary.TButton", command=lambda: self._start_run(selected_only=True)).grid(row=0, column=5, sticky="ew", padx=(0, 8))
        ttk.Button(actions_frame, text="Run All", style="Primary.TButton", command=lambda: self._start_run(selected_only=False)).grid(row=0, column=6, sticky="ew", padx=(0, 8))
        ttk.Button(actions_frame, text="Save App State", style="Secondary.TButton", command=self._save_app_state_from_ui).grid(row=0, column=7, sticky="ew")

        queue_frame = ttk.LabelFrame(builder_frame, text=" Queued Searches ", padding=4, style="Card.TLabelframe")
        queue_frame.grid(row=4, column=0, columnspan=5, sticky="nsew", pady=(4, 0))
        queue_frame.columnconfigure(0, weight=1)
        queue_frame.columnconfigure(1, weight=0)
        queue_frame.rowconfigure(0, weight=1)

        settings_frame = ttk.Frame(queue_frame, style="InnerCard.TFrame", padding=4)
        settings_frame.grid(row=0, column=1, sticky="ne", padx=(12, 0))
        for column_index in range(4):
            settings_frame.columnconfigure(column_index, weight=1)

        ttk.Label(settings_frame, text="Page Delay", style="SectionLabel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(settings_frame, textvariable=self.settings_page_delay_var).grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ttk.Label(settings_frame, text="Retries", style="SectionLabel.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Entry(settings_frame, textvariable=self.settings_retries_var).grid(row=1, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(settings_frame, text="Pause Between Queries", style="SectionLabel.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Entry(settings_frame, textvariable=self.settings_pause_var).grid(row=1, column=2, sticky="ew", padx=(0, 8))
        ttk.Checkbutton(
            settings_frame,
            text="Continue on error",
            variable=self.settings_continue_var,
        ).grid(row=1, column=3, sticky="w")
        ttk.Checkbutton(
            settings_frame,
            text="Save all case snapshots into one workbook",
            variable=self.settings_combine_case_exports_var,
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Checkbutton(
            settings_frame,
            text="Prepare third-party provider support",
            variable=self.settings_enable_third_party_support_var,
            command=self._refresh_provider_summary,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(settings_frame, text="Provider", style="SectionLabel.TLabel").grid(row=4, column=0, sticky="w", pady=(6, 0))
        self.third_party_provider_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.settings_third_party_provider_var,
            values=tpms.get_provider_choice_labels(),
            state="readonly",
        )
        self.third_party_provider_combo.grid(row=5, column=0, columnspan=2, sticky="ew", padx=(0, 8))
        ttk.Label(
            settings_frame,
            textvariable=self.provider_summary_var,
            style="InnerHelper.TLabel",
            wraplength=300,
            justify="left",
        ).grid(row=4, column=2, columnspan=2, rowspan=2, sticky="w", padx=(8, 0), pady=(6, 0))

        queue_tables_frame = ttk.Frame(queue_frame, style="Card.TFrame")
        queue_tables_frame.grid(row=0, column=0, sticky="nsew")
        queue_tables_frame.columnconfigure(0, weight=1)
        queue_tables_frame.columnconfigure(1, weight=1)
        queue_tables_frame.rowconfigure(0, weight=1)

        left_queue_frame = ttk.Frame(queue_tables_frame, style="Card.TFrame")
        left_queue_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left_queue_frame.columnconfigure(0, weight=1)
        left_queue_frame.rowconfigure(0, weight=1)

        right_queue_frame = ttk.Frame(queue_tables_frame, style="Card.TFrame")
        right_queue_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right_queue_frame.columnconfigure(0, weight=1)
        right_queue_frame.rowconfigure(0, weight=1)

        self.query_tree_left = ttk.Treeview(
            left_queue_frame,
            columns=("item", "filters", "status"),
            show="headings",
            selectmode="extended",
            height=12,
        )
        self.query_tree_right = ttk.Treeview(
            right_queue_frame,
            columns=("item", "filters", "status"),
            show="headings",
            selectmode="extended",
            height=12,
        )

        for tree in (self.query_tree_left, self.query_tree_right):
            for column_name, heading_text, width in (
                ("item", "Queued Item", 255),
                ("filters", "Filters Used", 205),
                ("status", "Valid", 85),
            ):
                tree.heading(column_name, text=heading_text)
                tree.column(column_name, width=width, anchor="w", stretch=True)

        self.query_tree_left.grid(row=0, column=0, sticky="nsew")
        self.query_tree_right.grid(row=0, column=0, sticky="nsew")

        left_query_x_scrollbar = ttk.Scrollbar(left_queue_frame, orient="horizontal", command=self.query_tree_left.xview)
        left_query_x_scrollbar.grid(row=1, column=0, sticky="ew")
        right_query_x_scrollbar = ttk.Scrollbar(right_queue_frame, orient="horizontal", command=self.query_tree_right.xview)
        right_query_x_scrollbar.grid(row=1, column=0, sticky="ew")

        self.query_scrollbar = ttk.Scrollbar(queue_frame, orient="vertical", command=self._queue_trees_yview)
        self.query_scrollbar.grid(row=0, column=2, sticky="ns")
        self.query_tree_left.configure(
            yscrollcommand=self._on_queue_tree_yscroll,
            xscrollcommand=left_query_x_scrollbar.set,
        )
        self.query_tree_right.configure(
            yscrollcommand=self._on_queue_tree_yscroll,
            xscrollcommand=right_query_x_scrollbar.set,
        )

        results_frame = ttk.LabelFrame(outer, text=" Results and Activity ", padding=12, style="Card.TLabelframe")
        results_frame.grid(row=3, column=0, sticky="nsew")
        results_frame.columnconfigure(0, weight=0)
        results_frame.columnconfigure(1, weight=1)
        results_frame.rowconfigure(2, weight=1)

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(results_frame, textvariable=self.status_var, style="CardStatus.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(
            results_frame,
            text="Clear Results",
            style="Secondary.TButton",
            command=self._clear_results_workspace,
        ).grid(row=0, column=1, sticky="e")
        ttk.Label(results_frame, textvariable=self.results_summary_var, style="CardHelper.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

        log_frame = ttk.Frame(results_frame, style="InnerCard.TFrame", padding=10)
        log_frame.grid(row=2, column=0, sticky="nsw", padx=(0, 12))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)
        ttk.Label(log_frame, text="Activity Log", style="SectionLabel.TLabel").grid(row=0, column=0, sticky="w")
        log_text_frame = ttk.Frame(log_frame, style="InnerCard.TFrame", padding=0)
        log_text_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        log_text_frame.columnconfigure(0, weight=1)
        log_text_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_text_frame,
            wrap="none",
            height=24,
            bg="#17231d",
            fg="#ecf5ef",
            insertbackground="#ecf5ef",
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=10,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        log_y_scroll = ttk.Scrollbar(log_text_frame, orient="vertical", command=self.log_text.yview)
        log_y_scroll.grid(row=0, column=1, sticky="ns")
        log_x_scroll = ttk.Scrollbar(log_text_frame, orient="horizontal", command=self.log_text.xview)
        log_x_scroll.grid(row=1, column=0, sticky="ew")
        self.log_text.configure(yscrollcommand=log_y_scroll.set, xscrollcommand=log_x_scroll.set, state="disabled")

        notebook_frame = ttk.Frame(results_frame, style="Card.TFrame")
        notebook_frame.grid(row=2, column=1, sticky="nsew")
        notebook_frame.columnconfigure(0, weight=1)
        notebook_frame.rowconfigure(1, weight=1)

        self.results_tab_shell = ttk.Frame(notebook_frame, style="Card.TFrame")
        self.results_tab_shell.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.results_tab_shell.columnconfigure(0, weight=1)
        self.results_tab_shell.rowconfigure(0, weight=1)

        self.results_tab_canvas = tk.Canvas(
            self.results_tab_shell,
            background=CARD_BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
            height=RESULT_TAB_BAR_MAX_HEIGHT,
        )
        self.results_tab_canvas.grid(row=0, column=0, sticky="ew")

        self.results_tab_scrollbar = ttk.Scrollbar(
            self.results_tab_shell,
            orient="vertical",
            command=self.results_tab_canvas.yview,
        )
        self.results_tab_scrollbar.grid(row=0, column=1, sticky="ns")
        self.results_tab_canvas.configure(yscrollcommand=self.results_tab_scrollbar.set)

        self.results_tab_bar = tk.Frame(
            self.results_tab_canvas,
            background=RESULT_TAB_STRIP_BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
        )
        self.results_tab_canvas_window = self.results_tab_canvas.create_window(
            (0, 0),
            window=self.results_tab_bar,
            anchor="nw",
        )
        self.results_tab_bar.bind(
            "<Configure>",
            lambda _event: self.results_tab_canvas.configure(scrollregion=self.results_tab_canvas.bbox("all")),
        )
        self.results_tab_canvas.bind(
            "<Configure>",
            lambda event: self.results_tab_canvas.itemconfigure(self.results_tab_canvas_window, width=event.width),
        )

        self.results_content_frame = ttk.Frame(notebook_frame, style="Card.TFrame")
        self.results_content_frame.grid(row=1, column=0, sticky="nsew")
        self.results_content_frame.columnconfigure(0, weight=1)
        self.results_content_frame.rowconfigure(0, weight=1)

        self.results_placeholder = ttk.Frame(self.results_content_frame, style="InnerCard.TFrame", padding=18)
        self.results_placeholder.grid(row=0, column=0, sticky="nsew")
        self.results_placeholder.columnconfigure(0, weight=1)
        ttk.Label(
            self.results_placeholder,
            text="Results Workspace",
            style="SectionLabel.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            self.results_placeholder,
            text=(
                "Run a queued search to open a results tab here. This area will show the query summary "
                "and the structured results table."
            ),
            style="Body.TLabel",
            wraplength=720,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._refresh_no_wear_mode()
        self._refresh_provider_summary()
        self._refresh_editor_summary()

    def _configure_styles(self, style: ttk.Style) -> None:
        style.configure("App.TFrame", background=APP_BACKGROUND)
        style.configure("Card.TFrame", background=CARD_BACKGROUND)
        style.configure("InnerCard.TFrame", background=ACCENT_SOFT)
        style.configure("Card.TLabelframe", background=CARD_BACKGROUND, borderwidth=0)
        style.configure("Card.TLabelframe.Label", background=CARD_BACKGROUND, foreground=TEXT_PRIMARY, font=("Segoe UI", 11, "bold"))
        style.configure("TLabel", background=APP_BACKGROUND, foreground=TEXT_PRIMARY, font=("Segoe UI", 10))
        style.configure("HeroTitle.TLabel", background=CARD_BACKGROUND, foreground=TEXT_PRIMARY, font=("Segoe UI Semibold", 22, "bold"))
        style.configure("Subhero.TLabel", background=CARD_BACKGROUND, foreground=TEXT_MUTED, font=("Segoe UI", 11))
        style.configure("Badge.TLabel", background=ACCENT_SOFT, foreground=ACCENT_COLOR, font=("Segoe UI Semibold", 10, "bold"), padding=(10, 5))
        style.configure("SectionLabel.TLabel", background=ACCENT_SOFT, foreground=TEXT_PRIMARY, font=("Segoe UI Semibold", 10, "bold"))
        style.configure("Body.TLabel", background=ACCENT_SOFT, foreground=TEXT_PRIMARY, font=("Segoe UI", 10))
        style.configure("CardBody.TLabel", background=CARD_BACKGROUND, foreground=TEXT_PRIMARY, font=("Segoe UI", 10))
        style.configure("Helper.TLabel", background=APP_BACKGROUND, foreground=TEXT_MUTED, font=("Segoe UI", 9))
        style.configure("InnerHelper.TLabel", background=ACCENT_SOFT, foreground=TEXT_MUTED, font=("Segoe UI", 9))
        style.configure("CardHelper.TLabel", background=CARD_BACKGROUND, foreground=TEXT_MUTED, font=("Segoe UI", 9))
        style.configure("Status.TLabel", background=APP_BACKGROUND, foreground=ACCENT_COLOR, font=("Segoe UI Semibold", 11, "bold"))
        style.configure("CardStatus.TLabel", background=CARD_BACKGROUND, foreground=ACCENT_COLOR, font=("Segoe UI Semibold", 11, "bold"))
        style.configure("TButton", font=("Segoe UI Semibold", 10), padding=(10, 8))
        style.configure("Primary.TButton", foreground="#ffffff", background=ACCENT_COLOR)
        style.map("Primary.TButton", background=[("active", "#18473b"), ("pressed", "#143b31")], foreground=[("disabled", "#cde0d8")])
        style.configure("Secondary.TButton", foreground=TEXT_PRIMARY, background="#efe7d7")
        style.map("Secondary.TButton", background=[("active", "#e3d8c2"), ("pressed", "#d7c9ae")])
        style.configure("TEntry", fieldbackground="#fffdf8", padding=6)
        style.configure("TCombobox", fieldbackground="#fffdf8", padding=4)
        style.configure("TCheckbutton", background=ACCENT_SOFT, foreground=TEXT_PRIMARY, font=("Segoe UI", 10))
        style.configure("Treeview", rowheight=30, font=("Segoe UI", 10), fieldbackground="#fffdf8", background="#fffdf8")
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 10, "bold"))
        style.map("Treeview", background=[("selected", ACCENT_COLOR)], foreground=[("selected", "#ffffff")])

    def _bind_events(self) -> None:
        self.item_entry.bind("<KeyRelease>", self._on_item_name_key_release)
        self._bind_scrollable_widget(
            self.item_entry,
            lambda steps: self.item_entry.yview_scroll(steps, "units"),
            lambda steps: self.item_entry.xview_scroll(steps, "units"),
        )
        self.suggestion_tree.bind("<<TreeviewSelect>>", self._on_suggestion_selected)
        self.suggestion_tree.bind("<Double-Button-1>", self._on_suggestion_selected)
        self._bind_scrollable_widget(
            self.suggestion_tree,
            lambda steps: self.suggestion_tree.yview_scroll(steps, "units"),
            lambda steps: self.suggestion_tree.xview_scroll(steps, "units"),
        )
        self._bind_scrollable_widget(
            self.query_tree_left,
            self._scroll_queue_trees,
            lambda steps: self.query_tree_left.xview_scroll(steps, "units"),
        )
        self._bind_scrollable_widget(
            self.query_tree_right,
            self._scroll_queue_trees,
            lambda steps: self.query_tree_right.xview_scroll(steps, "units"),
        )
        self._bind_scrollable_widget(
            self.log_text,
            lambda steps: self.log_text.yview_scroll(steps, "units"),
            lambda steps: self.log_text.xview_scroll(steps, "units"),
        )

    def _on_outer_configure(self, _event: tk.Event[Any]) -> None:
        self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event[Any]) -> None:
        self.main_canvas.itemconfigure(self.canvas_window, width=max(event.width, 1500))

    def _bind_scrollable_widget(
        self,
        widget: tk.Widget,
        vertical_handler: Callable[[int], None],
        horizontal_handler: Callable[[int], None],
    ) -> None:
        def on_enter(_event: tk.Event[Any]) -> None:
            self.active_vertical_scroll_handler = vertical_handler
            self.active_horizontal_scroll_handler = horizontal_handler

        def on_leave(_event: tk.Event[Any]) -> None:
            if self.active_vertical_scroll_handler is vertical_handler:
                self.active_vertical_scroll_handler = None
            if self.active_horizontal_scroll_handler is horizontal_handler:
                self.active_horizontal_scroll_handler = None

        widget.bind("<Enter>", on_enter, add="+")
        widget.bind("<Leave>", on_leave, add="+")

    def _dispatch_mousewheel(self, event: tk.Event[Any]) -> str:
        if not hasattr(event, "delta") or not event.delta:
            return "break"
        steps = int(-event.delta / 120)
        if steps == 0:
            return "break"
        if self.active_vertical_scroll_handler is not None:
            self.active_vertical_scroll_handler(steps)
            return "break"
        self.main_canvas.yview_scroll(steps, "units")
        return "break"

    def _dispatch_shift_mousewheel(self, event: tk.Event[Any]) -> str:
        if not hasattr(event, "delta") or not event.delta:
            return "break"
        steps = int(-event.delta / 120)
        if steps == 0:
            return "break"
        if self.active_horizontal_scroll_handler is not None:
            self.active_horizontal_scroll_handler(steps)
            return "break"
        self.main_canvas.xview_scroll(steps, "units")
        return "break"

    def _queue_trees_yview(self, *args: str) -> None:
        self.query_tree_left.yview(*args)
        self.query_tree_right.yview(*args)

    def _on_queue_tree_yscroll(self, first: str, last: str) -> None:
        self.query_scrollbar.set(first, last)

    def _scroll_queue_trees(self, steps: int) -> None:
        self.query_tree_left.yview_scroll(steps, "units")
        self.query_tree_right.yview_scroll(steps, "units")

    def _toggle_sticker_mode(self) -> None:
        if self.has_stickers_var.get() and self.no_stickers_var.get():
            self.no_stickers_var.set(False)

    def _get_item_name_text(self) -> str:
        return self.item_entry.get("1.0", "end-1c")

    def _set_item_name_text(self, value: str) -> None:
        normalized_value = value.rstrip("\n")
        self.item_entry.delete("1.0", "end")
        self.item_entry.insert("1.0", normalized_value)
        self.item_name_var.set(normalized_value)

    def _get_bulk_item_names(self) -> List[str]:
        seen_names = set()
        item_names: List[str] = []
        for raw_line in self._get_item_name_text().splitlines():
            normalized_name = raw_line.strip()
            if not normalized_name:
                continue
            folded_name = normalized_name.casefold()
            if folded_name in seen_names:
                continue
            seen_names.add(folded_name)
            item_names.append(normalized_name)
        return item_names

    def _on_no_wear_toggled(self) -> None:
        if self.no_wear_item_var.get():
            for variable in self.wear_vars.values():
                variable.set(False)
        self._refresh_no_wear_mode()

    def _refresh_no_wear_mode(self) -> None:
        is_no_wear_item = self.no_wear_item_var.get()
        wear_state = "disabled" if is_no_wear_item else "!disabled"
        self.select_all_wears_button.state([wear_state])
        self.clear_wears_button.state([wear_state])
        for wear_checkbutton in self.wear_checkbuttons:
            wear_checkbutton.state([wear_state])

        max_float_state = "disabled" if is_no_wear_item else "!disabled"
        self.max_float_entry.state([max_float_state])

        sticker_state = "disabled" if is_no_wear_item else "!disabled"
        self.has_stickers_check.state([sticker_state])
        self.no_stickers_check.state([sticker_state])

        if is_no_wear_item:
            self.has_stickers_var.set(False)
            self.no_stickers_var.set(False)

    def _refresh_provider_summary(self, *_args: object) -> None:
        provider_key = self.provider_label_to_key.get(
            self.settings_third_party_provider_var.get(),
            tpms.PROVIDER_SKINPORT,
        )
        if not self.settings_enable_third_party_support_var.get():
            self.provider_summary_var.set("Steam remains the active source. Third-party support is currently off.")
            return
        self.provider_summary_var.set(tpms.describe_provider_status(provider_key))

    def _set_all_wears(self, selected: bool) -> None:
        if self.no_wear_item_var.get():
            return
        for variable in self.wear_vars.values():
            variable.set(selected)

    def _on_item_name_key_release(self, _event: tk.Event[Any]) -> None:
        self.item_name_var.set(self._get_item_name_text().rstrip("\n"))
        self._trigger_autocomplete(force_refresh=False)

    def _on_editor_state_changed(self, *_args: object) -> None:
        self._refresh_editor_summary()
        self._refresh_provider_summary()

    def _trigger_autocomplete(self, force_refresh: bool) -> None:
        query_text = self._get_item_name_text().strip()
        self.item_name_var.set(query_text)
        if "\n" in query_text:
            self._set_suggestions([])
            self.status_var.set("Bulk item list detected. Autocomplete is paused until the input is back to one line.")
            return
        if len(query_text) < AUTOCOMPLETE_MIN_CHARS:
            self._set_suggestions([])
            return

        cached_suggestions = self.autocomplete_cache.get_cached_suggestions(query_text)
        if cached_suggestions:
            self._set_suggestions(cached_suggestions)
            if not force_refresh:
                return

        self.autocomplete_request_id += 1
        request_id = self.autocomplete_request_id
        self.status_var.set(f"Refreshing suggestions for '{query_text}'...")

        def worker() -> None:
            try:
                suggestions = self.autocomplete_cache.fetch_and_cache_suggestions(query_text)
                self.worker_events.put(
                    {
                        "type": "autocomplete",
                        "request_id": request_id,
                        "query_text": query_text,
                        "suggestions": suggestions,
                    }
                )
            except Exception as exc:
                self.worker_events.put(
                    {
                        "type": "autocomplete_error",
                        "request_id": request_id,
                        "query_text": query_text,
                        "error": str(exc),
                    }
                )

        threading.Thread(target=worker, daemon=True).start()

    def _set_suggestions(self, suggestions: List[MarketSuggestion]) -> None:
        self.current_suggestions = suggestions
        self.suggestion_tree.delete(*self.suggestion_tree.get_children())
        for index, suggestion in enumerate(suggestions):
            wears_text = ", ".join(suggestion.wears) if suggestion.wears else "No wear / no float"
            self.suggestion_tree.insert(
                "",
                "end",
                iid=str(index),
                tags=("altrow",) if index % 2 else (),
                values=(suggestion.base_name, wears_text),
            )
        self.suggestion_tree.tag_configure("altrow", background=TABLE_ALT_ROW)
        matching_suggestion = self._matching_suggestion_for_item_name(self.item_name_var.get())
        if matching_suggestion is not None and not matching_suggestion.wears:
            self.no_wear_item_var.set(True)
            self._refresh_no_wear_mode()

    def _matching_suggestion_for_item_name(self, item_name: str) -> Optional[MarketSuggestion]:
        normalized_item_name = sme.normalize_market_hash_name_input(item_name.strip())
        normalized_item_name = sme.normalize_market_hash_name_input(strip_wear_suffix(normalized_item_name)).casefold()
        if not normalized_item_name:
            return None

        for suggestion in self.current_suggestions:
            normalized_base_name = sme.normalize_market_hash_name_input(suggestion.base_name).casefold()
            if normalized_item_name == normalized_base_name:
                return suggestion

            normalized_example_name = sme.normalize_market_hash_name_input(
                strip_wear_suffix(suggestion.example_hash_name)
            ).casefold()
            if normalized_item_name == normalized_example_name:
                return suggestion
        return None

    def _on_suggestion_selected(self, _event: tk.Event[Any]) -> None:
        selection = self.suggestion_tree.selection()
        if not selection:
            return
        suggestion = self.current_suggestions[int(selection[0])]
        self._set_item_name_text(suggestion.base_name)
        is_no_wear_item = not suggestion.wears
        self.no_wear_item_var.set(is_no_wear_item)
        for wear_name, variable in self.wear_vars.items():
            variable.set((not is_no_wear_item) and wear_name in suggestion.wears)
        if not is_no_wear_item and not any(variable.get() for variable in self.wear_vars.values()) and suggestion.wears:
            self.wear_vars[suggestion.wears[0]].set(True)
        self._refresh_no_wear_mode()
        self.status_var.set(f"Loaded suggestion for {suggestion.base_name}.")

    def _selected_wears(self) -> List[str]:
        return [
            wear_name
            for wear_name, variable in self.wear_vars.items()
            if variable.get()
        ]

    def _refresh_editor_summary(self) -> None:
        item_names = self._get_bulk_item_names()
        if len(item_names) > 1:
            item_name = f"{len(item_names)} pasted item names"
        else:
            item_name = (item_names[0] if item_names else "No item selected yet")
        selected_wears = self._selected_wears()
        wears_text = (
            "not applicable (case / sticker / no-float item)"
            if self.no_wear_item_var.get()
            else (", ".join(selected_wears) if selected_wears else "no wear selected")
        )

        active_filters: List[str] = []
        if self.max_float_var.get().strip() and not self.no_wear_item_var.get():
            active_filters.append(f"float <= {self.max_float_var.get().strip()}")
        if self.max_price_var.get().strip():
            active_filters.append(f"price <= {self.max_price_var.get().strip()}")
        if self.paint_seed_var.get().strip():
            active_filters.append(f"paint seed = {self.paint_seed_var.get().strip()}")
        if self.has_stickers_var.get() and not self.no_wear_item_var.get():
            active_filters.append("has stickers")
        if self.no_stickers_var.get() and not self.no_wear_item_var.get():
            active_filters.append("no stickers")

        sort_text = self.sort_by_var.get() or "price"
        direction_text = "descending" if self.descending_var.get() else "ascending"
        filter_text = ", ".join(active_filters) if active_filters else "no extra filters"

        self.editor_summary_var.set(
            f"Item: {item_name}\n"
            f"Wear: {wears_text}\n"
            f"Filters: {filter_text}\n"
            f"Sort: {sort_text} ({direction_text}), limit {self.limit_var.get().strip() or DEFAULT_DESKTOP_LIMIT}"
        )

    def _build_queries_from_editor(self) -> List[DesktopQuery]:
        item_names = self._get_bulk_item_names()
        if not item_names:
            raise ValueError("Item name is required")

        inferred_suggestion = None
        if len(item_names) == 1:
            inferred_suggestion = self._matching_suggestion_for_item_name(item_names[0])
        if inferred_suggestion is not None and not inferred_suggestion.wears and not self.no_wear_item_var.get():
            self.no_wear_item_var.set(True)
            self._refresh_no_wear_mode()

        if self.no_wear_item_var.get():
            return [
                create_query_from_form(
                    base_name=item_name,
                    wear_name=None,
                    item_has_no_wear=True,
                    max_float_text=self.max_float_var.get(),
                    max_price_text=self.max_price_var.get(),
                    paint_seed_text=self.paint_seed_var.get(),
                    has_stickers=self.has_stickers_var.get(),
                    no_stickers=self.no_stickers_var.get(),
                    min_sticker_count_text=self.min_sticker_count_var.get(),
                    max_sticker_count_text=self.max_sticker_count_var.get(),
                    sort_by=[self.sort_by_var.get()],
                    descending=self.descending_var.get(),
                    limit_text=self.limit_var.get(),
                )
                for item_name in item_names
            ]

        if len(item_names) > 1:
            return self._build_bulk_skin_queries(item_names)

        selected_wears = self._selected_wears()
        if not selected_wears:
            raise ValueError("Select at least one wear checkbox")

        if inferred_suggestion is None:
            raise ValueError(
                "For skins, choose an exact autocomplete suggestion before adding the query."
            )
        missing_wears = [
            wear_name for wear_name in selected_wears if wear_name not in inferred_suggestion.wears
        ]
        if missing_wears:
            missing_wears_text = ", ".join(missing_wears)
            raise ValueError(
                f"The selected autocomplete item does not support these wear values: {missing_wears_text}"
            )

        queries = [
            create_query_from_form(
                base_name=item_names[0],
                wear_name=wear_name,
                item_has_no_wear=False,
                max_float_text=self.max_float_var.get(),
                max_price_text=self.max_price_var.get(),
                paint_seed_text=self.paint_seed_var.get(),
                has_stickers=self.has_stickers_var.get(),
                no_stickers=self.no_stickers_var.get(),
                min_sticker_count_text=self.min_sticker_count_var.get(),
                max_sticker_count_text=self.max_sticker_count_var.get(),
                sort_by=[self.sort_by_var.get()],
                descending=self.descending_var.get(),
                limit_text=self.limit_var.get(),
            )
            for wear_name in selected_wears
        ]
        return queries

    def _build_bulk_skin_queries(self, item_names: List[str]) -> List[DesktopQuery]:
        base_suggestions_by_name: Dict[str, List[MarketSuggestion]] = {}
        normalized_base_name_lookup: Dict[str, str] = {}
        validation_errors: List[str] = []
        bulk_queries: List[DesktopQuery] = []

        for item_name in item_names:
            normalized_market_hash_name = sme.normalize_market_hash_name_input(item_name)
            wear_name = sme.extract_wear_name_from_market_hash_name(normalized_market_hash_name)
            if wear_name is None:
                validation_errors.append(
                    f"{item_name}: include the exact wear in parentheses, like (Factory New)"
                )
                continue

            base_name = strip_wear_suffix(normalized_market_hash_name)
            normalized_base_name = sme.normalize_market_hash_name_input(base_name).casefold()
            if normalized_base_name not in base_suggestions_by_name:
                base_suggestions_by_name[normalized_base_name] = self.autocomplete_cache.fetch_and_cache_suggestions(base_name)
                normalized_base_name_lookup[normalized_base_name] = base_name

            temp_query = DesktopQuery(
                base_name=base_name,
                wear=wear_name,
                sort_by=[self.sort_by_var.get()],
                descending=self.descending_var.get(),
                limit=int(self.limit_var.get().strip() or DEFAULT_DESKTOP_LIMIT),
            )

            base_suggestions = base_suggestions_by_name[normalized_base_name]
            is_valid = any(
                query_matches_suggestion(temp_query, suggestion)
                for suggestion in base_suggestions
            )

            if not is_valid:
                exact_suggestions = self.autocomplete_cache.fetch_and_cache_suggestions(normalized_market_hash_name)
                is_valid = any(
                    query_matches_suggestion(temp_query, suggestion)
                    for suggestion in exact_suggestions
                )

            if not is_valid:
                validation_errors.append(
                    f"{normalized_market_hash_name}: Steam did not confirm that exact skin + wear combination"
                )
                continue

            bulk_queries.append(
                create_query_from_form(
                    base_name=base_name,
                    wear_name=wear_name,
                    item_has_no_wear=False,
                    max_float_text="",
                    max_price_text="",
                    paint_seed_text="",
                    has_stickers=False,
                    no_stickers=False,
                    min_sticker_count_text="",
                    max_sticker_count_text="",
                    sort_by=[self.sort_by_var.get()],
                    descending=self.descending_var.get(),
                    limit_text=self.limit_var.get(),
                )
            )

        if validation_errors:
            error_preview = "\n".join(f"- {error}" for error in validation_errors[:8])
            if len(validation_errors) > 8:
                error_preview += f"\n- ...and {len(validation_errors) - 8} more"
            raise ValueError(
                "Bulk skin add could not validate every exact item name.\n\n"
                f"{error_preview}"
            )

        return bulk_queries

    def _add_queries_from_editor(self) -> None:
        try:
            new_queries = self._build_queries_from_editor()
        except ValueError as exc:
            messagebox.showerror("Invalid query", str(exc), parent=self.root)
            return

        start_index = len(self.query_items)
        self.query_items.extend(new_queries)
        for offset, query in enumerate(new_queries):
            self.query_validation_statuses[start_index + offset] = self._default_validation_status_for_query(query)
        self._refresh_query_tree()
        self._persist_query_queue()
        self._append_log(f"Added {len(new_queries)} queued quer{'y' if len(new_queries) == 1 else 'ies'}.")

    def _populate_editor_from_selected_query(self) -> None:
        selected_indices = self._selected_query_indices_from_tree()
        if len(selected_indices) != 1:
            messagebox.showinfo("Select one query", "Choose exactly one queued item to load into the editor.", parent=self.root)
            return

        selected_index = selected_indices[0]
        query = self.query_items[selected_index]
        self._set_item_name_text(query.base_name)
        self.max_float_var.set("" if query.max_float is None else str(query.max_float))
        self.max_price_var.set("" if query.max_price is None else str(query.max_price))
        self.paint_seed_var.set("" if query.paint_seed is None else str(query.paint_seed))
        self.min_sticker_count_var.set("" if query.min_sticker_count is None else str(query.min_sticker_count))
        self.max_sticker_count_var.set("" if query.max_sticker_count is None else str(query.max_sticker_count))
        self.limit_var.set(str(query.limit))
        self.sort_by_var.set(query.sort_by[0] if query.sort_by else "price")
        self.descending_var.set(query.descending)
        self.has_stickers_var.set(query.has_stickers)
        self.no_stickers_var.set(query.no_stickers)
        self.no_wear_item_var.set(query.wear is None)
        for wear_name, variable in self.wear_vars.items():
            variable.set(query.wear is not None and wear_name == query.wear)
        self._refresh_no_wear_mode()

    def _remove_selected_queries(self) -> None:
        selected_indices = sorted(self._selected_query_indices_from_tree(), reverse=True)
        if not selected_indices:
            return
        for index in selected_indices:
            del self.query_items[index]
        self._clear_validation_statuses()
        self._refresh_query_tree()
        self._persist_query_queue()
        self._append_log(f"Removed {len(selected_indices)} queued quer{'y' if len(selected_indices) == 1 else 'ies'}.")

    def _clear_query_queue(self) -> None:
        if not self.query_items:
            return
        self.query_items.clear()
        self._clear_validation_statuses()
        self._refresh_query_tree()
        self._persist_query_queue()
        self._append_log("Cleared the queued query list.")

    def _clear_results_workspace(self) -> None:
        for tab_info in getattr(self, "result_tabs", []):
            tab_info["frame"].destroy()
        self.result_tabs = []
        self.active_result_tab_index = None
        if hasattr(self, "results_tab_bar"):
            self._render_results_tab_bar()
        if not self.results_placeholder.winfo_ismapped():
            self.results_placeholder.grid(row=0, column=0, sticky="nsew")
        self.results_summary_var.set("Run a search to open result tabs here.")
        self.status_var.set("Results cleared.")
        self._append_log("Cleared all open result tabs.")

    @staticmethod
    def _result_tab_grid_position(index: int) -> tuple[int, int]:
        return divmod(index, RESULT_TABS_PER_ROW)

    @staticmethod
    def _format_result_tab_title(raw_title: str) -> str:
        clean_title = (raw_title or "").strip() or "Item"
        if len(clean_title) <= RESULT_TAB_MAX_LABEL_CHARS:
            return clean_title
        return f"{clean_title[: RESULT_TAB_MAX_LABEL_CHARS - 1]}\u2026"

    def _render_results_tab_bar(self) -> None:
        for child in self.results_tab_bar.winfo_children():
            child.destroy()

        if not self.result_tabs:
            return

        for index, tab_info in enumerate(self.result_tabs):
            row_index, column_index = self._result_tab_grid_position(index)
            is_active = index == self.active_result_tab_index
            background_color = (
                RESULT_TAB_ACTIVE_BACKGROUND if is_active else RESULT_TAB_INACTIVE_BACKGROUND
            )
            foreground_color = (
                RESULT_TAB_ACTIVE_FOREGROUND if is_active else RESULT_TAB_INACTIVE_FOREGROUND
            )
            displayed_title = self._format_result_tab_title(tab_info["title"])

            tab_frame = tk.Frame(
                self.results_tab_bar,
                background=background_color,
                highlightbackground=RESULT_TAB_BORDER_COLOR,
                highlightcolor=RESULT_TAB_BORDER_COLOR,
                highlightthickness=1,
                borderwidth=0,
                cursor="hand2",
            )
            tab_frame.grid(row=row_index, column=column_index, sticky="w", padx=0, pady=0)

            tab_label = tk.Label(
                tab_frame,
                text=displayed_title,
                font=("Segoe UI Semibold", 7) if is_active else ("Segoe UI", 7),
                background=background_color,
                foreground=foreground_color,
                anchor="w",
                justify="left",
                padx=5,
                pady=2,
                width=max(RESULT_TAB_MIN_WIDTH_CHARS, len(displayed_title)),
                cursor="hand2",
            )
            tab_label.pack(fill="x")
            tab_frame.bind(
                "<Button-1>",
                lambda _event, selected_index=index: self._select_result_tab(selected_index),
            )
            tab_label.bind(
                "<Button-1>",
                lambda _event, selected_index=index: self._select_result_tab(selected_index),
            )

        self.results_tab_canvas.update_idletasks()
        self.results_tab_canvas.configure(scrollregion=self.results_tab_canvas.bbox("all"))

    def _select_result_tab(self, index: int) -> None:
        if index < 0 or index >= len(self.result_tabs):
            return
        self.active_result_tab_index = index
        self.results_placeholder.grid_remove()
        selected_frame = self.result_tabs[index]["frame"]
        selected_frame.tkraise()
        self._render_results_tab_bar()

    def _replace_result_tab(self, index: int, result: QueryExecutionResult) -> None:
        if index < 0 or index >= len(self.result_tabs):
            return

        old_frame = self.result_tabs[index]["frame"]
        old_frame.destroy()
        new_tab_info = self._create_result_tab_info(result)
        self.result_tabs[index] = new_tab_info
        self.active_result_tab_index = index
        self._select_result_tab(index)

    def _create_result_tab_info(self, result: QueryExecutionResult) -> Dict[str, Any]:
        tab = ttk.Frame(self.results_content_frame, padding=12, style="Card.TFrame")
        tab.grid(row=0, column=0, sticky="nsew")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        tab_title = result.query.base_name
        return {
            "title": tab_title,
            "frame": tab,
            "result": result,
        }

    def _build_query_filters_text(self, query: DesktopQuery) -> str:
            filter_parts: List[str] = []
            if query.max_float is not None:
                filter_parts.append(f"float <= {query.max_float}")
            if query.max_price is not None:
                filter_parts.append(f"price <= {query.max_price}")
            if query.paint_seed is not None:
                filter_parts.append(f"seed {query.paint_seed}")
            if query.wear is not None:
                if query.has_stickers:
                    filter_parts.append("has stickers")
                if query.no_stickers:
                    filter_parts.append("no stickers")
            return " | ".join(filter_parts) if filter_parts else "no extra filters"

    def _selected_query_indices_from_tree(self) -> List[int]:
        selected_indices: List[int] = []
        seen_indices = set()
        for tree, mapping in (
            (self.query_tree_left, self.left_query_row_mappings),
            (self.query_tree_right, self.right_query_row_mappings),
        ):
            for item_id in tree.selection():
                query_index = mapping.get(item_id)
                if query_index is None or query_index in seen_indices:
                    continue
                seen_indices.add(query_index)
                selected_indices.append(query_index)
        return sorted(selected_indices)

    def _refresh_query_tree(self) -> None:
        self.query_tree_left.delete(*self.query_tree_left.get_children())
        self.query_tree_right.delete(*self.query_tree_right.get_children())
        self.left_query_row_mappings = {}
        self.right_query_row_mappings = {}
        for row_number, left_index in enumerate(range(0, len(self.query_items), 2)):
            row_id = f"row-{row_number}"
            right_index = left_index + 1
            left_query = self.query_items[left_index]
            right_query = self.query_items[right_index] if right_index < len(self.query_items) else None
            self.left_query_row_mappings[row_id] = left_index
            if right_query is not None:
                self.right_query_row_mappings[row_id] = right_index

            current_statuses = self._current_validation_statuses()
            left_status = current_statuses.get(
                left_index,
                self._default_validation_status_for_query(left_query),
            )
            right_status = (
                current_statuses.get(
                    right_index,
                    self._default_validation_status_for_query(right_query),
                )
                if right_query is not None
                else ""
            )
            self.query_tree_left.insert(
                "",
                "end",
                iid=row_id,
                tags=("altrow",) if row_number % 2 else (),
                values=(
                    build_query_label(left_query),
                    self._build_query_filters_text(left_query),
                    left_status,
                ),
            )
            self.query_tree_right.insert(
                "",
                "end",
                iid=row_id,
                tags=("altrow",) if row_number % 2 else (),
                values=(
                    build_query_label(right_query) if right_query is not None else "",
                    self._build_query_filters_text(right_query) if right_query is not None else "",
                    right_status,
                ),
            )
        self.query_tree_left.tag_configure("altrow", background=TABLE_ALT_ROW)
        self.query_tree_right.tag_configure("altrow", background=TABLE_ALT_ROW)
        if not self.query_items:
            self.queue_summary_var.set("No searches queued yet. Add one or more query rows above to build a batch.")
            return
        wear_based_count = sum(1 for query in self.query_items if query.wear is not None)
        no_wear_count = len(self.query_items) - wear_based_count
        summary_parts = [
            f"{len(self.query_items)} queued search{'es' if len(self.query_items) != 1 else ''}",
            f"{wear_based_count} wear-based" if wear_based_count else None,
            f"{no_wear_count} no-wear" if no_wear_count else None,
        ]
        summary_text = ", ".join(part for part in summary_parts if part)
        self.queue_summary_var.set(f"{summary_text}. Select rows here to run only part of the batch.")

    def _collect_runtime_settings(self) -> DesktopSettings:
        try:
            page_delay = float(self.settings_page_delay_var.get().strip())
            retries = int(self.settings_retries_var.get().strip())
            pause_between_queries = float(self.settings_pause_var.get().strip())
        except ValueError as exc:
            raise ValueError("Page delay, retries, and pause values must be numeric") from exc

        if page_delay < 0 or retries < 0 or pause_between_queries < 0:
            raise ValueError("Page delay, retries, and pause values cannot be negative")

        settings = DesktopSettings(
            currency=self.settings.currency,
            country=self.settings.country,
            language=self.settings.language,
            steam_page_delay=page_delay,
            steam_max_retries=retries,
            pause_between_queries=pause_between_queries,
            continue_on_error=self.settings_continue_var.get(),
            combine_case_exports=self.settings_combine_case_exports_var.get(),
            enable_third_party_support=self.settings_enable_third_party_support_var.get(),
            third_party_provider=self.provider_label_to_key.get(
                self.settings_third_party_provider_var.get(),
                tpms.PROVIDER_SKINPORT,
            ),
        )
        return settings

    def _save_settings_from_ui(self) -> None:
        try:
            self.settings = self._collect_runtime_settings()
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc), parent=self.root)
            return

        save_desktop_settings(self.settings)
        self._append_log("Saved desktop settings.")
        self.status_var.set("Settings saved.")

    def _save_app_state_from_ui(self) -> None:
        try:
            self.settings = self._collect_runtime_settings()
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc), parent=self.root)
            return

        save_desktop_settings(self.settings)
        save_desktop_query_queue(self.query_items)
        self._append_log("Saved desktop settings and queued searches.")
        self.status_var.set("App state saved.")

    def _persist_query_queue(self) -> None:
        save_desktop_query_queue(self.query_items)

    def _clear_validation_statuses(self) -> None:
        self.query_validation_statuses = {}

    def _default_validation_status_for_query(self, query: DesktopQuery) -> str:
        if query.wear is not None:
            return "Valid"

        matching_suggestion = self._matching_suggestion_for_item_name(query.base_name)
        if matching_suggestion is not None and not matching_suggestion.wears:
            return "Valid"

        return "Not checked"

    def _current_validation_statuses(self) -> Dict[int, str]:
        return getattr(self, "query_validation_statuses", {})

    def _queries_requiring_explicit_validation(
        self,
        query_indices: List[int],
    ) -> List[tuple[int, DesktopQuery]]:
        queries_to_validate: List[tuple[int, DesktopQuery]] = []
        current_statuses = self._current_validation_statuses()
        for query_index in query_indices:
            query = self.query_items[query_index]
            if query.wear is not None:
                continue
            if current_statuses.get(query_index) == "Valid":
                continue
            queries_to_validate.append((query_index, query))
        return queries_to_validate

    def _validate_queries(self, queries: List[DesktopQuery]) -> List[QueryValidationResult]:
        return [
            validate_query_against_market(query, self.autocomplete_cache)
            for query in queries
        ]

    def _apply_validation_results(self, results: List[QueryValidationResult]) -> None:
        status_lookup = {
            build_query_label(result.query): result.status_text
            for result in results
        }
        updated_statuses: Dict[int, str] = {}
        current_statuses = self._current_validation_statuses()
        for index, query in enumerate(self.query_items):
            label = build_query_label(query)
            if label in status_lookup:
                updated_statuses[index] = status_lookup[label]
            else:
                updated_statuses[index] = current_statuses.get(
                    index,
                    self._default_validation_status_for_query(query),
                )
        self.query_validation_statuses = updated_statuses
        self._refresh_query_tree()

    def _validate_queue_from_ui(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Already running", "Wait for the current background task to finish first.", parent=self.root)
            return
        if not self.query_items:
            messagebox.showinfo("No queued searches", "Add one or more queries before validating.", parent=self.root)
            return

        query_indices = list(range(len(self.query_items)))
        indexed_queries = self._queries_requiring_explicit_validation(query_indices)
        if not indexed_queries:
            messagebox.showinfo(
                "Nothing to validate",
                "Only bulk or no-wear queue items need explicit validation. Skin queries already use autocomplete as their validation step.",
                parent=self.root,
            )
            return

        self.status_var.set(
            f"Validating {len(indexed_queries)} queued quer{'y' if len(indexed_queries) == 1 else 'ies'}..."
        )
        self._append_log(self.status_var.get())

        def worker() -> None:
            results = self._validate_queries([query for _, query in indexed_queries])
            self.worker_events.put(
                {
                    "type": "validation_result",
                    "results": results,
                }
            )

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def _on_close(self) -> None:
        try:
            self.settings = self._collect_runtime_settings()
            save_desktop_settings(self.settings)
        except ValueError:
            pass

        self._persist_query_queue()
        self.root.destroy()

    def _start_run(self, *, selected_only: bool) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Already running", "A batch is already running right now.", parent=self.root)
            return

        if selected_only:
            selected_indices = self._selected_query_indices_from_tree()
            queries_to_run = [self.query_items[index] for index in selected_indices]
        else:
            selected_indices = list(range(len(self.query_items)))
            queries_to_run = list(self.query_items)

        if not queries_to_run:
            messagebox.showinfo("No queued searches", "Add one or more queries before running.", parent=self.root)
            return

        try:
            settings = self._collect_runtime_settings()
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc), parent=self.root)
            return

        self.settings = settings
        save_desktop_settings(settings)
        self._persist_query_queue()

        indexed_queries_to_validate = self._queries_requiring_explicit_validation(selected_indices)
        if indexed_queries_to_validate:
            validation_results = self._validate_queries([query for _, query in indexed_queries_to_validate])
            self._apply_validation_results(validation_results)
            invalid_results = [result for result in validation_results if not result.is_valid]
            if invalid_results:
                invalid_labels = "\n".join(f"- {build_query_label(result.query)}" for result in invalid_results)
                self.status_var.set("Validation found missing market items.")
                self._append_log("Validation found missing market items.")
                messagebox.showerror(
                    "Invalid queued items",
                    "These queued item names do not currently match a Steam market item exactly:\n\n"
                    f"{invalid_labels}\n\nFix or remove them before running the queue.",
                    parent=self.root,
                )
                return

        self.status_var.set(f"Running {len(queries_to_run)} queued quer{'y' if len(queries_to_run) == 1 else 'ies'}...")
        self._append_log(self.status_var.get())
        self._append_log(f"Provider mode: {describe_runtime_provider_mode(settings)}")

        def worker() -> None:
            for query_index, query in enumerate(queries_to_run, start=1):
                label = build_query_label(query)
                self.worker_events.put(
                    {
                        "type": "status",
                        "message": f"Running {query_index}/{len(queries_to_run)}: {label}",
                    }
                )
                try:
                    result = execute_desktop_query(query, settings)
                    self.worker_events.put(
                        {
                            "type": "result",
                            "result": result,
                        }
                    )
                except Exception as exc:
                    self.worker_events.put(
                        {
                            "type": "query_error",
                            "query": query,
                            "error": str(exc),
                        }
                    )
                    if not settings.continue_on_error:
                        break

                if settings.pause_between_queries > 0 and query_index < len(queries_to_run):
                    time.sleep(settings.pause_between_queries)

            self.worker_events.put({"type": "finished"})

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def _poll_worker_events(self) -> None:
        while True:
            try:
                event = self.worker_events.get_nowait()
            except queue.Empty:
                break
            self._handle_worker_event(event)

        self.root.after(150, self._poll_worker_events)

    def _handle_worker_event(self, event: Dict[str, Any]) -> None:
        event_type = event["type"]
        if event_type == "status":
            self.status_var.set(event["message"])
            self._append_log(event["message"])
            return

        if event_type == "autocomplete":
            if event["request_id"] != self.autocomplete_request_id:
                return
            self._set_suggestions(event["suggestions"])
            self.status_var.set(f"Loaded {len(event['suggestions'])} suggestion(s).")
            return

        if event_type == "autocomplete_error":
            if event["request_id"] != self.autocomplete_request_id:
                return
            self.status_var.set("Suggestion refresh failed.")
            self._append_log(f"Autocomplete error for '{event['query_text']}': {event['error']}")
            return

        if event_type == "validation_result":
            results: List[QueryValidationResult] = event["results"]
            self._apply_validation_results(results)
            invalid_count = sum(1 for result in results if not result.is_valid)
            if invalid_count:
                self.status_var.set(f"Validation finished. {invalid_count} item name(s) need attention.")
                self._append_log(self.status_var.get())
            else:
                self.status_var.set(f"Validation finished. All {len(results)} queued item names matched Steam.")
                self._append_log(self.status_var.get())
            return

        if event_type == "result":
            result: QueryExecutionResult = event["result"]
            self._show_result_tab(result)
            summary = sme.build_fetch_result_summary(result.fetch_result)
            self.status_var.set(summary)
            self._append_log(summary)
            return

        if event_type == "query_error":
            query: DesktopQuery = event["query"]
            error_message = f"Failed {build_query_label(query)}: {event['error']}"
            self.status_var.set(error_message)
            self._append_log(error_message)
            return

        if event_type == "finished":
            self.status_var.set("Run finished.")
            self._append_log("Run finished.")

    def _show_result_tab(self, result: QueryExecutionResult) -> None:
        tab_info = self._create_result_tab_info(result)
        tab = tab_info["frame"]

        canvas_container = ttk.Frame(tab, style="Card.TFrame")
        canvas_container.grid(row=0, column=0, sticky="nsew")
        canvas_container.columnconfigure(0, weight=1)
        canvas_container.rowconfigure(0, weight=1)

        result_canvas = tk.Canvas(
            canvas_container,
            background=CARD_BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
        )
        result_canvas.grid(row=0, column=0, sticky="nsew")

        result_y_scroll = ttk.Scrollbar(canvas_container, orient="vertical", command=result_canvas.yview)
        result_y_scroll.grid(row=0, column=1, sticky="ns")
        result_x_scroll = ttk.Scrollbar(canvas_container, orient="horizontal", command=result_canvas.xview)
        result_x_scroll.grid(row=1, column=0, sticky="ew")
        result_canvas.configure(yscrollcommand=result_y_scroll.set, xscrollcommand=result_x_scroll.set)
        self._bind_scrollable_widget(
            result_canvas,
            lambda steps: result_canvas.yview_scroll(steps, "units"),
            lambda steps: result_canvas.xview_scroll(steps, "units"),
        )

        scroll_content = ttk.Frame(result_canvas, style="Card.TFrame", padding=(0, 0, 4, 0))
        scroll_content.columnconfigure(0, weight=1)
        scroll_window = result_canvas.create_window((0, 0), window=scroll_content, anchor="nw")

        def refresh_scrollregion(_event: tk.Event[Any]) -> None:
            result_canvas.configure(scrollregion=result_canvas.bbox("all"))

        def fit_scroll_content(event: tk.Event[Any]) -> None:
            result_canvas.itemconfigure(scroll_window, width=max(event.width, 1100))

        scroll_content.bind("<Configure>", refresh_scrollregion)
        result_canvas.bind("<Configure>", fit_scroll_content)

        summary_lines = [
            build_query_label(result.query),
            sme.build_fetch_result_summary(result.fetch_result),
            f"Matched rows: {len(result.matched_dataframe)}",
            f"Output file: {result.fetch_result.output_path}",
        ]
        ttk.Label(
            scroll_content,
            text="\n".join(summary_lines),
            justify="left",
            style="Body.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        next_row_index = 1
        if not sme.market_item_supports_wear(build_query_label(result.query)):
            actions_frame = ttk.Frame(scroll_content, style="Card.TFrame")
            actions_frame.grid(row=next_row_index, column=0, sticky="w", pady=(0, 10))
            next_row_index += 1

            def apply_manual_override() -> None:
                current_price = None
                if not result.fetch_result.dataframe.empty and "price" in result.fetch_result.dataframe.columns:
                    current_price = pd.to_numeric(
                        pd.Series([result.fetch_result.dataframe.iloc[-1]["price"]]),
                        errors="coerce",
                    ).iloc[0]
                prompt_text = f"Enter the corrected current lowest price for {build_query_label(result.query)}."
                if pd.notna(current_price):
                    prompt_text += f"\nCurrent saved price: ${float(current_price):.2f}"
                new_price = simpledialog.askfloat(
                    "Update Latest Price",
                    prompt_text,
                    parent=self.root,
                    minvalue=0.01,
                )
                if new_price is None:
                    return

                try:
                    updated_result = apply_manual_price_override(
                        result.query,
                        self.settings,
                        new_price,
                        output_path=result.fetch_result.output_path,
                    )
                except Exception as exc:
                    messagebox.showerror("Update failed", str(exc), parent=self.root)
                    return

                current_tab_index = next(
                    (
                        index
                        for index, existing_tab_info in enumerate(self.result_tabs)
                        if existing_tab_info["frame"] is tab
                    ),
                    None,
                )
                if current_tab_index is None:
                    return
                self._replace_result_tab(current_tab_index, updated_result)
                summary = sme.build_fetch_result_summary(updated_result.fetch_result)
                self.status_var.set(summary)
                self._append_log(summary)

            ttk.Button(
                actions_frame,
                text="Update Latest Price",
                command=apply_manual_override,
                style="Accent.TButton",
            ).grid(row=0, column=0, sticky="w")

        stat_strip = ttk.Frame(scroll_content, style="InnerCard.TFrame", padding=10)
        stat_strip.grid(row=next_row_index, column=0, sticky="ew", pady=(0, 10))
        next_row_index += 1
        for column_index in range(4):
            stat_strip.columnconfigure(column_index, weight=1)
        stats = [
            ("Rows shown", str(len(result.display_dataframe))),
            ("Rows matched", str(len(result.matched_dataframe))),
            ("Sort", ", ".join(result.query.sort_by)),
            ("Limit", str(result.query.limit)),
        ]
        for column_index, (label_text, value_text) in enumerate(stats):
            ttk.Label(stat_strip, text=label_text, style="SectionLabel.TLabel").grid(row=0, column=column_index, sticky="w")
            ttk.Label(stat_strip, text=value_text, style="Body.TLabel").grid(row=1, column=column_index, sticky="w", pady=(2, 0))

        table_frame = ttk.LabelFrame(scroll_content, text=" Structured Results Table ", padding=10, style="Card.TLabelframe")
        table_frame.grid(row=next_row_index, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        result_tree = ttk.Treeview(
            table_frame,
            columns=list(result.display_dataframe.columns),
            show="headings",
            height=15,
        )
        for column_name in result.display_dataframe.columns:
            result_tree.heading(column_name, text=column_name.replace("_", " ").title())
            result_tree.column(column_name, anchor="w", width=140)

        for row_index, (_, row) in enumerate(result.display_dataframe.iterrows()):
            result_tree.insert(
                "",
                "end",
                tags=("altrow",) if row_index % 2 else (),
                values=[row[column_name] for column_name in result.display_dataframe.columns],
            )
        result_tree.tag_configure("altrow", background=TABLE_ALT_ROW)

        result_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=result_tree.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=result_tree.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        result_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self._bind_scrollable_widget(
            result_tree,
            lambda steps: result_tree.yview_scroll(steps, "units"),
            lambda steps: result_tree.xview_scroll(steps, "units"),
        )

        if self.results_placeholder.winfo_ismapped():
            self.results_placeholder.grid_remove()
        self.result_tabs.append(tab_info)
        self.active_result_tab_index = len(self.result_tabs) - 1
        self._select_result_tab(self.active_result_tab_index)
        self.results_summary_var.set(
            f"{len(self.result_tabs)} result tab{'s' if len(self.result_tabs) != 1 else ''} open. "
            f"Latest: {build_query_label(result.query)}."
        )

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


def main() -> None:
    root = tk.Tk()
    app = SMTEDesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
