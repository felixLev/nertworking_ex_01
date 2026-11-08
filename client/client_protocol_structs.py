import struct
from enum import IntEnum


class RequestType(IntEnum):
    REGISTER_USER = 1

def build_register_user_payload(user: str, password: str) -> bytes:
    encoded_user = user.encode('utf-8')
    encoded_password = password.encode('utf-8')
    return struct.pack(f'>II{len(encoded_user)}sI{len(encoded_password)}s', RequestType.REGISTER_USER,
                       len(encoded_user), encoded_user,
                       len(encoded_password), encoded_password)
