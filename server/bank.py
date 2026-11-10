"""In-memory bank: accounts, authentication, balances, transfers, history,
calendar-monthly standing orders and loans.

Designed for a single-threaded select()-based server: no locks. All timestamps
come from the bank's own ``SimTime`` clock. Due standing orders and loan
repayments are processed when the main loop calls ``run_due()`` (and after
the operator advances the bank date via ``on_console_line``).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Optional

from server_utils import SimTime

log = logging.getLogger("bank")

_AMOUNT_RE = re.compile(r"^[0-9]+(?:\.[0-9]{1,2})?$")


@dataclass
class Transaction:
    timestamp: float
    type: str
    counterparty: str
    counterparty_name: str
    amount_cents: int
    balance_cents: int
    note: str = ""


@dataclass
class StandingOrder:
    order_id: int
    target_id: str
    amount_cents: int
    remaining: Optional[int]
    executed: int
    next_run: date
    day_of_month: int
    active: bool = True


@dataclass
class Loan:
    loan_id: int
    principal_cents: int
    repay_cents: int
    taken_on: date
    due_on: date
    paid: bool = False


@dataclass
class Account:
    user_id: str
    username: str
    balance_cents: int = 0
    history: list[Transaction] = field(default_factory=list)
    standing_orders: dict[int, StandingOrder] = field(default_factory=dict)
    loans: dict[int, Loan] = field(default_factory=dict)


class Bank:
    """Single-threaded in-memory banking state driven by a simulated clock."""

    OVERDRAFT_RATE = Decimal("0.0005")

    def __init__(self, start_date: date):
        self.clock = SimTime(start_date=start_date)
        self.accounts: dict[str, Account] = {}
        self._next_order_id = 1
        self._next_loan_id = 1

    @staticmethod
    def parse_amount(amount: object) -> int:
        """Parse a positive, plain decimal amount into integer cents."""
        if not isinstance(amount, str) or not _AMOUNT_RE.fullmatch(amount):
            raise ValueError("Amount must be a positive number with at most two decimal places")
        with localcontext() as context:
            context.prec = max(context.prec, len(amount) + 2)
            value = Decimal(amount)
            if value <= 0:
                raise ValueError("Amount must be greater than zero")
            return int((value * 100).to_integral_exact())

    @staticmethod
    def format_amount(cents: int) -> str:
        sign = "-" if cents < 0 else ""
        absolute = abs(cents)
        return f"{sign}{absolute // 100}.{absolute % 100:02d}"

    def add_account(self, user_id: str, username: str) -> None:
        if user_id in self.accounts:
            raise ValueError("Account id already exists")
        self.accounts[user_id] = Account(user_id, username)

    def _account(self, user_id: str) -> Account:
        try:
            return self.accounts[user_id]
        except KeyError:
            raise ValueError("Unknown account") from None

    def _record(self, account: Account, kind: str, counterparty: str,
                counterparty_name: str, amount_cents: int, note: str = "") -> None:
        account.history.append(Transaction(
            self.clock.now(), kind, counterparty, counterparty_name,
            amount_cents, account.balance_cents, note,
        ))

    def get_balance(self, user_id: str) -> str:
        return self.format_amount(self._account(user_id).balance_cents)

    def get_history(self, user_id: str, from_ts: object = None,
                    to_ts: object = None) -> list[tuple[str, str, str, str, str, str, str]]:
        account = self._account(user_id)
        start = self._validate_timestamp(from_ts, "from_ts")
        end = self._validate_timestamp(to_ts, "to_ts")
        if start is not None and end is not None and start > end:
            raise ValueError("from_ts must not be later than to_ts")
        return [
            (
                self.clock.format(when=entry.timestamp), entry.type,
                entry.counterparty, entry.counterparty_name,
                self.format_amount(entry.amount_cents),
                self.format_amount(entry.balance_cents), entry.note,
            )
            for entry in account.history
            if (start is None or entry.timestamp >= start)
            and (end is None or entry.timestamp <= end)
        ]

    @staticmethod
    def _validate_timestamp(value: object, field_name: str) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field_name} must be a number")
        result = float(value)
        if result != result or result in (float("inf"), float("-inf")):
            raise ValueError(f"{field_name} must be finite")
        return result

    def deposit(self, user_id: str, amount: object) -> str:
        account = self._account(user_id)
        cents = self.parse_amount(amount)
        account.balance_cents += cents
        self._record(account, "DEPOSIT", "CASH", "CASH", cents)
        return self.format_amount(account.balance_cents)

    def withdraw(self, user_id: str, amount: object) -> str:
        account = self._account(user_id)
        cents = self.parse_amount(amount)
        account.balance_cents -= cents
        self._record(account, "WITHDRAWAL", "CASH", "CASH", -cents)
        return self.format_amount(account.balance_cents)

    def transfer(self, sender_id: str, target_id: str, amount: object) -> str:
        sender = self._account(sender_id)
        recipient = self._account(target_id)
        if sender_id == target_id:
            raise ValueError("Cannot transfer money to the same account")
        cents = self.parse_amount(amount)
        sender.balance_cents -= cents
        recipient.balance_cents += cents
        self._record(sender, "TRANSFER_OUT", target_id, recipient.username, -cents)
        self._record(recipient, "TRANSFER_IN", sender_id, sender.username, cents)
        return self.format_amount(sender.balance_cents)

    def create_standing_order(self, sender_id: str, target_id: str,
                              amount: object, count: int) -> int:
        sender = self._account(sender_id)
        if sender_id == target_id:
            raise ValueError("Cannot create a standing order to the same account")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("Payment count must be zero or a positive integer")
        cents = self.parse_amount(amount)
        order_id = self._next_order_id
        self._next_order_id += 1
        today = self.clock.today()
        order = StandingOrder(
            order_id, target_id, cents, count or None, 0, today, today.day,
        )
        sender.standing_orders[order_id] = order
        self.run_due()
        return order_id

    def _execute_standing_order(self, sender: Account, recipient: Account,
                                order: StandingOrder) -> None:
        sender.balance_cents -= order.amount_cents
        recipient.balance_cents += order.amount_cents
        order.executed += 1
        if order.remaining is not None:
            order.remaining -= 1
        note = f"Standing order #{order.order_id}"
        self._record(sender, "TRANSFER_OUT", recipient.user_id, recipient.username,
                     -order.amount_cents, note)
        self._record(recipient, "TRANSFER_IN", sender.user_id, sender.username,
                     order.amount_cents, note)

    @staticmethod
    def _next_month(value: date, day_of_month: int) -> date:
        next_month = value.replace(day=1) + timedelta(days=32)
        first_day = next_month.replace(day=1)
        last_day = (first_day + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return first_day.replace(day=min(day_of_month, last_day.day))

    def get_standing_orders(self, user_id: str) -> list[tuple[int, str, str, str, int, Optional[int], str]]:
        account = self._account(user_id)
        return [
            (order.order_id, order.target_id, self._account(order.target_id).username,
             self.format_amount(order.amount_cents), order.executed, order.remaining,
             order.next_run.isoformat())
            for order in account.standing_orders.values() if order.active
        ]

    def cancel_standing_order(self, user_id: str, order_id: object) -> None:
        account = self._account(user_id)
        if isinstance(order_id, bool) or not isinstance(order_id, int):
            raise ValueError("Standing-order id must be an integer")
        order = account.standing_orders.get(order_id)
        if order is None or not order.active:
            raise ValueError("Standing order not found")
        order.active = False
        del account.standing_orders[order_id]

    def take_loan(self, user_id: str, amount: object) -> tuple[int, str]:
        account = self._account(user_id)
        if account.balance_cents < 0 or any(not loan.paid for loan in account.loans.values()):
            raise ValueError("Loans are available only to customers with no outstanding debt")
        principal = self.parse_amount(amount)
        with localcontext() as context:
            context.prec = max(context.prec, len(str(principal)) + 3)
            repay = int((Decimal(principal) * Decimal("1.05")).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP))
        loan_id = self._next_loan_id
        self._next_loan_id += 1
        taken_on = self.clock.today()
        account.loans[loan_id] = Loan(
            loan_id, principal, repay, taken_on, taken_on + timedelta(days=30),
        )
        account.balance_cents += principal
        self._record(account, "LOAN", "BANK", "BANK", principal,
                     f"Loan #{loan_id}")
        return loan_id, self.format_amount(account.balance_cents)

    def get_loans(self, user_id: str) -> list[tuple[int, str, str, str, str]]:
        account = self._account(user_id)
        return [
            (loan.loan_id, self.format_amount(loan.principal_cents),
             self.format_amount(loan.repay_cents), loan.taken_on.isoformat(),
             loan.due_on.isoformat())
            for loan in account.loans.values() if not loan.paid
        ]

    def charge_overdraft_interest(self) -> None:
        for account in self.accounts.values():
            if account.balance_cents >= 0:
                continue
            with localcontext() as context:
                context.prec = max(context.prec, len(str(-account.balance_cents)) + 6)
                interest = int((Decimal(-account.balance_cents) * self.OVERDRAFT_RATE)
                               .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            if interest == 0:
                continue
            account.balance_cents -= interest
            self._record(account, "OVERDRAFT_INTEREST", "BANK", "BANK", -interest,
                         "Daily overdraft interest (0.05%)")

    def run_due(self) -> None:
        today = self.clock.today()
        for account in self.accounts.values():
            for loan in account.loans.values():
                if not loan.paid and loan.due_on <= today:
                    account.balance_cents -= loan.repay_cents
                    loan.paid = True
                    self._record(account, "LOAN_REPAYMENT", "BANK", "BANK",
                                 -loan.repay_cents, f"Loan #{loan.loan_id} repayment")
            for order in list(account.standing_orders.values()):
                recipient = self._account(order.target_id)
                while order.active and order.next_run <= today:
                    self._execute_standing_order(account, recipient, order)
                    if order.remaining == 0:
                        order.active = False
                        account.standing_orders.pop(order.order_id, None)
                    else:
                        order.next_run = self._next_month(
                            order.next_run, order.day_of_month)

    def advance_day(self) -> date:
        """Close the current bank day, charge overdraft interest, and process due items."""
        self.charge_overdraft_interest()
        new_date = self.clock.advance_day()
        self.run_due()
        return new_date

    def announce_date(self) -> None:
        """Print the current simulated date."""
        print(f"Current date is {self.clock.today()}")
