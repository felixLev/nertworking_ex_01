import json
import socket
import struct
from enum import IntEnum

MAX_MESSAGE_SIZE = 1024 * 1024


class ProtocolError(Exception):
    """A client sent a malformed or incomplete protocol message."""


class RequestType(IntEnum):
    REGISTER_USER           = 1
    LOGIN                   = 2
    GET_BALANCE             = 3
    TRANSFER                = 4
    STANDING_ORDER          = 5
    TAKE_LOAN               = 6
    CANCEL_STANDING_ORDER   = 7
    GET_LOANS               = 8
    LOGOUT                  = 9


class Status(IntEnum):
    SUCCESS                 = 1
    ERROR                   = 2


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly n bytes from a client socket."""
    buffer = bytearray()
    while len(buffer) < n:
        try:
            packet = sock.recv(n - len(buffer))
        except OSError as error:
            raise ConnectionError(f"failed to receive message: {error}") from error
        if not packet:
            if not buffer:
                raise ConnectionError("client closed the connection")
            raise ProtocolError("client closed the connection in the middle of a message")
        buffer.extend(packet)
    return bytes(buffer)


def receive_message(sock: socket.socket) -> tuple[RequestType, object]:
    """Read, decode, and validate one length-prefixed client request."""
    raw_length = recv_exact(sock, 4)
    message_length = struct.unpack(">I", raw_length)[0]
    if message_length == 0 or message_length > MAX_MESSAGE_SIZE:
        raise ProtocolError(f"invalid message size: {message_length}")

    raw_payload = recv_exact(sock, message_length)
    try:
        message = json.loads(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError(f"invalid JSON request: {error}") from error
    if not isinstance(message, dict):
        raise ProtocolError("message JSON must be an object")
    action_value = message.get("action")
    if isinstance(action_value, bool) or not isinstance(action_value, int):
        raise ProtocolError("message action must be a known request type")
    try:
        action = RequestType(action_value)
    except ValueError as error:
        raise ProtocolError("message contains an unknown or missing action") from error
    if "payload" not in message:
        raise ProtocolError("message is missing its payload")
    request_data = message["payload"]
    if not isinstance(request_data, dict):
        raise ProtocolError("message payload must be an object")
    return action, request_data


def build_message(data: object, status = Status.SUCCESS) -> bytes:
    encoded_message = json.dumps({
        "status": status,
        "data": data,
    }).encode("utf-8")
    return struct.pack(">I", len(encoded_message)) + encoded_message


def build_error_message(message: str):
    encoded_message = json.dumps({
        "status": Status.ERROR,
        "data": {"error": message},
    }).encode("utf-8")
    return struct.pack(">I", len(encoded_message)) + encoded_message