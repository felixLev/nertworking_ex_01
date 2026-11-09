import json
import socket
import struct
from enum import IntEnum

MAX_MESSAGE_SIZE = 1024 * 1024


class ProtocolError(Exception):
    """The server sent something that cannot be parsed."""


class RequestFailed(Exception):
    """The server rejected the request. ``str(self)`` is safe to show to the user."""


class RequestType(IntEnum):
    REGISTER_USER           = 1
    LOGIN                   = 2
    GET_BALANCE             = 3
    TRANSFER                = 4
    STANDING_ORDER          = 5
    TAKE_LOAN               = 6
    CANCEL_STANDING_ORDER   = 7
    GET_LOANS               = 8


class Status(IntEnum):
    SUCCESS                 = 1
    ERROR                   = 2


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly n bytes, distinguishing a clean close from a truncated frame."""
    buffer = bytearray()
    while len(buffer) < n:
        try:
            packet = sock.recv(n - len(buffer))
        except OSError as error:
            raise ConnectionError(f"failed to receive message: {error}") from error
        if not packet:
            if not buffer:
                raise ConnectionError("peer closed the connection")
            raise ConnectionError("peer closed the connection in the middle of a message")
        buffer.extend(packet)
    return bytes(buffer)


def receive_message(sock: socket.socket) -> tuple[Status, object]:
    """Read, decode, and validate one length-prefixed server response."""
    raw_length = recv_exact(sock, 4)
    message_length = struct.unpack(">I", raw_length)[0]
    if message_length == 0 or message_length > MAX_MESSAGE_SIZE:
        raise ProtocolError(f"invalid message size: {message_length}")
    raw_payload = recv_exact(sock, message_length)
    try:
        message = json.loads(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError(f"invalid JSON response: {error}") from error
    if not isinstance(message, dict):
        raise ProtocolError("message JSON must be an object")
    status_value = message.get("status")
    data = message.get("data")
    if isinstance(status_value, bool) or not isinstance(status_value, int):
        raise ProtocolError("message status must be a known status value")
    try:
        status = Status(status_value)
    except ValueError as error:
        raise ProtocolError(f"unknown message status: {status_value}") from error
    if status is Status.ERROR:
        if not isinstance(data, dict) or not isinstance(data.get("error"), str):
            raise ProtocolError("server error response is missing an error message")
        raise RequestFailed(data["error"])
    if "data" not in message:
        raise ProtocolError("message is missing its data")
    return status, data


def build_message(action: RequestType, payload: dict[str, object]) -> bytes:
    encoded_message = json.dumps({ "action": action, "payload": payload }).encode('utf-8')
    return struct.pack('>I', len(encoded_message)) + encoded_message


def build_register_user_payload(username: str, password: str) -> bytes:
    return build_message(RequestType.REGISTER_USER, {
        'username': username,
        'password': password,
    })
