"""Network layer of the bank client.

Public methods return built-in Python values (str, int, list, tuple, None), except
history types which use the ``TxType`` enum so the GUI does not deal with raw
type strings. On a rejected or unexpected server reply they raise ``RequestFailed``
with a user-facing message. Transport failures raise ``ConnectionError`` / ``OSError``.
"""
from __future__ import annotations

import socket
from enum import Enum
from typing import List, Optional, Tuple, Union

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
        self.is_connected = False


    @property
    def connected(self) -> bool:
        """Returns True if a TCP connection to the server is currently open."""
        return self.is_connected


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
        self.close()
        new_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            new_socket.connect((host, port))
        except OSError:
            new_socket.close()
            raise
        self.socket = new_socket
        self.is_connected = True


    def close(self) -> None:
        """Close the TCP connection if one is open. Safe to call more than once.

        Returns:
            None.

        Raises:
            OSError: if closing the socket fails.
        """
        self.socket.close()
        self.is_connected = False


    def req_register(self, username: str, password: str) -> str:
        """Register a new account.

        Args:
            username: Account name (3-20 letters/digits/``_``). Need not be unique.
            password: Password (at least 4 characters).

        Returns:
            The new unique user id (token), a 10-character ``A-Z0-9`` string.

        Raises:
            RequestFailed: registration rejected (bad username/password, …).
            ConnectionError: connection lost.
        """
        data = self._send_action(
            protocol.RequestType.REGISTER_USER,
            {"username": username, "password": password},
        )
        if not isinstance(data.get("userid"), str):
            raise RequestFailed("registration response is missing a string userid")
        return data["userid"]


    def _send_request(self, message: bytes) -> dict:
        try:
            self.socket.sendall(message)
        except OSError as error:
            raise ConnectionError(f"failed to send request: {error}") from error
        try:
            _, data = protocol.receive_message(self.socket)
        except ProtocolError as error:
            raise RequestFailed(str(error)) from error
        if not isinstance(data, dict):
            raise RequestFailed("server response data must be an object")
        return data

    def _send_action(self, action: protocol.RequestType,
                     payload: dict[str, object]) -> dict:
        return self._send_request(protocol.build_message(action, payload))

    @staticmethod
    def _required_string(data: dict, key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str):
            raise RequestFailed(f"server response is missing a string {key}")
        return value

    @staticmethod
    def _required_list(data: dict, key: str) -> list:
        value = data.get(key)
        if not isinstance(value, list):
            raise RequestFailed(f"server response is missing the {key} list")
        return value

    @staticmethod
    def _require_success(data: dict, operation: str) -> None:
        status = data.get("status")
        if isinstance(status, bool) or not isinstance(status, int) or status != 1:
            raise RequestFailed(f"server returned an invalid {operation} response")


    def req_login(self, user: str, password: str, token: str) -> None:
        """Log in to an existing account on this connection.

        Args:
            user: Account name used at registration.
            password: Account password.
            token: User id (account id) issued at registration.

        Returns:
            None on success.

        Raises:
            RequestFailed: wrong credentials, unknown user id, or invalid server response.
            ConnectionError: connection lost.
        """
        data = self._send_action(protocol.RequestType.LOGIN, {
            "username": user,
            "password": password,
            "user_id": token,
        })
        self._require_success(data, "login")


    def req_logout(self) -> None:
        """Log out and close the connection.

        Returns:
            None.

        Raises:
            RequestFailed: logout rejected or server response invalid.
            ConnectionError: connection lost.
            OSError: closing the socket fails.
        """
        data = self._send_action(protocol.RequestType.LOGOUT, {})
        self._require_success(data, "logout")
        self.close()


    def req_get_balance(self) -> str:
        """Fetch the logged-in account's balance.

        Returns:
            Balance string with two decimals, e.g. ``\"500.00\"`` or ``\"-12.50\"``.

        Raises:
            RequestFailed: not logged in or server error.
            ConnectionError: connection lost.
        """
        data = self._send_action(protocol.RequestType.GET_BALANCE, {})
        return self._required_string(data, "balance")


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
        data = self._send_action(protocol.RequestType.DEPOSIT, {"amount": amount})
        return self._required_string(data, "balance")


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
        data = self._send_action(protocol.RequestType.WITHDRAW, {"amount": amount})
        return self._required_string(data, "balance")


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
        data = self._send_action(protocol.RequestType.TRANSFER, {
            "target": target,
            "amount": amount,
        })
        return self._required_string(data, "balance")


    def req_schedule_so(self, target: str, amount: str, count: str) -> int:
        """Create a recurring transfer with its first payment today.

        Args:
            target: Payee user id (token).
            amount: Amount per payment (positive decimal string).
            count: Number of payments as a digit string; blank or ``\"0\"`` means indefinitely.

        Returns:
            The new standing-order id (positive int).

        Raises:
            RequestFailed: validation error or unknown target.
            ConnectionError: connection lost.
        """
        if not isinstance(count, str):
            raise RequestFailed("Payment count must be a non-negative integer")
        count = count.strip() or "0"
        if not count.isascii() or not count.isdigit():
            raise RequestFailed("Payment count must be a non-negative integer")
        data = self._send_action(protocol.RequestType.STANDING_ORDER, {
            "target": target,
            "amount": amount,
            "count": count,
        })
        order_id = data.get("so_id")
        if isinstance(order_id, bool) or not isinstance(order_id, int) or order_id <= 0:
            raise RequestFailed("server response is missing a valid standing-order id")
        return order_id


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
            * ``remaining`` (int | None) — payments left, or ``None`` if indefinite
            * ``next_run`` (str) — next payment date ``YYYY-MM-DD``

        Raises:
            RequestFailed: not logged in or server error.
            ConnectionError: connection lost.
        """
        data = self._send_action(protocol.RequestType.GET_STANDING_ORDERS, {})
        rows = self._required_list(data, "standing_orders")
        result = []
        for row in rows:
            if not isinstance(row, list) or len(row) != 7:
                raise RequestFailed("server returned an invalid standing-order entry")
            order_id, token, name, amount, executed, remaining, next_run = row
            if (isinstance(order_id, bool) or not isinstance(order_id, int)
                    or not isinstance(token, str) or not isinstance(name, str)
                    or not isinstance(amount, str)
                    or isinstance(executed, bool) or not isinstance(executed, int)
                    or (remaining is not None and (
                        isinstance(remaining, bool) or not isinstance(remaining, int)))
                    or not isinstance(next_run, str)):
                raise RequestFailed("server returned an invalid standing-order entry")
            result.append((order_id, token, name, amount, executed, remaining, next_run))
        return result


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
        if isinstance(so_id, str):
            if not so_id.isascii() or not so_id.isdigit():
                raise RequestFailed("Standing-order id must be a positive integer")
            so_id = int(so_id)
        if isinstance(so_id, bool) or not isinstance(so_id, int) or so_id <= 0:
            raise RequestFailed("Standing-order id must be a positive integer")
        self._send_action(protocol.RequestType.CANCEL_STANDING_ORDER, {"so_id": so_id})


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
        data = self._send_action(protocol.RequestType.TAKE_LOAN, {"amount": amount})
        loan_id, balance = data.get("loan_id"), data.get("balance")
        if (isinstance(loan_id, bool) or not isinstance(loan_id, int) or loan_id <= 0
                or not isinstance(balance, str)):
            raise RequestFailed("server returned an invalid loan response")
        return loan_id, balance


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
        data = self._send_action(protocol.RequestType.GET_LOANS, {})
        rows = self._required_list(data, "loans")
        result = []
        for row in rows:
            if (not isinstance(row, list) or len(row) != 5
                    or isinstance(row[0], bool) or not isinstance(row[0], int)
                    or not all(isinstance(value, str) for value in row[1:])):
                raise RequestFailed("server returned an invalid loan entry")
            result.append(tuple(row))
        return result


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
        payload: dict[str, object] = {}
        for key, timestamp in (("from_ts", from_ts), ("to_ts", to_ts)):
            if timestamp is not None:
                if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                    raise RequestFailed(f"{key} must be a number")
                payload[key] = timestamp
        data = self._send_action(protocol.RequestType.GET_HISTORY, payload)
        rows = self._required_list(data, "history")
        result = []
        for row in rows:
            if (not isinstance(row, list) or len(row) != 7
                    or not all(isinstance(value, str) for value in row)):
                raise RequestFailed("server returned an invalid history entry")
            try:
                tx_type = TxType(row[1])
            except ValueError as error:
                raise RequestFailed(f"server returned an unknown transaction type: {row[1]}") from error
            result.append((row[0], tx_type, *row[2:]))
        return result
