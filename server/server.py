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

        self.users = []
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
                        self.handle_client_request(sock, data)
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


    def handle_client_request(self, sock: socket, data: tuple[bytes, dict]):
        action, payload = data
        close_socket = False # states if we should close the socket after handling the request
        match action:
            case protocol.RequestType.REGISTER_USER:
                username = payload.get("username")
                password = payload.get("password")
                if isinstance(username, str) and isinstance(password, str):
                    user_id = self._handle_create_user(username, password)
                    newusername = username + password
                    print("newusername", newusername)
                    response = protocol.build_message({"userid": user_id})
                else:
                    response = protocol.build_error_message("Registration requires string username and password fields")
            case protocol.RequestType.LOGIN:
                username = payload.get("username")
                password = payload.get("password")
                user_id = payload.get("user_id")
                if isinstance(username, str) and isinstance(password, str) and isinstance(user_id, str):
                    login_success = False
                    for user in self.users:
                        if user.username == username and user.password == password and user.user_id == user_id:
                            self.logged_in_users[sock] = user
                            login_success = True
                    response = protocol.build_message({"status": int(login_success)})
                else:
                    response = protocol.build_error_message("Login requires username, password and user id fields")
            case protocol.RequestType.LOGOUT:
                if sock not in self.logged_in_users:
                    sock.close() # TODO: should we close the socket in this case?
                    response = protocol.build_error_message("No logged in user was found")
                else:
                    close_socket = True
                    response = protocol.build_message({"status": 1})
                    self.logged_in_users.pop(sock)
            case _:
                response = protocol.build_error_message("Unsupported action")
        sock.sendall(response)
        if close_socket:
            sock.close()


    def _on_advance_time_request(self, user_input):
        self.bank.clock.advance_day()
        print("Time advanced")
        self.bank.announce_date()

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
