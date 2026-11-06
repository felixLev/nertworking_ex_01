##### DO NOT MODIFY THIS FILE #####

"""Desktop GUI for the socket bank (tkinter, no external packages).

All communication goes through a Connection object (see connection.py) using the
protocol in PROTOCOL.md.

Connection is a plain single-threaded socket client. This GUI keeps the Tk event
loop on the main thread and runs every Connection call on one dedicated network
worker thread (a FIFO job queue), so requests never overlap and connection.py
needs no locks.

Launch via client.py — do not run this file directly.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import tkinter as tk
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, simpledialog, ttk
from typing import Callable, Optional, Tuple

from connection import Connection, ProtocolError, RequestFailed, TxType

# Sentinel posted to the network job queue to ask the worker to exit.
_NET_STOP = object()

POLL_MS = 2000
TOKENS_FILE = os.path.join(os.path.expanduser("~"), ".sockets_bank_tokens.json")
CURRENCY = "₪"  # shekel sign


def describe_party(token: str, name: str) -> str:
    """'bob (Q7ZK2M9XAB)' for customers; CASH/BANK as is."""
    return f"{name} ({token})" if name and name != token else token


_TX_TYPE_LABELS = {
    TxType.DEPOSIT: "Deposit",
    TxType.WITHDRAWAL: "Withdrawal",
    TxType.TRANSFER_IN: "Transfer in",
    TxType.TRANSFER_OUT: "Transfer out",
    TxType.CHARGE: "Standing order",
    TxType.LOAN: "Loan",
    TxType.LOAN_REPAYMENT: "Loan repayment",
    TxType.OVERDRAFT_INTEREST: "Overdraft interest",
}


def format_tx_type(tx_type: TxType) -> str:
    """Turn a ``TxType`` from Connection into text for the history table."""
    return _TX_TYPE_LABELS.get(tx_type, tx_type.value)


def load_tokens() -> dict:
    try:
        with open(TOKENS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_token(key: str, token: str) -> None:
    tokens = load_tokens()
    tokens[key] = token
    try:
        with open(TOKENS_FILE, "w", encoding="utf-8") as fh:
            json.dump(tokens, fh, indent=2)
    except OSError:
        pass  # remembering tokens is only a convenience


def signed(amount: str) -> Decimal:
    try:
        return Decimal(amount)
    except InvalidOperation:
        return Decimal(0)


class BankApp(tk.Tk):
    def __init__(self, connection: Connection, host: str = "127.0.0.1", port: int = 5050):
        super().__init__()
        self.title("Sockets Bank")
        self.geometry("880x820")
        self.minsize(780, 680)

        self.connection = connection
        self.connected_to: Optional[Tuple[str, int]] = None
        self.user: Optional[str] = None
        self.account_token = ""
        self.last_balance: Optional[Decimal] = None
        self.poll_busy = False
        # GUI-thread callbacks produced by the network worker.
        self.results: "queue.Queue[Tuple[Callable, tuple]]" = queue.Queue()
        # Single network worker: Connection is not thread-safe, so all socket I/O
        # is serialized through this FIFO queue.
        self._net_jobs: queue.Queue = queue.Queue()
        self._net_thread = threading.Thread(target=self._net_loop, name="network", daemon=True)
        self._net_thread.start()

        self.host_var = tk.StringVar(value=host)
        self.port_var = tk.StringVar(value=str(port))
        self.login_token_var = tk.StringVar()
        self.login_password_var = tk.StringVar()
        self.register_name_var = tk.StringVar()
        self.register_password_var = tk.StringVar()
        self.auto_refresh_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Not connected")

        self._build_layout()
        self.show_login()
        self.after(50, self._drain_results)
        self.after(POLL_MS, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # =====================================================================
    # Network worker: one thread, FIFO jobs — Connection stays lock-free
    # =====================================================================
    def run_async(self, task: Callable, on_done: Callable,
                  on_error: Optional[Callable[[str], None]] = None,
                  on_reject: Optional[Callable[[str], None]] = None) -> None:
        """Queue ``task`` for the network thread; callbacks run on the GUI thread.

        ``on_done(result)`` — successful return value from Connection.
        ``on_reject(message)`` — server rejected the request (``RequestFailed``).
        ``on_error(message)`` — transport / protocol failure.
        """
        self._net_jobs.put((
            task,
            on_done,
            on_error or self._connection_lost,
            self._request_rejected if on_reject is None else on_reject,
        ))

    def _net_loop(self) -> None:
        while True:
            item = self._net_jobs.get()
            if item is _NET_STOP:
                break
            task, on_done, on_error, on_reject = item
            try:
                result = task()
            except RequestFailed as err:
                self.results.put((on_reject, (str(err),)))
            except ProtocolError as err:
                self.results.put((on_error, (f"Protocol error: {err}",)))
            except (ConnectionError, OSError) as err:
                self.results.put((on_error, (str(err),)))
            else:
                self.results.put((on_done, (result,)))
        try:
            self.connection.close()
        except OSError:
            pass

    def _drain_results(self) -> None:
        self.after(50, self._drain_results)
        while True:
            try:
                callback, args = self.results.get_nowait()
            except queue.Empty:
                return
            try:
                callback(*args)
            except (IndexError, KeyError, TypeError, ValueError, ProtocolError) as err:
                # Malformed reply (wrong number of fields, bad JSON shape, ...).
                self.set_status(f"Unexpected reply from server: {err!r}")

    def _connection_lost(self, message: str) -> None:
        self.poll_busy = False
        if self.user is None:
            return
        self.user = None
        self.connected_to = None
        self.run_async(self.connection.close, lambda *_: None,
                       on_error=lambda *_: None, on_reject=lambda *_: None)
        self.show_login()
        self.set_status(f"Disconnected: {message}")
        messagebox.showerror("Connection lost", f"Lost the connection to the server.\n\n{message}")

    def _connect_failed(self, message: str) -> None:
        self.connected_to = None
        self.run_async(self.connection.close, lambda *_: None,
                       on_error=lambda *_: None, on_reject=lambda *_: None)
        self.set_status(f"Cannot reach server: {message}")
        messagebox.showerror("Connection failed",
                             f"Could not talk to {self.host_var.get()}:{self.port_var.get()}\n\n{message}")

    def _request_rejected(self, message: str) -> None:
        self.poll_busy = False
        self.set_status(message)
        messagebox.showerror("Request rejected", message)

    def _ensure_connected(self, address: Tuple[str, int]) -> None:
        """Runs on the network thread."""
        if not self.connection.connected or self.connected_to != address:
            self.connection.connect(*address)
            self.connected_to = address

    # =====================================================================
    # Layout
    # =====================================================================
    def _build_layout(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Balance.TLabel", font=("Segoe UI", 24, "bold"))
        style.configure("Muted.TLabel", foreground="#666666")

        self.container = ttk.Frame(self)
        self.container.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))
        self.login_frame = self._build_login(self.container)
        self.main_frame = self._build_main(self.container)

        status = ttk.Label(self, textvariable=self.status_var, anchor="w", relief=tk.SUNKEN, padding=(6, 2))
        status.pack(fill=tk.X, side=tk.BOTTOM, padx=8, pady=6)

    @staticmethod
    def _field(parent, row: int, label: str, var: tk.StringVar, width: int = 24, show: str = "") -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        entry = ttk.Entry(parent, textvariable=var, width=width, show=show)
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        return entry

    def _build_login(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent)
        card = ttk.Frame(frame, padding=24)
        card.place(relx=0.5, rely=0.45, anchor="center")

        ttk.Label(card, text="Sockets Bank", style="Title.TLabel").grid(row=0, column=0, columnspan=2, pady=(0, 4))
        ttk.Label(card, text="Connect to the bank, then log in or register a new account",
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=2, pady=(0, 14))

        server = ttk.Frame(card)
        server.grid(row=2, column=0, columnspan=2, sticky="ew")
        self._field(server, 0, "Server host", self.host_var)
        self._field(server, 1, "Port", self.port_var, width=8)

        ttk.Separator(card).grid(row=3, column=0, columnspan=2, sticky="ew", pady=12)

        columns = ttk.Frame(card)
        columns.grid(row=4, column=0, columnspan=2, sticky="nsew")
        columns.columnconfigure(0, weight=1)
        columns.columnconfigure(1, weight=1)

        login_col = ttk.LabelFrame(columns, text="Log in", padding=12)
        login_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._field(login_col, 0, "User id", self.login_token_var)
        self._field(login_col, 1, "Password", self.login_password_var, show="*")
        ttk.Button(login_col, text="Log in", command=self.login).grid(
            row=2, column=1, sticky="e", pady=(10, 0))

        register_col = ttk.LabelFrame(columns, text="Register", padding=12)
        register_col.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self._field(register_col, 0, "Account name", self.register_name_var)
        self._field(register_col, 1, "Password", self.register_password_var, show="*")
        ttk.Label(register_col, text="Account names may repeat.\nYour unique user id is issued on register.",
                  style="Muted.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(register_col, text="Register new account", command=self.register).grid(
            row=3, column=1, sticky="e", pady=(10, 0))

        self.bind("<Return>", lambda _e: self.login() if self.user is None else None)
        return frame

    def _build_main(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent)

        header = ttk.Frame(frame, padding=(4, 4, 4, 10))
        header.pack(fill=tk.X)
        left = ttk.Frame(header)
        left.pack(side=tk.LEFT)
        self.welcome_label = ttk.Label(left, text="", style="Title.TLabel")
        self.welcome_label.pack(anchor="w")
        token_row = ttk.Frame(left)
        token_row.pack(anchor="w")
        self.account_token_label = ttk.Label(token_row, text="", style="Muted.TLabel")
        self.account_token_label.pack(side=tk.LEFT)
        ttk.Button(token_row, text="Copy", width=6, command=self._copy_account_token).pack(side=tk.LEFT, padx=6)
        self.balance_label = ttk.Label(left, text="--", style="Balance.TLabel")
        self.balance_label.pack(anchor="w")
        self.overdrawn_label = ttk.Label(left, text="", foreground="#b3261e")
        self.overdrawn_label.pack(anchor="w")

        right = ttk.Frame(header)
        right.pack(side=tk.RIGHT, anchor="n")
        ttk.Button(right, text="Log out", command=self.logout).pack(side=tk.RIGHT, padx=4)
        ttk.Button(right, text="Refresh", command=self.refresh_all).pack(side=tk.RIGHT, padx=4)
        ttk.Checkbutton(right, text=f"Auto-refresh ({POLL_MS // 1000}s)",
                        variable=self.auto_refresh_var).pack(side=tk.RIGHT, padx=8)

        self.notebook = ttk.Notebook(frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.history_tab = self._build_history_tab(self.notebook)
        self.cash_tab = self._build_cash_tab(self.notebook)
        self.transfer_tab = self._build_transfer_tab(self.notebook)
        self.so_tab = self._build_so_tab(self.notebook)
        self.loans_tab = self._build_loans_tab(self.notebook)
        self.notebook.add(self.history_tab, text="  History  ")
        self.notebook.add(self.cash_tab, text="  Deposit / Withdrawal  ")
        self.notebook.add(self.transfer_tab, text="  Transfer  ")
        self.notebook.add(self.so_tab, text="  Standing orders  ")
        self.notebook.add(self.loans_tab, text="  Loans  ")
        self.notebook.bind("<<NotebookTabChanged>>", lambda _e: self._refresh_current_tab())
        return frame

    def _build_history_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=16)
        ttk.Label(tab, text="All transactions (newest first)",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        columns = ("time", "type", "counterparty", "amount", "balance", "note")
        headings = ("Date / time", "Type", "Source / target", "Amount", "Balance after", "Details")
        widths = (150, 110, 190, 100, 110, 260)
        self.history_tree = self._make_tree(tab, columns, headings, widths, height=14)
        self.history_tree.tag_configure("in", foreground="#137333")
        self.history_tree.tag_configure("out", foreground="#b3261e")
        self.history_summary = ttk.Label(tab, text="", style="Muted.TLabel")
        self.history_summary.pack(anchor="w", pady=(6, 0))
        return tab

    def _build_cash_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=16)
        self.cash_amount_var = tk.StringVar()
        box = ttk.LabelFrame(tab, text="Cash deposit / withdrawal", padding=12)
        box.pack(anchor="nw")
        self._field(box, 0, "Amount", self.cash_amount_var)
        buttons = ttk.Frame(box)
        buttons.grid(row=1, column=1, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Deposit", command=self.deposit).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Withdraw", command=self.withdraw).pack(side=tk.LEFT, padx=(6, 0))
        self.cash_result = ttk.Label(tab, text="", font=("Segoe UI", 11))
        self.cash_result.pack(anchor="w", pady=16)
        return tab

    def _build_transfer_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=16)
        self.transfer_target_var = tk.StringVar()
        self.transfer_amount_var = tk.StringVar()
        box = ttk.LabelFrame(tab, text="Transfer money to another customer", padding=12)
        box.pack(anchor="nw")
        self._field(box, 0, "To (user id)", self.transfer_target_var)
        self._field(box, 1, "Amount", self.transfer_amount_var)
        ttk.Button(box, text="Send transfer", command=self.transfer).grid(
            row=2, column=1, sticky="e", pady=(8, 0))
        self.transfer_result = ttk.Label(tab, text="", font=("Segoe UI", 11))
        self.transfer_result.pack(anchor="w", pady=16)
        return tab

    def _build_so_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=16)
        self.order_target_var = tk.StringVar()
        self.order_amount_var = tk.StringVar()
        self.order_count_var = tk.StringVar(value="3")

        forms = ttk.Frame(tab)
        forms.pack(fill=tk.X)
        box = ttk.LabelFrame(forms, text="Standing order / installments (monthly)", padding=12)
        box.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 16))
        self._field(box, 0, "Pay to (user id)", self.order_target_var, width=14)
        self._field(box, 1, "Amount per payment", self.order_amount_var, width=14)
        self._field(box, 2, "Number of payments", self.order_count_var, width=14)
        ttk.Label(box, text="leave blank = until cancelled\nFirst payment today, then the same day each month.",
                  style="Muted.TLabel").grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(box, text="Create standing order",
                   command=self.schedule).grid(row=4, column=1, sticky="e", pady=(8, 0))
        ttk.Label(forms, style="Muted.TLabel", justify="left", text=(
            "Paying a salary?\n"
            "Log in as the employer and create a standing order\n"
            "to the employee's user id. The employee sees each\n"
            "payment arrive as TRANSFER_IN in the account history.")).pack(side=tk.LEFT, anchor="n", pady=(8, 0))

        ttk.Label(tab, text="Your active standing orders (they run on the server, even after you log out)",
                  style="Muted.TLabel").pack(anchor="w", pady=(16, 4))
        columns = ("id", "counterparty", "amount", "executed", "remaining", "next_run")
        headings = ("ID", "Pay to", "Amount", "Done", "Remaining", "Next payment")
        widths = (50, 240, 100, 60, 110, 120)
        self.so_tree = self._make_tree(tab, columns, headings, widths, height=7)

        buttons = ttk.Frame(tab)
        buttons.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(buttons, text="Cancel selected standing order", command=self.cancel_standing_order).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Refresh", command=self.refresh_so_list).pack(side=tk.LEFT, padx=6)
        return tab

    def _build_loans_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=16)
        self.loan_amount_var = tk.StringVar()
        box = ttk.LabelFrame(tab, text="Take a loan", padding=12)
        box.pack(anchor="nw", fill=tk.X)
        self._field(box, 0, "Amount", self.loan_amount_var)
        ttk.Label(box, text="Repaid automatically after 30 bank days with 5% interest.",
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(box, text="Take loan", command=self.take_loan).grid(
            row=2, column=1, sticky="e", pady=(8, 0))
        self.loan_result = ttk.Label(tab, text="", font=("Segoe UI", 11))
        self.loan_result.pack(anchor="w", pady=(12, 0))

        ttk.Label(tab, text="Unpaid loans", style="Muted.TLabel").pack(anchor="w", pady=(16, 4))
        columns = ("id", "principal", "repay_amount", "taken_on", "due_on")
        headings = ("ID", "Principal", "Repay amount", "Taken on", "Due on")
        widths = (50, 120, 120, 120, 120)
        self.loans_tree = self._make_tree(tab, columns, headings, widths, height=8)
        buttons = ttk.Frame(tab)
        buttons.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(buttons, text="Refresh", command=self.refresh_loans).pack(side=tk.LEFT)
        return tab

    @staticmethod
    def _make_tree(parent, columns, headings, widths, height: int, pady=(0, 0)) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True, pady=pady)
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=height, selectmode="browse")
        for column, heading, width in zip(columns, headings, widths):
            tree.heading(column, text=heading, anchor="w")
            tree.column(column, width=width, anchor="w", stretch=column in ("note", "next_run"))
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        return tree

    # =====================================================================
    # View switching & small helpers
    # =====================================================================
    def show_login(self) -> None:
        self.main_frame.pack_forget()
        self.login_frame.pack(fill=tk.BOTH, expand=True)
        self.title("Sockets Bank")

    def show_main(self) -> None:
        self.login_frame.pack_forget()
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        self.welcome_label.config(text=f"Hello, {self.user}")
        self.account_token_label.config(text=f"Your user id (account ID): {self.account_token}")
        self.title(f"Sockets Bank - {self.user} ({self.account_token})")

    def set_status(self, text: str) -> None:
        self.status_var.set(f"[{time.strftime('%H:%M:%S')}] {text}")

    def _server_address(self) -> Optional[Tuple[str, int]]:
        try:
            return self.host_var.get().strip(), int(self.port_var.get())
        except ValueError:
            messagebox.showwarning("Invalid port", "Port must be a number.")
            return None

    def _server_key_prefix(self) -> str:
        return f"{self.host_var.get().strip()}:{self.port_var.get().strip()}"

    def _name_to_token_key(self, name: str) -> str:
        return f"{self._server_key_prefix()}/name/{name}"

    def _token_to_name_key(self, token: str) -> str:
        return f"{self._server_key_prefix()}/id/{token}"

    def _remember_account(self, name: str, token: str) -> None:
        """Remember both directions so login by user id can recover the account name."""
        save_token(self._name_to_token_key(name), token)
        save_token(self._token_to_name_key(token), name)

    def _account_name_for_token(self, token: str) -> Optional[str]:
        name = load_tokens().get(self._token_to_name_key(token), "")
        return name or None

    def _report_success(self, success_text: str, label: Optional[ttk.Label] = None) -> None:
        self.set_status(success_text)
        if label is not None:
            label.config(text=success_text, foreground="#137333")

    @staticmethod
    def _require(*values: str) -> bool:
        if all(value.strip() for value in values):
            return True
        messagebox.showwarning("Missing input", "Please fill in all fields.")
        return False

    # =====================================================================
    # Authentication
    # =====================================================================
    def login(self) -> None:
        address = self._server_address()
        token = self.login_token_var.get().strip()
        password = self.login_password_var.get().strip()
        if address is None or not self._require(token, password):
            return

        # Protocol LOGIN still needs the account name; recover it from a prior register/login
        # on this machine, or ask once if it is not remembered yet.
        user = self._account_name_for_token(token)
        if user is None:
            user = tk.simpledialog.askstring(
                "Account name",
                "This user id is not remembered on this computer.\n"
                "Enter the account name used when you registered:",
                parent=self,
            )
            if not user or not user.strip():
                return
            user = user.strip()

        def task():
            self._ensure_connected(address)
            self.connection.req_login(user, password, token)

        def done(_result: None):
            self.user = user
            self.account_token = token
            self.last_balance = None
            self._remember_account(user, token)
            self.login_password_var.set("")
            self.show_main()
            self.set_status(f"Logged in as {user}")
            self.refresh_all()

        self.set_status(f"Connecting to {address[0]}:{address[1]} ...")
        self.run_async(task, done, on_error=self._connect_failed)

    def register(self) -> None:
        address = self._server_address()
        name = self.register_name_var.get().strip()
        password = self.register_password_var.get().strip()
        if address is None or not self._require(name, password):
            return

        def task():
            self._ensure_connected(address)
            return self.connection.req_register(name, password)

        def done(token: str):
            self._remember_account(name, token)
            self.register_password_var.set("")
            self.login_token_var.set(token)
            self.set_status(f"Account '{name}' created")
            self._show_registered_user_id(name, token)

        self.run_async(task, done, on_error=self._connect_failed)

    def _show_registered_user_id(self, name: str, token: str) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Account created")
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.grab_set()

        body = ttk.Frame(dialog, padding=20)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=f"Account '{name}' was created successfully.",
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="Your unique user id (write it down — you need it for every login):",
                  style="Muted.TLabel").pack(anchor="w", pady=(12, 6))

        id_row = ttk.Frame(body)
        id_row.pack(fill=tk.X, pady=(0, 12))
        entry = tk.Entry(id_row, font=("Consolas", 14), width=16, justify="center",
                         relief=tk.FLAT, readonlybackground="#f0f0f0")
        entry.insert(0, token)
        entry.configure(state="readonly")
        entry.pack(side=tk.LEFT, padx=(0, 8))

        def copy_id() -> None:
            self.clipboard_clear()
            self.clipboard_append(token)
            self.set_status("user id copied to clipboard")
            copied_label.config(text="Copied!")

        ttk.Button(id_row, text="Copy to clipboard", command=copy_id).pack(side=tk.LEFT)
        copied_label = ttk.Label(body, text="", foreground="#137333")
        copied_label.pack(anchor="w")

        ttk.Button(body, text="OK", command=dialog.destroy).pack(anchor="e", pady=(16, 0))
        dialog.bind("<Return>", lambda _e: dialog.destroy())
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dialog.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - dialog.winfo_height()) // 3
        dialog.geometry(f"+{x}+{y}")

    def _copy_account_token(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.account_token)
        self.set_status("user id copied - share it so others can transfer money to you")

    def logout(self) -> None:
        self.user = None  # stops polling and silences errors from in-flight requests
        self.connected_to = None
        self.show_login()
        self.set_status("Logged out")
        self.run_async(self.connection.req_logout, lambda _resp: None,
                       on_error=lambda _msg: None, on_reject=lambda _msg: None)

    def _on_close(self) -> None:
        self.user = None
        self._net_jobs.put(_NET_STOP)
        self._net_thread.join(timeout=1.5)
        self.destroy()

    # =====================================================================
    # Banking actions
    # =====================================================================
    def transfer(self) -> None:
        target, amount = self.transfer_target_var.get().strip(), self.transfer_amount_var.get().strip()
        if not self._require(target, amount):
            return

        def done(new_balance: str):
            self._report_success(
                f"Transferred {amount} to {target}. New balance: {new_balance}",
                self.transfer_result,
            )
            self.transfer_amount_var.set("")
            self.refresh_balance()

        self.run_async(lambda: self.connection.req_transfer(target, amount), done)

    def deposit(self) -> None:
        self._cash_operation(self.connection.req_deposit, "Deposited")

    def withdraw(self) -> None:
        self._cash_operation(self.connection.req_withdraw, "Withdrew")

    def _cash_operation(self, request: Callable[[str], str], verb: str) -> None:
        amount = self.cash_amount_var.get().strip()
        if not self._require(amount):
            return

        def done(new_balance: str):
            self._report_success(f"{verb} {amount}. New balance: {new_balance}", self.cash_result)
            self.cash_amount_var.set("")
            self.refresh_balance()

        self.run_async(lambda: request(amount), done)

    def schedule(self) -> None:
        target, amount = self.order_target_var.get().strip(), self.order_amount_var.get().strip()
        count = self.order_count_var.get().strip() or "0"  # blank = until cancelled
        if not self._require(target, amount):
            return

        def done(so_id: int):
            self._report_success(f"Standing order #{so_id} created")
            self.refresh_so_list()

        self.run_async(lambda: self.connection.req_schedule_so(target, amount, count), done)

    def take_loan(self) -> None:
        amount = self.loan_amount_var.get().strip()
        if not self._require(amount):
            return

        def done(result: Tuple[int, str]):
            loan_id, new_balance = result
            self._report_success(
                f"Loan #{loan_id} taken. New balance: {new_balance}",
                self.loan_result,
            )
            self.loan_amount_var.set("")
            self.refresh_balance()
            self.refresh_loans()

        self.run_async(lambda: self.connection.req_loan(amount), done)

    def cancel_standing_order(self) -> None:
        selected = self.so_tree.selection()
        if not selected:
            messagebox.showinfo("Cancel standing order", "Select a standing order in the table first.")
            return
        so_id = self.so_tree.set(selected[0], "id")

        def done(_result: None):
            self._report_success(f"Standing order #{so_id} cancelled")
            self.refresh_so_list()

        self.run_async(lambda: self.connection.req_cancel_so(so_id), done)

    # =====================================================================
    # Refreshing data (manual and automatic)
    # =====================================================================
    def refresh_all(self) -> None:
        self.refresh_balance()
        self._refresh_current_tab()

    def _refresh_current_tab(self) -> None:
        if self.user is None:
            return
        current = self.notebook.select()
        if current == str(self.so_tab):
            self.refresh_so_list()
        elif current == str(self.loans_tab):
            self.refresh_loans()
        elif current == str(self.history_tab):
            self.refresh_history()

    def refresh_balance(self) -> None:
        self.run_async(self.connection.req_get_balance, lambda resp: self._show_balance(resp, from_poll=False))

    def refresh_so_list(self) -> None:
        self.run_async(self.connection.req_get_so_list, self._show_so_list)

    def refresh_loans(self) -> None:
        self.run_async(self.connection.req_get_loans, self._show_loans)

    def refresh_history(self) -> None:
        self.run_async(self.connection.req_history, self._show_history)

    def _poll(self) -> None:
        self.after(POLL_MS, self._poll)
        if self.user is None or self.poll_busy or not self.auto_refresh_var.get():
            return
        current = self.notebook.select()

        def task():
            replies = {"balance": self.connection.req_get_balance()}
            if current == str(self.so_tab):
                replies["standing_orders"] = self.connection.req_get_so_list()
            if current == str(self.loans_tab):
                replies["loans"] = self.connection.req_get_loans()
            if current == str(self.history_tab):
                replies["history"] = self.connection.req_history()
            return replies

        def done(replies: dict):
            self.poll_busy = False
            if self.user is None:
                return
            self._show_balance(replies["balance"], from_poll=True)
            if "standing_orders" in replies:
                self._show_so_list(replies["standing_orders"])
            if "loans" in replies:
                self._show_loans(replies["loans"])
            if "history" in replies:
                self._show_history(replies["history"])

        self.poll_busy = True
        self.run_async(task, done)

    def _show_balance(self, balance: str, from_poll: bool) -> None:
        value = signed(balance)
        self.balance_label.config(text=f"{CURRENCY} {balance}",
                                  foreground="#b3261e" if value < 0 else "#137333")
        self.overdrawn_label.config(text="Account is overdrawn" if value < 0 else "")
        if from_poll and self.last_balance is not None and value != self.last_balance:
            change = value - self.last_balance
            self.set_status(f"Balance changed by {'+' if change > 0 else ''}{change} "
                            f"(scheduled payment / loan / incoming transfer)")
            if self.notebook.select() == str(self.history_tab):
                self.refresh_history()
            elif self.notebook.select() == str(self.loans_tab):
                self.refresh_loans()
        self.last_balance = value

    def _show_so_list(self, standing_orders: list) -> None:
        selected = self.so_tree.selection()
        selected_id = self.so_tree.set(selected[0], "id") if selected else None
        self.so_tree.delete(*self.so_tree.get_children())
        for so_id, token, name, amount, executed, remaining, next_run in sorted(
                standing_orders, key=lambda row: row[0]):
            remaining_text = "until cancelled" if remaining is None else remaining
            item = self.so_tree.insert("", tk.END, values=(
                so_id, describe_party(token, name), amount,
                executed, remaining_text, next_run))
            if str(so_id) == selected_id:
                self.so_tree.selection_set(item)

    def _show_loans(self, loans: list) -> None:
        self.loans_tree.delete(*self.loans_tree.get_children())
        for loan_id, principal, repay_amount, taken_on, due_on in sorted(loans, key=lambda row: row[0]):
            self.loans_tree.insert("", tk.END, values=(
                loan_id, principal, repay_amount, taken_on, due_on))

    def _show_history(self, transactions: list) -> None:
        # Connection returns oldest-first; show newest at the top.
        rows = list(reversed(transactions))
        self.history_tree.delete(*self.history_tree.get_children())
        total_in = total_out = Decimal(0)
        for time_s, tx_type, token, name, amount_s, balance_s, note in rows:
            amount = signed(amount_s)
            if amount >= 0:
                tag, total_in = "in", total_in + amount
            else:
                tag, total_out = "out", total_out + amount
            self.history_tree.insert("", tk.END, tags=(tag,), values=(
                time_s, format_tx_type(tx_type), describe_party(token, name),
                amount_s, balance_s, note))
        children = self.history_tree.get_children()
        if children:
            self.history_tree.see(children[0])
        self.history_summary.config(
            text=f"{len(rows)} transactions   |   money in: +{total_in:.2f}   |   money out: {total_out:.2f}")
