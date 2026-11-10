"""Network layer of the bank client.

Public methods return built-in Python values (str, int, list, tuple, None), except
history types which use the ``TxType`` enum so the GUI does not deal with raw
type strings. On a rejected or unexpected server reply they raise ``RequestFailed``
with a user-facing message. Transport failures raise ``ConnectionError`` / ``OSError``.
"""
from __future__ import annotations

import socket
from enum import Enum
from typing import Callable, List, Optional, Tuple, Union

import client_protocol_structs as protocol


class TxType(Enum):
    """Finite set of history entry types the GUI understands.

    ``req_history`` returns these instead of free-form strings. The GUI turns
    them into display text; wire values from the server are mapped here.
    """

    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    CHARGE = "CHARGE"
    LOAN = "LOAN"
    LOAN_REPAYMENT = "LOAN_REPAYMENT"
    OVERDRAFT_INTEREST = "OVERDRAFT_INTEREST"

# --------------------------Error Classes --------------------------
# ---------Raise these for the GUI to react appropriately.----------
ProtocolError = protocol.ProtocolError
RequestFailed = protocol.RequestFailed


### Do not remove any of the existing functions or change their signatures. ###
### You can add new functions and classes if needed. ###
class Connection:
    """One TCP connection to the bank server.

    Not thread-safe: call from a single thread (the GUI network worker, or a shell).
    """

    def __init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)


    @property
    def connected(self) -> bool:
        """Returns True if a TCP connection to the server is currently open."""
        # TODO implement this
        pass


    def connect(self, host: str, port: int) -> None:
        """Open a TCP connection to the bank server.

        Args:
            host: Server hostname or IP (e.g. ``\"127.0.0.1\"``).
            port: Server TCP port (e.g. ``5050``).
            timeout: Seconds to wait for the TCP handshake.

        Returns:
            None.

        Raises:
            OSError / ConnectionError: if the server cannot be reached.
        """
        # TODO implement this
        print("trying to connect")
        self.socket.connect((host, port))


    def close(self) -> None:
        """Close the TCP connection if one is open. Safe to call more than once.

        Returns:
            None.
        """
        # TODO implement this
        pass


    def req_register(self, username: str, password: str) -> str:
        """Register a new account.

        Args:
            user: Account name (3-20 letters/digits/``_``). Need not be unique.
            password: Password (at least 4 characters).

        Returns:
            The new unique user id (token), a 10-character ``A-Z0-9`` string.

        Raises:
            RequestFailed: registration rejected (bad username/password, …).
            ConnectionError: connection lost.
        """
        try :
            status, data = self._send_request(
                protocol.build_register_user_payload(username, password)
            )
        except ProtocolError as e:
            raise RequestFailed(str(e))
        if not isinstance(data, dict) or not isinstance(data.get("userid"), str):
            raise RequestFailed("registration response is missing a string userid")
        return data["userid"]


    def _send_request(self, message: bytes) -> tuple[protocol.Status, object]:
        try:
            self.socket.sendall(message)
        except OSError as error:
            raise ConnectionError(f"failed to send request: {error}") from error
        return protocol.receive_message(self.socket)


    def req_login(self, user: str, password: str, token: str) -> None:
        """Log in to an existing account on this connection.

        Args:
            user: Account name used at registration.
            password: Account password.
            token: User id (account id) issued at registration.

        Returns:
            None on success.

        Raises:
            RequestFailed: wrong credentials / unknown user id.
            ConnectionError: connection lost.
        """
        # TODO implement this
        pass


    def req_logout(self) -> None:
        """Log out and close the connection.

        Returns:
            None.
        """
        # TODO implement this
        pass


    def req_get_balance(self) -> str:
        """Fetch the logged-in account's balance.

        Returns:
            Balance string with two decimals, e.g. ``\"500.00\"`` or ``\"-12.50\"``.

        Raises:
            RequestFailed: not logged in or server error.
            ConnectionError: connection lost.
        """
        # TODO implement this
        return "0.00"


    def req_deposit(self, amount: str) -> str:
        """Deposit cash into the logged-in account.

        Args:
            amount: Positive decimal string, at most 2 fractional digits (e.g. ``\"99.90\"``).

        Returns:
            New balance string (two decimals).

        Raises:
            RequestFailed: invalid amount or not logged in.
            ConnectionError: connection lost.
        """
        # TODO implement this
        return "0.00"


    def req_withdraw(self, amount: str) -> str:
        """Withdraw cash from the logged-in account (may go negative).

        Args:
            amount: Positive decimal string, at most 2 fractional digits.

        Returns:
            New balance string (two decimals).

        Raises:
            RequestFailed: invalid amount or not logged in.
            ConnectionError: connection lost.
        """
        # TODO implement this
        return "0.00"


    def req_transfer(self, target: str, amount: str) -> str:
        """Transfer money to another account.

        Args:
            target: Recipient user id (token).
            amount: Positive decimal string, at most 2 fractional digits.

        Returns:
            New balance of the sender (two decimals).

        Raises:
            RequestFailed: bad amount, unknown target, self-transfer, …
            ConnectionError: connection lost.
        """
        # TODO implement this
        return "0.00"


    def req_schedule_so(self, target: str, amount: str, count: str) -> int:
        """Create a monthly standing order (first payment today).

        Args:
            target: Payee user id (token).
            amount: Amount per payment (positive decimal string).
            count: Number of payments as a digit string; ``\"0\"`` means until cancelled.

        Returns:
            The new standing-order id (positive int).

        Raises:
            RequestFailed: validation error or unknown target.
            ConnectionError: connection lost.
        """
        # TODO implement this
        return 1


    def req_get_so_list(self) -> List[Tuple[int, str, str, str, int, Optional[int], str]]:
        """List active standing orders paid by the logged-in account.

        Returns:
            A list of tuples, one per standing order, in any order::

                (so_id, counterparty_token, counterparty_name,
                 amount, executed, remaining, next_run)

            * ``so_id`` (int)
            * ``counterparty_token`` (str) — payee user id
            * ``counterparty_name`` (str) — payee account name
            * ``amount`` (str) — per-payment amount, two decimals
            * ``executed`` (int) — how many payments have run
            * ``remaining`` (int | None) — payments left, or ``None`` if until cancelled
            * ``next_run`` (str) — next payment date ``YYYY-MM-DD``

        Raises:
            RequestFailed: not logged in or server error.
            ConnectionError: connection lost.
        """
        # TODO implement this
        return [(1, "EXAMPLE_ID1", "EXAMPLE_NAME1", "0.00", 1, 2, "2026-11-12"),
                (2, "EXAMPLE_ID2", "EXAMPLE_NAME2", "0.00", 4, None, "2026-11-20")]


    def req_cancel_so(self, so_id: Union[str, int]) -> None:
        """Cancel one of the logged-in account's standing orders.

        Args:
            so_id: Standing-order id (int or digit string).

        Returns:
            None on success.

        Raises:
            RequestFailed: unknown standing order or not owned by this account.
            ConnectionError: connection lost.
        """
        # TODO implement this
        pass


    def req_loan(self, amount: str) -> Tuple[int, str]:
        """Take a loan (principal credited now; auto-repay after 30 bank days + 5%).

        Args:
            amount: Principal as a positive decimal string.

        Returns:
            ``(loan_id, new_balance)`` where ``loan_id`` is int and ``new_balance``
            is a two-decimal string.

        Raises:
            RequestFailed: invalid amount or not logged in.
            ConnectionError: connection lost.
        """
        # TODO implement this
        return (1, "0.00")


    def req_get_loans(self) -> List[Tuple[int, str, str, str, str]]:
        """List unpaid loans for the logged-in account.

        Returns:
            A list of tuples, one per unpaid loan, in any order::

                (loan_id, principal, repay_amount, taken_on, due_on)

            * ``loan_id`` (int)
            * ``principal`` (str) — two decimals
            * ``repay_amount`` (str) — principal * 1.05, two decimals
            * ``taken_on`` (str) — ``YYYY-MM-DD``
            * ``due_on`` (str) — ``YYYY-MM-DD``

        Raises:
            RequestFailed: not logged in or server error.
            ConnectionError: connection lost.
        """
        return [(1, "100.00", "105.00", "2026-11-12", "2026-11-12"),
                (2, "200.00", "210.00", "2026-11-20", "2026-11-20")]


    def req_history(self, from_ts: Optional[float] = None,
                    to_ts: Optional[float] = None) -> List[Tuple[str, TxType, str, str, str, str, str]]:
        """Fetch account history (oldest first). The GUI reverses for display.

        Args:
            from_ts: Optional inclusive lower bound (Unix seconds). The GUI passes
                neither bound (full history).
            to_ts: Optional inclusive upper bound (Unix seconds).

        Returns:
            A list of tuples, **oldest first**::

                (time, type, counterparty, counterparty_name, amount, balance, note)

            * ``time`` (str) — e.g. ``\"2026-10-30 14:13:20\"``
            * ``type`` (``TxType``) — e.g. ``TxType.DEPOSIT``, ``TxType.TRANSFER_IN``, …
            * ``counterparty`` (str) — other party token, ``CASH``, or ``BANK``
            * ``counterparty_name`` (str) — display name (may equal counterparty)
            * ``amount`` (str) — signed two-decimal amount for this entry
            * ``balance`` (str) — balance after this entry, two decimals
            * ``note`` (str) — free text (may be empty)

        Raises:
            RequestFailed: not logged in or bad timestamps.
            ConnectionError: connection lost.
        """
        return [("2026-11-12 14:15:20", TxType.TRANSFER_OUT, "EXAMPLE_ID2", "EXAMPLE_NAME2", "100.00", "100.00", ""),
                ("2026-11-12 14:13:20", TxType.DEPOSIT, "EXAMPLE_ID1", "EXAMPLE_NAME1", "200.00", "200.00", "")]
