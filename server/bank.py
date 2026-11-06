"""In-memory bank: accounts, authentication, balances, transfers, history,
calendar-monthly standing orders and loans.

Designed for a single-threaded select()-based server: no locks. All timestamps
come from the bank's own ``SimTime`` clock. Due standing orders and loan
repayments are processed when the main loop calls ``run_due()`` (and after
the operator advances the bank date via ``on_console_line``).
"""
from __future__ import annotations

import logging
from datetime import date

from server_utils import SimTime

log = logging.getLogger("bank")

class Bank:
    def __init__(self, start_date: date):
        self.clock = SimTime(start_date=start_date)
    # TODO implement this class
    #      You can add new functions and classes if needed