from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
import steam_market_to_excel as sme

from smte_desktop_support import (
    AUTOCOMPLETE_MIN_CHARS,
    DEFAULT_DESKTOP_LIMIT,
    MarketAutocompleteCache,
    MarketSuggestion,
    DesktopQuery,
    DesktopSettings,
    QueryExecutionResult,
    WEAR_OPTIONS,
    build_query_label,
    create_query_from_form,
    execute_desktop_query,
    load_desktop_settings,
    save_desktop_settings,
)

SORT_OPTIONS = ["price", "float", "paint_seed", "sticker_count", "page"]
APP_BACKGROUND = "#f3efe7"
CARD_BACKGROUND = "#fffaf3"
ACCENT_COLOR = "#215f4e"
ACCENT_SOFT = "#dcece5"
TEXT_PRIMARY = "#223127"
TEXT_MUTED = "#5c6a62"
TABLE_ALT_ROW = "#f7f1e7"


class SMTEDesktopApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SMTE Desktop")
        self.root.geometry("1580x980")
        self.root.minsize(1320, 840)
        self.root.configure(background=APP_BACKGROUND)

        self.settings = load_desktop_settings()
        self.autocomplete_cache = MarketAutocompleteCache()
        self.query_items: List[DesktopQuery] = []
        self.current_suggestions: List[MarketSuggestion] = []
        self.worker_thread: Optional[threading.Thread] = None
        self.worker_events: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self.autocomplete_request_id = 0
        self.active_vertical_scroll_handler: Optional[Callable[[int], None]] = None
        self.active_horizontal_scroll_handler: Optional[Callable[[int], None]] = None

        self._build_variables()
        self._build_ui()
        self._bind_events()
        self._poll_worker_events()
        self._refresh_query_tree()

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

        self.settings_page_delay_var = tk.StringVar(value=str(self.settings.steam_page_delay))
        self.settings_retries_var = tk.StringVar(value=str(self.settings.steam_max_retries))
        self.settings_pause_var = tk.StringVar(value=str(self.settings.pause_between_queries))
        self.settings_continue_var = tk.BooleanVar(value=self.settings.continue_on_error)
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

        builder_frame = ttk.LabelFrame(outer, text=" Query Builder ", padding=14, style="Card.TLabelframe")
        builder_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        builder_frame.columnconfigure(0, weight=4)
        builder_frame.columnconfigure(1, weight=2)
        builder_frame.columnconfigure(2, weight=2)
        builder_frame.columnconfigure(3, weight=2)
        builder_frame.columnconfigure(4, weight=2)
        builder_frame.rowconfigure(2, weight=1)
        builder_frame.rowconfigure(4, weight=0)

        ttk.Label(builder_frame, text="Item Name", style="SectionLabel.TLabel").grid(row=0, column=0, sticky="w")
        self.item_entry = ttk.Entry(builder_frame, textvariable=self.item_name_var)
        self.item_entry.grid(row=1, column=0, sticky="ew", padx=(0, 10))

        self.refresh_suggestions_button = ttk.Button(
            builder_frame,
            text="Refresh Suggestions",
            style="Secondary.TButton",
            command=lambda: self._trigger_autocomplete(force_refresh=True),
        )
        self.refresh_suggestions_button.grid(row=1, column=1, sticky="ew", padx=(0, 10))

        ttk.Label(builder_frame, text="Sort By", style="SectionLabel.TLabel").grid(row=0, column=2, sticky="w")
        self.sort_by_combo = ttk.Combobox(
            builder_frame,
            textvariable=self.sort_by_var,
            values=SORT_OPTIONS,
            state="readonly",
        )
        self.sort_by_combo.grid(row=1, column=2, sticky="ew", padx=(0, 10))

        self.descending_check = ttk.Checkbutton(
            builder_frame,
            text="Descending",
            variable=self.descending_var,
        )
        self.descending_check.grid(row=1, column=3, sticky="w", padx=(0, 10))

        ttk.Label(builder_frame, text="Show Limit", style="SectionLabel.TLabel").grid(row=0, column=4, sticky="w")
        self.limit_entry = ttk.Entry(builder_frame, textvariable=self.limit_var)
        self.limit_entry.grid(row=1, column=4, sticky="ew")

        suggestion_frame = ttk.Frame(builder_frame, style="InnerCard.TFrame", padding=4)
        suggestion_frame.grid(row=2, column=0, columnspan=3, sticky="nsew", padx=(0, 10), pady=(10, 0))
        suggestion_frame.columnconfigure(0, weight=1)
        suggestion_frame.rowconfigure(2, weight=1)

        ttk.Label(
            suggestion_frame,
            text="Autocomplete Suggestions",
            style="SectionLabel.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            suggestion_frame,
            text=f"Suggestions start after {AUTOCOMPLETE_MIN_CHARS} characters and reuse a local cache for speed.",
            style="InnerHelper.TLabel",
            wraplength=520,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(2, 8))

        self.suggestion_tree = ttk.Treeview(
            suggestion_frame,
            columns=("base_name", "wears"),
            show="headings",
            height=3,
            selectmode="browse",
        )
        self.suggestion_tree.heading("base_name", text="Item Name")
        self.suggestion_tree.heading("wears", text="Available Wears")
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
        suggestion_x_scrollbar.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.suggestion_tree.configure(
            yscrollcommand=suggestion_scrollbar.set,
            xscrollcommand=suggestion_x_scrollbar.set,
        )

        filters_frame = ttk.LabelFrame(builder_frame, text=" Search Filters ", padding=12, style="Card.TLabelframe")
        filters_frame.grid(row=2, column=3, columnspan=2, sticky="nsew", pady=(10, 0))
        for column_index in range(4):
            filters_frame.columnconfigure(column_index, weight=1)
        filters_frame.rowconfigure(4, weight=1)

        ttk.Label(filters_frame, text="Max Float", style="SectionLabel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(filters_frame, textvariable=self.max_float_var).grid(row=1, column=0, sticky="ew", padx=(0, 8))

        ttk.Label(filters_frame, text="Max Price", style="SectionLabel.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Entry(filters_frame, textvariable=self.max_price_var).grid(row=1, column=1, sticky="ew", padx=(0, 8))

        ttk.Label(filters_frame, text="Paint Seed", style="SectionLabel.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Entry(filters_frame, textvariable=self.paint_seed_var).grid(row=1, column=2, sticky="ew", padx=(0, 8))

        sticker_mode_frame = ttk.Frame(filters_frame, style="InnerCard.TFrame", padding=8)
        sticker_mode_frame.grid(row=1, column=3, sticky="w")
        ttk.Label(sticker_mode_frame, text="Sticker Preference", style="SectionLabel.TLabel").pack(anchor="w", pady=(0, 4))
        ttk.Checkbutton(
            sticker_mode_frame,
            text="Has stickers",
            variable=self.has_stickers_var,
            command=self._toggle_sticker_mode,
        ).pack(anchor="w")
        ttk.Checkbutton(
            sticker_mode_frame,
            text="No stickers",
            variable=self.no_stickers_var,
            command=self._toggle_sticker_mode,
        ).pack(anchor="w")

        ttk.Label(filters_frame, text="Min Sticker Count", style="SectionLabel.TLabel").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(filters_frame, textvariable=self.min_sticker_count_var).grid(row=3, column=0, sticky="ew", padx=(0, 8))

        ttk.Label(filters_frame, text="Max Sticker Count", style="SectionLabel.TLabel").grid(row=2, column=1, sticky="w", pady=(10, 0))
        ttk.Entry(filters_frame, textvariable=self.max_sticker_count_var).grid(row=3, column=1, sticky="ew", padx=(0, 8))

        wear_frame = ttk.LabelFrame(filters_frame, text=" Wear Selection ", padding=8, style="Card.TLabelframe")
        wear_frame.grid(row=4, column=0, columnspan=4, sticky="nsew", pady=(12, 0))
        wear_frame.columnconfigure(0, weight=1)
        wear_frame.columnconfigure(1, weight=1)
        ttk.Label(
            wear_frame,
            text="Pick one or more wears. The app queues one search per wear.",
            style="Body.TLabel",
            wraplength=430,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Button(
            wear_frame,
            text="Select All Wears",
            style="Secondary.TButton",
            command=lambda: self._set_all_wears(True),
        ).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(0, 10))
        ttk.Button(
            wear_frame,
            text="Clear Wears",
            style="Secondary.TButton",
            command=lambda: self._set_all_wears(False),
        ).grid(row=1, column=1, sticky="w", pady=(0, 10))
        for index, wear_name in enumerate(WEAR_OPTIONS):
            ttk.Checkbutton(
                wear_frame,
                text=wear_name,
                variable=self.wear_vars[wear_name],
            ).grid(row=2 + (index // 2), column=index % 2, sticky="w", padx=(0, 12), pady=2)

        actions_frame = ttk.Frame(builder_frame, style="App.TFrame")
        actions_frame.grid(row=3, column=0, columnspan=5, sticky="ew", pady=(12, 0))
        for column_index in range(7):
            actions_frame.columnconfigure(column_index, weight=1)

        ttk.Button(actions_frame, text="Add Query", style="Primary.TButton", command=self._add_queries_from_editor).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(actions_frame, text="Populate From Selected", style="Secondary.TButton", command=self._populate_editor_from_selected_query).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(actions_frame, text="Remove Selected", style="Secondary.TButton", command=self._remove_selected_queries).grid(row=0, column=2, sticky="ew", padx=(0, 8))
        ttk.Button(actions_frame, text="Clear Queue", style="Secondary.TButton", command=self._clear_query_queue).grid(row=0, column=3, sticky="ew", padx=(0, 8))
        ttk.Button(actions_frame, text="Run Selected", style="Primary.TButton", command=lambda: self._start_run(selected_only=True)).grid(row=0, column=4, sticky="ew", padx=(0, 8))
        ttk.Button(actions_frame, text="Run All", style="Primary.TButton", command=lambda: self._start_run(selected_only=False)).grid(row=0, column=5, sticky="ew", padx=(0, 8))
        ttk.Button(actions_frame, text="Save Settings", style="Secondary.TButton", command=self._save_settings_from_ui).grid(row=0, column=6, sticky="ew")

        queue_frame = ttk.LabelFrame(builder_frame, text=" Queued Searches ", padding=8, style="Card.TLabelframe")
        queue_frame.grid(row=4, column=0, columnspan=5, sticky="nsew", pady=(12, 0))
        queue_frame.columnconfigure(0, weight=3)
        queue_frame.columnconfigure(1, weight=2)
        queue_frame.rowconfigure(1, weight=1)

        ttk.Label(
            queue_frame,
            textvariable=self.queue_summary_var,
            style="CardBody.TLabel",
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6), padx=(0, 10))

        settings_frame = ttk.Frame(queue_frame, style="InnerCard.TFrame", padding=8)
        settings_frame.grid(row=0, column=1, sticky="ew", pady=(0, 6))
        for column_index in range(8):
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

        self.query_tree = ttk.Treeview(
            queue_frame,
            columns=("queued_search", "filters", "run_plan"),
            show="headings",
            selectmode="extended",
            height=3,
        )
        for column_name, heading_text, width in (
            ("queued_search", "Queued Search", 430),
            ("filters", "Filters", 420),
            ("run_plan", "Run Plan", 250),
        ):
            self.query_tree.heading(column_name, text=heading_text)
            self.query_tree.column(column_name, width=width, anchor="w")

        self.query_tree.grid(row=1, column=0, columnspan=2, sticky="nsew")
        query_scrollbar = ttk.Scrollbar(queue_frame, orient="vertical", command=self.query_tree.yview)
        query_scrollbar.grid(row=1, column=2, sticky="ns")
        self.query_tree.configure(yscrollcommand=query_scrollbar.set)

        results_frame = ttk.LabelFrame(outer, text=" Results and Activity ", padding=12, style="Card.TLabelframe")
        results_frame.grid(row=3, column=0, sticky="nsew")
        results_frame.columnconfigure(0, weight=0)
        results_frame.columnconfigure(1, weight=1)
        results_frame.rowconfigure(2, weight=1)

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(results_frame, textvariable=self.status_var, style="CardStatus.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
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
        notebook_frame.rowconfigure(0, weight=1)

        self.results_notebook = ttk.Notebook(notebook_frame)
        self.results_notebook.grid(row=0, column=0, sticky="nsew")
        self.results_placeholder = ttk.Frame(notebook_frame, style="InnerCard.TFrame", padding=18)
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
        style.configure("TNotebook", background=APP_BACKGROUND, tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", padding=(14, 8), font=("Segoe UI Semibold", 10))
        style.map("TNotebook.Tab", background=[("selected", CARD_BACKGROUND), ("active", "#e7e0d2")])

    def _bind_events(self) -> None:
        self.item_entry.bind("<KeyRelease>", self._on_item_name_key_release)
        self.suggestion_tree.bind("<<TreeviewSelect>>", self._on_suggestion_selected)
        self.suggestion_tree.bind("<Double-Button-1>", self._on_suggestion_selected)
        self._bind_scrollable_widget(
            self.suggestion_tree,
            lambda steps: self.suggestion_tree.yview_scroll(steps, "units"),
            lambda steps: self.suggestion_tree.xview_scroll(steps, "units"),
        )
        self._bind_scrollable_widget(
            self.query_tree,
            lambda steps: self.query_tree.yview_scroll(steps, "units"),
            lambda steps: self.query_tree.xview_scroll(steps, "units"),
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

    def _toggle_sticker_mode(self) -> None:
        if self.has_stickers_var.get() and self.no_stickers_var.get():
            self.no_stickers_var.set(False)

    def _set_all_wears(self, selected: bool) -> None:
        for variable in self.wear_vars.values():
            variable.set(selected)

    def _on_item_name_key_release(self, _event: tk.Event[Any]) -> None:
        self._trigger_autocomplete(force_refresh=False)

    def _on_editor_state_changed(self, *_args: object) -> None:
        self._refresh_editor_summary()

    def _trigger_autocomplete(self, force_refresh: bool) -> None:
        query_text = self.item_name_var.get().strip()
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
            wears_text = ", ".join(suggestion.wears) if suggestion.wears else "No wear info yet"
            self.suggestion_tree.insert(
                "",
                "end",
                iid=str(index),
                tags=("altrow",) if index % 2 else (),
                values=(suggestion.base_name, wears_text),
            )
        self.suggestion_tree.tag_configure("altrow", background=TABLE_ALT_ROW)

    def _on_suggestion_selected(self, _event: tk.Event[Any]) -> None:
        selection = self.suggestion_tree.selection()
        if not selection:
            return
        suggestion = self.current_suggestions[int(selection[0])]
        self.item_name_var.set(suggestion.base_name)
        for wear_name, variable in self.wear_vars.items():
            variable.set(wear_name in suggestion.wears)
        if not any(variable.get() for variable in self.wear_vars.values()) and suggestion.wears:
            self.wear_vars[suggestion.wears[0]].set(True)
        self.status_var.set(f"Loaded suggestion for {suggestion.base_name}.")

    def _selected_wears(self) -> List[str]:
        return [
            wear_name
            for wear_name, variable in self.wear_vars.items()
            if variable.get()
        ]

    def _refresh_editor_summary(self) -> None:
        item_name = self.item_name_var.get().strip() or "No item selected yet"
        selected_wears = self._selected_wears()
        wears_text = ", ".join(selected_wears) if selected_wears else "no wear selected"

        active_filters: List[str] = []
        if self.max_float_var.get().strip():
            active_filters.append(f"float <= {self.max_float_var.get().strip()}")
        if self.max_price_var.get().strip():
            active_filters.append(f"price <= {self.max_price_var.get().strip()}")
        if self.paint_seed_var.get().strip():
            active_filters.append(f"paint seed = {self.paint_seed_var.get().strip()}")
        if self.has_stickers_var.get():
            active_filters.append("has stickers")
        if self.no_stickers_var.get():
            active_filters.append("no stickers")
        if self.min_sticker_count_var.get().strip():
            active_filters.append(f"stickers >= {self.min_sticker_count_var.get().strip()}")
        if self.max_sticker_count_var.get().strip():
            active_filters.append(f"stickers <= {self.max_sticker_count_var.get().strip()}")

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
        selected_wears = self._selected_wears()
        if not selected_wears:
            raise ValueError("Select at least one wear checkbox")

        queries = [
            create_query_from_form(
                base_name=self.item_name_var.get(),
                wear_name=wear_name,
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

    def _add_queries_from_editor(self) -> None:
        try:
            new_queries = self._build_queries_from_editor()
        except ValueError as exc:
            messagebox.showerror("Invalid query", str(exc), parent=self.root)
            return

        self.query_items.extend(new_queries)
        self._refresh_query_tree()
        self._append_log(f"Added {len(new_queries)} queued quer{'y' if len(new_queries) == 1 else 'ies'}.")

    def _populate_editor_from_selected_query(self) -> None:
        selected_items = self.query_tree.selection()
        if len(selected_items) != 1:
            messagebox.showinfo("Select one query", "Choose exactly one queued query to load into the editor.", parent=self.root)
            return

        selected_index = int(selected_items[0])
        query = self.query_items[selected_index]
        self.item_name_var.set(query.base_name)
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
        for wear_name, variable in self.wear_vars.items():
            variable.set(wear_name == query.wear)

    def _remove_selected_queries(self) -> None:
        selected_indices = sorted((int(item_id) for item_id in self.query_tree.selection()), reverse=True)
        if not selected_indices:
            return
        for index in selected_indices:
            del self.query_items[index]
        self._refresh_query_tree()
        self._append_log(f"Removed {len(selected_indices)} queued quer{'y' if len(selected_indices) == 1 else 'ies'}.")

    def _clear_query_queue(self) -> None:
        if not self.query_items:
            return
        self.query_items.clear()
        self._refresh_query_tree()
        self._append_log("Cleared the queued query list.")

    def _refresh_query_tree(self) -> None:
        self.query_tree.delete(*self.query_tree.get_children())
        for index, query in enumerate(self.query_items):
            sticker_mode = "has" if query.has_stickers else "none"
            if query.no_stickers:
                sticker_mode = "no"
            filter_parts: List[str] = []
            if query.max_float is not None:
                filter_parts.append(f"float <= {query.max_float}")
            if query.max_price is not None:
                filter_parts.append(f"price <= {query.max_price}")
            if query.paint_seed is not None:
                filter_parts.append(f"seed {query.paint_seed}")
            if query.min_sticker_count is not None:
                filter_parts.append(f"stickers >= {query.min_sticker_count}")
            if query.max_sticker_count is not None:
                filter_parts.append(f"stickers <= {query.max_sticker_count}")
            filter_parts.append(f"stickers: {sticker_mode}")
            run_plan_parts = [f"sort: {', '.join(query.sort_by)}"]
            run_plan_parts.append("descending" if query.descending else "ascending")
            run_plan_parts.append(f"limit {query.limit}")
            self.query_tree.insert(
                "",
                "end",
                iid=str(index),
                tags=("altrow",) if index % 2 else (),
                values=(
                    f"{query.base_name} ({query.wear})",
                    " | ".join(filter_parts),
                    " | ".join(run_plan_parts),
                ),
            )
        self.query_tree.tag_configure("altrow", background=TABLE_ALT_ROW)
        if not self.query_items:
            self.queue_summary_var.set("No searches queued yet. Add one or more query rows above to build a batch.")
            return
        wear_count = len({query.wear for query in self.query_items})
        self.queue_summary_var.set(
            f"{len(self.query_items)} queued search{'es' if len(self.query_items) != 1 else ''} across "
            f"{wear_count} wear selection{'s' if wear_count != 1 else ''}. Select rows here to run only part of the batch."
        )

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

    def _start_run(self, *, selected_only: bool) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Already running", "A batch is already running right now.", parent=self.root)
            return

        if selected_only:
            selected_indices = [int(item_id) for item_id in self.query_tree.selection()]
            queries_to_run = [self.query_items[index] for index in selected_indices]
        else:
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
        self.status_var.set(f"Running {len(queries_to_run)} queued quer{'y' if len(queries_to_run) == 1 else 'ies'}...")
        self._append_log(self.status_var.get())

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
        tab = ttk.Frame(self.results_notebook, padding=12, style="Card.TFrame")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

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

        stat_strip = ttk.Frame(scroll_content, style="InnerCard.TFrame", padding=10)
        stat_strip.grid(row=1, column=0, sticky="ew", pady=(0, 10))
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
        table_frame.grid(row=2, column=0, sticky="nsew")
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

        tab_title = result.query.base_name[:24]
        if self.results_placeholder.winfo_ismapped():
            self.results_placeholder.grid_remove()
        self.results_notebook.add(tab, text=tab_title)
        self.results_notebook.select(tab)
        self.results_summary_var.set(
            f"{len(self.results_notebook.tabs())} result tab{'s' if len(self.results_notebook.tabs()) != 1 else ''} open. "
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
