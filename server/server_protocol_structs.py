import struct

# Note that the unpacking functions unpack the payloads after the Request Type code was already removed from them
def unpack_register_user_payload(payload: bytes) -> tuple[str, str]:
    username_len = struct.unpack('>I', payload[:4])[0]
    username = str(payload[4:4 + username_len])
    password_len = struct.unpack('>I', payload[username_len + 4:username_len + 8])[0]
    password = str(payload[username_len + 8:username_len + 8 + password_len])
    return username, password
