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


def build_message(status: Status, data: object) -> None:
    encoded_message = json.dumps({
        "status": status,
        "data": data,
    }).encode("utf-8")
    return struct.pack(">I", len(encoded_message)) + encoded_message


def unpack_message(payload: bytes) -> tuple[RequestType, object]:
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
