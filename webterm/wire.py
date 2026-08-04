"""Frame codec: JSON text frames for control, binary frames for terminal bytes.

Data frame layout (mirrored by `wire.js` in the browser)::

    | kind: u8 | len(session_id): u8 | offset: u64be | session_id | payload |

`offset` is the absolute position of `payload` in the session's output stream on
OUTPUT frames, and unused (0) on INPUT frames. Keeping terminal bytes out of
JSON avoids base64 inflating every keystroke and every screen repaint.
"""

from __future__ import annotations

import json
import struct

OUTPUT = 1  # server -> browser
INPUT = 2  # browser -> server

_HEAD = struct.Struct("!BBQ")


def encode_data(kind: int, session_id: str, offset: int, payload: bytes) -> bytes:
    sid = session_id.encode()
    if len(sid) > 255:
        raise ValueError("session id too long")
    return _HEAD.pack(kind, len(sid), offset) + sid + payload


def decode_data(frame: bytes) -> tuple[int, str, int, bytes]:
    kind, sid_len, offset = _HEAD.unpack_from(frame)
    start = _HEAD.size
    return kind, frame[start : start + sid_len].decode(), offset, frame[start + sid_len :]


def encode_ctrl(**fields: object) -> str:
    return json.dumps(fields, separators=(",", ":"))


def decode_ctrl(text: str) -> dict:
    return json.loads(text)
