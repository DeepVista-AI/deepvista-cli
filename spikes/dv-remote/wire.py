"""Frame codec shared by the relay, the machine agent, and viewers.

Two frame classes ride the same WebSocket:

* **Control frames** are JSON text frames (``attach``, ``resize``, ``gap``, ...).
* **Data frames** are binary, so PTY bytes are not base64-inflated on the way
  through. Every output frame carries the session's absolute byte offset. That
  offset is the whole trick behind resume-after-reconnect: a viewer that comes
  back says "I had up to N", and the machine replays from its own ring buffer.
  The relay never needs to store (or be able to read) the stream.

Header layout for data frames::

    | kind: u8 | len(session_id): u8 | offset: u64be | session_id | payload |
"""

import json
import struct

OUTPUT = 1  # machine -> viewer: PTY bytes at `offset`
INPUT = 2  # viewer -> machine: keystrokes (offset unused, always 0)

_HEAD = struct.Struct("!BBQ")


def encode_data(kind: int, session_id: str, offset: int, payload: bytes) -> bytes:
    sid = session_id.encode()
    if len(sid) > 255:
        raise ValueError("session id too long")
    return _HEAD.pack(kind, len(sid), offset) + sid + payload


def decode_data(frame: bytes) -> tuple[int, str, int, bytes]:
    kind, sid_len, offset = _HEAD.unpack_from(frame)
    start = _HEAD.size
    sid = frame[start : start + sid_len].decode()
    return kind, sid, offset, frame[start + sid_len :]


def encode_ctrl(**fields: object) -> str:
    return json.dumps(fields, separators=(",", ":"))


def decode_ctrl(text: str) -> dict:
    return json.loads(text)
