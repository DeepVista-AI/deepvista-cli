# dv-remote spike

A working, deliberately small version of the relay architecture behind products
like [Vibe X](../../docs/design/vibe-x-teardown.md): a phone-side viewer talks
to a cloud relay, the developer's machine holds an outbound tunnel to the same
relay, and the relay copies bytes between them. Nothing listens on the laptop.

It exists to answer the question "which parts of that are actually hard?" with
code instead of a diagram. See [`../../docs/design/dv-remote.md`](../../docs/design/dv-remote.md)
for the product proposal this feeds.

## Run it

```bash
cd spikes/dv-remote
uv run --with websockets --with psutil python e2e_test.py      # 16/16 checks
```

Or drive it by hand in three terminals:

```bash
uv run --with websockets python relay.py --port 8787
uv run --with websockets python agent.py --machine mac-01 --relay ws://127.0.0.1:8787
uv run --with websockets python viewer.py --machine mac-01 --session s1      # type at it
# then, in a fourth terminal, attach a second viewer to the same session:
uv run --with websockets python viewer.py --machine mac-01 --session s1 --from 0
```

## Files

| | |
| --- | --- |
| `wire.py` | frame codec — JSON control frames, binary data frames carrying absolute byte offsets |
| `relay.py` | the cloud half: rendezvous by machine id, fan-out to viewers. Holds no scrollback and needs to understand nothing but routing |
| `agent.py` | the machine half: owns the PTY, keeps an offset-addressed ring buffer, replays on reattach, reconnects with backoff |
| `viewer.py` | what xterm.js would do — accumulates output, sends keys and resizes |
| `e2e_test.py` | boots real relay + agent subprocesses and asserts the eight claims below |

## What it demonstrates

1. Keystrokes reach a real PTY and output comes back — on a proper controlling
   terminal, so job control and `^C` work (`TIOCSCTTY`; without it the shell
   prints *"can't access tty; job control turned off"*).
2. The session outlives every viewer disconnecting.
3. A reconnecting viewer resumes at its byte offset: it gets what it missed and
   **only** what it missed.
4. Several viewers can watch one session simultaneously.
5. Resize reaches the tty — `stty size` inside the session proves it.
6. When a viewer asks for bytes the ring buffer has already dropped, it is told
   there is a **gap** instead of being handed a silently truncated stream.
7. The machine process has **zero listening sockets** and exactly one
   established outbound connection. This is the whole NAT story, asserted
   rather than assumed.
8. Killing the relay does not kill the session: the machine redials and the same
   shell process is still there, with its shell variables intact.

The load-bearing design decision is that **the scrollback lives on the machine,
not in the relay**. That is what lets the relay stay ~200 lines, stateless, and
— once frames are encrypted — unable to read anything it forwards.

## What it deliberately does not do

- **No tmux.** The real thing should drive `tmux -CC` control mode so sessions
  survive the agent process crashing, not just the tunnel dropping. Here the
  agent owns the PTY directly, so killing `agent.py` kills the session.
- **No encryption.** Frames are plaintext and auth is a shared `DVR_TOKEN`
  query parameter. Real: per-machine keypairs, short-lived scoped attach
  tokens, X25519 + AES-GCM between viewer and machine.
- **No snapshot paint.** A cold attach replays raw bytes; the test shows a
  400 KB flood arriving as 400 KB. Production needs a serialized screen
  (`pyte` server-side) followed by the tail.
- **No browser.** `viewer.py` is headless; xterm.js and a touch key row are the
  actual client.
- **In-memory ring only** (256 KiB), no disk spill, so a long offline window
  overflows into a `gap`. Intentional — the test asserts the gap is reported.
- **No multiplexing, flow control, or backpressure.** One socket per viewer per
  session, and a fast writer can outrun a slow phone.
