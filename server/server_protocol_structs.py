import json
import socket
import struct
from enum import IntEnum


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


def recv_exact(sock: socket, n: int) -> bytes:
    """Helper function to receive exactly n bytes from a TCP socket."""
    buffer = bytearray()
    while len(buffer) < n:
        packet = sock.recv(n - len(buffer))
        if not packet:
            # Connection closed by peer prematurely
            raise ConnectionResetError("Socket closed before full payload was received")
        buffer.extend(packet)
    return bytes(buffer)


def receive_message(sock: socket) -> bytes:
    """Reads a complete length-prefixed JSON message from the socket."""
    # 1. Read the fixed 4-byte header to determine payload size
    raw_length = recv_exact(sock, 4)
    message_length = struct.unpack(">I", raw_length)[0]
    # 2. Read exactly `message_length` bytes of JSON payload
    raw_payload = recv_exact(sock, message_length)
    # 3. Safely decode and parse the full payload
    message = json.loads(raw_payload.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("message JSON must be an object")
    action_value = message.get("action")
    if isinstance(action_value, bool) or not isinstance(action_value, int):
        raise ValueError("message action must be a known request type")
    try:
        action = RequestType(action_value)
    except ValueError as error:
        raise ValueError("message contains an unknown or missing action") from error
    if "payload" not in message:
        raise ValueError("message is missing its payload")
    return action, message["payload"]


def build_message(status: Status, data: object) -> None:
    encoded_message = json.dumps({
        "status": status,
        "data": data,
    }).encode("utf-8")
    return struct.pack(">I", len(encoded_message)) + encoded_message