"""Single-threaded TCP banking server multiplexed with ``select()``.

Usage:
    python server.py [--host 127.0.0.1] [--port 5050] [--start-date YYYY-MM-DD] [--verbose]
"""
from __future__ import annotations

import argparse
import logging
import random
import re
import string
import time
from datetime import date
import socket
import select

from bank import Bank
from server_utils import Console

import server_protocol_structs as protocol

log = logging.getLogger("server")

class UserData:
    # TODO: store password hash?
    def __init__(self, username: str, password: str, user_id: str) -> None:
        self.username = username
        self.password = password
        self.user_id = user_id

### Do not remove any of the existing functions or change their signatures. ###
### You can add new functions and classes if needed. ###
class Server:
    def __init__(self, host: str, port: int, bank: Bank):
        self.host = host
        self.port = port

        self.bank = bank
        self.bank.announce_date()
        
        self.console = Console()

        self.users: list[UserData] = []
        self.logged_in_users = {}  # Maps sockets to the UserData's of the users that logged in with them

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind((self.host, self.port))
        self.socket.listen()


    def server_loop(self) -> None:
        """Main server loop for the bank server."""
        client_sockets = {} # TODO: change to list
        while True:
            self.console.poll(self._on_advance_time_request)
            socket_list = list(client_sockets.keys()) + [self.socket]
            reading_sockets, _, _ = select.select(socket_list, [], [], 1)
            for sock in reading_sockets:
                if sock == self.socket:
                    try:
                        client_socket, _ = self.socket.accept()
                    except OSError:
                        log.exception("Failed to accept client connection")
                        continue
                    client_sockets[client_socket] = ""
                    log.info("Client accepted")
                    print("Client accepted")
                else:
                    try:
                        data = protocol.receive_message(sock)
                    except ConnectionError as error:
                        self._close_client(sock, client_sockets)
                        log.info("Client disconnected: %s", error)
                        print("Client disconnected")
                        continue
                    except protocol.ProtocolError as error:
                        log.warning("Invalid message from client: %s", error)
                        try:
                            self._send_error(sock, str(error))
                        except OSError:
                            log.exception("Failed to send protocol error response")
                        self._close_client(sock, client_sockets)
                        continue
                    try:
                        if self.handle_client_request(sock, data):
                            client_sockets.pop(sock)
                    except OSError as error:
                        log.info("Client connection failed while responding: %s", error)
                        self._close_client(sock, client_sockets)
                    except Exception:
                        log.exception("Unexpected error while handling client request")
                        try:
                            self._send_error(sock, "Internal server error")
                        except OSError:
                            log.exception("Failed to send internal server error response")
                            self._close_client(sock, client_sockets)

    @staticmethod
    def _close_client(sock: socket.socket, client_sockets: dict) -> None:
        client_sockets.pop(sock, None)
        try:
            sock.close()
        except OSError:
            log.exception("Failed to close client socket")

    def _send_error(self, sock: socket.socket, message: str) -> None:
        sock.sendall(protocol.build_error_message(message))


    def handle_client_request(self, sock: socket, data: tuple[bytes, dict]) -> bool:
        action, payload = data
        if not isinstance(payload, dict):
            self._send_error(sock, "Request payload must be an object")
            return False

        close_socket = False
        try:
            match action:
                case protocol.RequestType.REGISTER_USER:
                    self._check_fields(payload, {"username", "password"})
                    username, password = payload["username"], payload["password"]
                    if not isinstance(username, str) or not re.fullmatch(
                            r"[A-Za-z0-9_]{3,20}", username):
                        raise ValueError("Username must be 3-20 letters, digits or underscores")
                    if not isinstance(password, str) or len(password) < 4:
                        raise ValueError("Password must contain at least 4 characters")
                    user_id = self._handle_create_user(username, password)
                    result = {"userid": user_id}
                case protocol.RequestType.LOGIN:
                    self._check_fields(payload, {"username", "password", "user_id"})
                    username, password, user_id = (
                        payload["username"], payload["password"], payload["user_id"])
                    if not all(isinstance(value, str) for value in (username, password, user_id)):
                        raise ValueError("Login requires string username, password and user id fields")
                    user = next((candidate for candidate in self.users
                                 if candidate.username == username
                                 and candidate.password == password
                                 and candidate.user_id == user_id), None)
                    if user is None:
                        raise ValueError("Wrong credentials or unknown user id")
                    if sock in self.logged_in_users:
                        raise ValueError("This connection already has a logged-in user")
                    self.logged_in_users[sock] = user
                    result = {"status": 1}
                case protocol.RequestType.LOGOUT:
                    self._check_fields(payload, set())
                    self._require_logged_in(sock)
                    self.logged_in_users.pop(sock)
                    result = {"status": 1}
                    close_socket = True
                case protocol.RequestType.GET_BALANCE:
                    self._check_fields(payload, set())
                    user = self._require_logged_in(sock)
                    result = {"balance": self.bank.get_balance(user.user_id)}
                case protocol.RequestType.DEPOSIT:
                    self._check_fields(payload, {"amount"})
                    user = self._require_logged_in(sock)
                    result = {"balance": self.bank.deposit(user.user_id, payload["amount"])}
                case protocol.RequestType.WITHDRAW:
                    self._check_fields(payload, {"amount"})
                    user = self._require_logged_in(sock)
                    result = {"balance": self.bank.withdraw(user.user_id, payload["amount"])}
                case protocol.RequestType.TRANSFER:
                    self._check_fields(payload, {"target", "amount"})
                    user = self._require_logged_in(sock)
                    target = payload["target"]
                    if not isinstance(target, str):
                        raise ValueError("Target account id must be a string")
                    result = {"balance": self.bank.transfer(
                        user.user_id, target, payload["amount"])}
                case protocol.RequestType.STANDING_ORDER:
                    self._check_fields(payload, {"target", "amount", "count"})
                    user = self._require_logged_in(sock)
                    target, count_text = payload["target"], payload["count"]
                    if not isinstance(target, str):
                        raise ValueError("Target account id must be a string")
                    if not isinstance(count_text, str) or not re.fullmatch(r"[0-9]+", count_text):
                        raise ValueError("Payment count must be a non-negative integer string")
                    result = {"so_id": self.bank.create_standing_order(
                        user.user_id, target, payload["amount"], int(count_text))}
                case protocol.RequestType.TAKE_LOAN:
                    self._check_fields(payload, {"amount"})
                    user = self._require_logged_in(sock)
                    loan_id, balance = self.bank.take_loan(user.user_id, payload["amount"])
                    result = {"loan_id": loan_id, "balance": balance}
                case protocol.RequestType.CANCEL_STANDING_ORDER:
                    self._check_fields(payload, {"so_id"})
                    user = self._require_logged_in(sock)
                    order_id = payload["so_id"]
                    if isinstance(order_id, str) and re.fullmatch(r"[0-9]+", order_id):
                        order_id = int(order_id)
                    self.bank.cancel_standing_order(user.user_id, order_id)
                    result = {"status": 1}
                case protocol.RequestType.GET_LOANS:
                    self._check_fields(payload, set())
                    user = self._require_logged_in(sock)
                    result = {"loans": self.bank.get_loans(user.user_id)}
                case protocol.RequestType.GET_HISTORY:
                    self._check_fields(payload, set(), {"from_ts", "to_ts"})
                    user = self._require_logged_in(sock)
                    result = {"history": self.bank.get_history(
                        user.user_id, payload.get("from_ts"), payload.get("to_ts"))}
                case _:
                    raise ValueError("Unsupported action")
            response = protocol.build_message(result)
        except ValueError as error:
            response = protocol.build_error_message(str(error))

        sock.sendall(response)
        if close_socket:
            sock.close()
        return close_socket


    @staticmethod
    def _check_fields(payload: dict, required: set[str],
                      optional: set[str] = frozenset()) -> None:
        missing = required - payload.keys()
        unknown = payload.keys() - required - optional
        if missing:
            raise ValueError(f"Missing request field(s): {', '.join(sorted(missing))}")
        if unknown:
            raise ValueError(f"Unexpected request field(s): {', '.join(sorted(unknown))}")


    def _require_logged_in(self, sock: socket.socket) -> UserData:
        user = self.logged_in_users.get(sock)
        if user is None:
            raise ValueError("Login is required for this request")
        return user


    def _on_advance_time_request(self, user_input):
        self.bank.advance_day()
        print("Time advanced")
        self.bank.announce_date()

    def _handle_create_user(self, username: str, password: str) -> str:
        user_id = self._generate_user_id()
        while user_id in self.bank.accounts:
            user_id = self._generate_user_id()
        self.users.append(UserData(username, password, user_id))
        self.bank.add_account(user_id, username)
        return user_id

    @staticmethod
    def _generate_user_id():
        """
        generates a 10 letters user ID
        TODO: maybe make sure the same uid isn't generated twice?
        """
        return ''.join(random.choices(string.ascii_letters + string.digits, k=10))

### Do not touch anything below this line. ###
def parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {text!r}") from None


def main() -> None:
    parser = argparse.ArgumentParser(description="select()-based socket banking server")
    parser.add_argument("--host", default="")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--start-date", type=parse_date, default=date.today(),
                        help="first bank date, YYYY-MM-DD (default: today)")
    parser.add_argument("--verbose", action="store_true", help="log every request and reply")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")

    bank = Bank(start_date=args.start_date)
    server = Server(args.host, args.port, bank)
    try:
        server.server_loop()
    except KeyboardInterrupt:
        log.info("shutting down")
        print("\nShutting down.", flush=True)


if __name__ == "__main__":
    main()
