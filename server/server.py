"""Single-threaded TCP banking server multiplexed with ``select()``.

Usage:
    python server.py [--host 127.0.0.1] [--port 5050] [--start-date YYYY-MM-DD] [--verbose]
"""
from __future__ import annotations

import argparse
import logging
import random
import string
import time
from datetime import date
import socket
import select

from bank import Bank
from server_utils import Console

log = logging.getLogger("server")

class UserData:
    # TODO: store password hash?
    def __init__(self, username: str, password: str, user_id: str) -> None:
        self.username = username
        self.password = password

### Do not remove any of the existing functions or change their signatures. ###
### You can add new functions and classes if needed. ###
class Server:
    def __init__(self, host: str, port: int, bank: Bank):
        self.host = host
        self.port = port

        self.bank = bank
        self.bank.announce_date()
        
        self.console = Console()

        self.users = []

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind((self.host, self.port))


    def server_loop(self) -> None:
        """Main server loop for the bank server."""
        # TODO implement this
        client_sockets = []
        while True:
            self.console.poll(self._on_advance_time_request)
            client_sock, _, _ = select.select([self.socket], [], [], 0.5)
            if self.socket in client_sock:
                client_sockets.append(self.socket.accept())
            time.sleep(0.1)  # TODO: do we need this sleep?

    def _on_advance_time_request(self, user_input):
        self.bank.clock.advance_day()
        print("time advanced")

    def _handle_create_user(self, username: str, password: str) -> str:
        user_id = self._generate_user_id()
        self.users.append(UserData(username, password, user_id))
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
