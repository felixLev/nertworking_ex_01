import json
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


def build_message(action: RequestType, payload: dict[str, object]) -> bytes:
    encoded_message = json.dumps({ "action": action, "payload": payload }).encode('utf-8')
    return struct.pack('>I', len(encoded_message)) + encoded_message


def unpack_message(payload: bytes) -> tuple[Status, object]:
    if len(payload) < 4:
        raise ValueError("message is missing its length prefix")

    message_length = struct.unpack(">I", payload[:4])[0]
    message_bytes = payload[4:]
    if len(message_bytes) != message_length:
        raise ValueError(
            f"message length prefix specifies {message_length} bytes, "
            f"but received {len(message_bytes)}"
        )

    message = json.loads(message_bytes.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("message JSON must be an object")

    status_value = message.get("status")
    if isinstance(status_value, bool) or not isinstance(status_value, int):
        raise ValueError("message status must be a known status value")
    try:
        status = Status(status_value)
    except ValueError as error:
        raise ValueError(f"unknown message status: {status_value}") from error

    if "data" not in message:
        raise ValueError("message is missing its data")
    return status, message["data"]


def build_register_user_payload(user: str, password: str) -> bytes:
    return build_message(RequestType.REGISTER_USER, {
        'user': user,
        'password': password,
    })
