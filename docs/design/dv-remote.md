# DV Attach — a Vibe X-shaped product, built on what DeepVista already has

**Date:** 2026-08-03 · **Status:** proposal for discussion, nothing decided
**Companion:** [`vibe-x-teardown.md`](vibe-x-teardown.md) · [`../../spikes/dv-remote/`](../../spikes/dv-remote/) — running spike, 16/16 checks

---

## 1. The one-paragraph version

Vibe X sells **pixels**: a phone-shaped terminal attached to your Mac, priced by
bandwidth. DeepVista already sells **memory**: machines, agents, tasks,
sessions and notes that persist and compound. We are two thirds of the way to
the same product from the other direction — we have the control plane
(identity, projects, machines, dispatch, transcripts) and, uniquely, a
*semantic* event stream from real hooks. What we lack is the live data plane:
the ability to see and type into a session that is running right now.

So the proposal is not "build a tunnel company". It is: **add an interactive
attach surface to the machine graph we already own, and let the product be the
approval inbox rather than the terminal.** The terminal is the escape hatch.

## 2. What we already have (verified in this repo)

| Piece | Where | What it gives us |
| --- | --- | --- |
| Auth + token store | `deepvista_cli/auth/` | device login, refreshable tokens |
| Project scoping | `deepvista_cli/commands/project.py` | every object is already project-scoped |
| **Machine registry** | `deepvista_cli/commands/agents.py:401` (`resolve_or_register_machine`), `:53` (`_machine_fingerprint`) | stable machine identity per project, online/offline heartbeat |
| **Remote dispatch** | `deepvista_cli/commands/tasks.py:254` (`_run_task_card`) | the web already sends work to a specific machine; the machine runs `claude -p /deepvista …` locally with `--output-format stream-json` |
| **Live progress channel** | `dv tasks note`, `tasks.py:1333` | the web chat's "Wait for Local Agent" panel already streams from this |
| **Session transcripts** | `deepvista_cli/commands/session.py:95` `init` / `:214` `tick` / `:317` `finalize` | rolling session cards, driven by Claude Code plugin hooks |
| Workflow phases | `update_workflow_phase` (DeepVista MCP), `workflow_doc.py` | phase state a mobile UI can render |
| Skills / knowledge | `dv skill`, `dv card`, `dv chat` | the reason to be in this product at all |

The gap is narrow and specific:

- dispatch is **pull-based and one-shot** (`dv tasks poll` → run → report). You
  cannot watch a run, and you cannot answer it a question mid-flight.
- there is **no live session object** — `session init/tick/finalize` records
  what happened, not what is happening.
- there is **no viewer**.

## 3. The wedge: an approval inbox, not a terminal

Vibe X's weakest claim is that it can notify you at "key checkpoints" while
installing no hooks and no plugins — leaving screen scraping as the only
detector (teardown §2.2c). We ship `plugins/claude-code/` with hooks and
already parse `stream-json` events (`tasks.py:230` `_summarize_stream_event`).
We can know *semantically* that a run is blocked on a permission prompt, which
phase a workflow is in, and which card it touched.

That flips the default UI. The home screen is not a terminal; it is a feed:

```
┌ mac-studio · deepvista-cli ─────────────────────────┐
│ ● DV-1901 refactor bundle store        needs you ▲ │   ← blocked on approval
│     "Bash(rm -rf .venv)" — allow once? [Y] [n]      │
│ ● DV-1904 skill: research-to-skill    phase 3/5    │
│ ○ nightly sweep                        done 04:12  │
│                                    [ open terminal ]│   ← escape hatch
└─────────────────────────────────────────────────────┘
```

Every row already exists as a DeepVista object. The terminal is one tap away
for when the structured view is not enough — which is often, and is why the
data plane still has to be good.

## 4. Architecture

```
  PWA (xterm.js + touch key row)          Native apps: not in v1
        │  WSS, one multiplexed socket, N session channels
        ▼
  ┌────────────────────────────────────────────────┐
  │ DeepVista API (existing)   │ dv-relay (new)    │
  │  auth, projects, machines  │  ~200 LOC         │
  │  tasks, cards, sessions    │  stateless byte   │
  │  mints attach tokens ─────►│  copier + fan-out │
  └────────────────────────────────────────────────┘
        ▲ outbound WSS, opened by the machine, never inbound
        │
  ┌─────┴───────────────────────────────────────────┐
  │ `dv attach serve`  (new subcommand, this CLI)   │
  │   ├ tunnel client + reconnect/backoff           │
  │   ├ ring buffer, offset-addressed (spill to disk)│
  │   ├ pyte screen  → snapshot paint + detectors   │
  │   └ tmux control-mode client (`tmux -CC`)       │
  └─────┬───────────────────────────────────────────┘
        │ send-keys -H / resize-window / capture-pane
  ┌─────┴───────────────────────────────────────────┐
  │ tmux server (detached, survives everything)     │
  │   └ claude / codex / your shell                 │
  └─────────────────────────────────────────────────┘
```

### 4.1 Session substrate: tmux, plus our own buffer

Vibe X uses tmux control mode; we should too, and then go one better.

- **tmux for liveness.** Detach, reattach, scrollback, multi-client and
  surviving `dv attach` crashing all come free, with no shell instrumentation —
  and it is what people already run agents inside. On Windows, psmux (with the
  same caveat that it is young; see teardown §2.1).
- **Our own ring buffer for correctness.** Control mode gives an unaddressed
  `%output` stream, so tmux alone can only resync by repainting the screen. The
  agent should tag every chunk with an absolute byte offset and keep a bounded
  ring (spilling to disk), so a phone that was offline for an hour can ask for
  *exactly* what it missed and be told when the buffer could not cover it. This
  is the half the spike proves; tmux is the half the spike stubs out.
- **`pyte` screen for two jobs**: (a) *snapshot paint* — a cold attach gets one
  serialized screen and then the tail, so the phone paints in one frame instead
  of replaying 400 KB of ANSI (the spike shows what the naive path costs); and
  (b) *detectors* — run the "is this blocked on a prompt?" heuristics against a
  parsed grid rather than a byte stream, as a fallback for agents we have no
  hooks for.

**Attach = snapshot + tail-from-offset. Resume = tail-from-offset alone.** Those
are different operations and conflating them is the mistake to avoid.

### 4.2 Wire protocol

Exactly what the spike implements ([`wire.py`](../../spikes/dv-remote/wire.py)),
plus a version byte and a channel id:

- **Data frames** (binary — do not base64 a terminal):
  `| kind u8 | len(session_id) u8 | offset u64be | session_id | payload |`
  `kind`: `1` output (machine→viewer, `offset` = absolute stream position),
  `2` input (viewer→machine).
- **Control frames** (JSON text): `attach{session,from}`, `attached{offset}`,
  `gap{from,resumed_at}`, `snapshot{rows,cols,grid}`, `resize{rows,cols}`,
  `exit`, `event{kind,task_id,…}` for the semantic feed.
- **Resize policy** (needs a decision, see §8): one attached viewer is the
  *controller* and owns the size; others letterbox. Auto-fitting to `min(cols)`
  across a phone and a laptop makes the laptop unusable, and reflowing a
  full-screen TUI on every device switch corrupts the display.

### 4.3 Notifications

Machine-side only, and structured: the hook/`stream-json` path already knows
when a run needs input, so `dv attach serve` emits an `event` frame and the API
sends the push. Nothing about the terminal bytes needs to be readable by the
server for notifications to work — which is what makes end-to-end encryption
affordable for us and expensive for Vibe X (teardown §2.3).

## 5. Security model

The uncomfortable truth first: **this ships a permanent, deliberate remote-code
execution channel into developer machines that bypasses every inbound network
control.** The crypto is the easy part; the account is the attack surface. Bare
minimum for v1:

1. **Explicit, per-machine, foreground enablement.** `dv attach serve` runs in
   the foreground for a chosen project. No daemon, no autostart, no "it was
   already running" surprise. Closing it ends attachability.
2. **Per-machine keypair** created at enrol time, stored next to the existing
   machine identity (`agents.py:83` `_machine_path`); the machine authenticates
   to the relay by key, not by a bearer token that lives in a config file.
3. **Short-lived, scoped attach tokens** minted by the API per attach
   (machine + session + expiry), never reusable, revocable per device.
4. **E2E from day one, or say plainly that it isn't.** X25519 ECDH between
   viewer device and machine, AES-256-GCM per message; the relay copies
   ciphertext. Feasible *because* of §4.3. Happy has shown users care.
5. **Attach requires confirmation** on first use from a new device, plus a
   visible indicator on the host while anyone is attached.
6. **Scope limits**: allowlist of project directories; refuse to spawn outside
   them; `--read-only` mode that drops input frames.
7. **Audit as data.** Every attach, input burst and approval becomes a card, so
   the audit trail lives in the knowledge base like everything else.

A stolen web session must not equal a shell. That means (3) + (5), not just TLS.

## 6. Cost and pricing

Do the arithmetic before copying anyone's price sheet. An active agent session
is a few KB/s; a hard month of use is well under a gigabyte per developer. Relay
egress is therefore **noise** — cents per seat per month — and metering GB the
way Vibe X does would price a rounding error and cap the good case.

Recommendation: **no new meter.** Attach is a feature of the existing DeepVista
plan (fair-use concurrent-session cap to stop obvious abuse). Deliberately leave
out file transfer, publish and port forwarding — that is where the bandwidth
cost, the abuse surface and the loss of E2E all live, and none of it is in
DeepVista's business.

## 7. Phasing

Each milestone is independently shippable, one engineer, given the spike.

| | Scope | Rough |
| --- | --- | --- |
| **M0** ✅ | Spike: relay + PTY agent + viewer, offset resume, fan-out, no inbound port, survives relay restart | done — `spikes/dv-remote/` |
| **M1** | `dv attach serve` over tmux control mode; `dv-relay` deployed; PWA with xterm.js + touch key row; one session; API: live-session objects + attach tokens | ~2–3 wks |
| **M2** | The inbox: hook/`stream-json` events → push → approve-from-phone, wired to existing task/session cards | ~2 wks |
| **M3** | Snapshot paint, disk-spilled buffer, multi-session/multi-machine switcher, E2E encryption, offline resume | ~3 wks |
| **M4** | Windows via psmux; predictive local echo; WebTransport/QUIC transport | opportunistic |

Build vs buy: **build the relay** (it is 200 lines and it must stay dumb), **buy
the edge** (any WS-capable managed edge; do not operate PoPs), **skip native
apps**, and **do not write a terminal emulator** — xterm.js on the front, pyte
on the back.

## 8. Open questions

1. **Is this a DeepVista product at all, or a feature?** My read: a feature.
   Positioned as "supervise the agent team you already have on your machines",
   it strengthens the knowledge product. Positioned as "terminal on your phone",
   it is a tunnel startup competing with Cloudflare on price and with Vibe X on
   CN network ops — neither of which we would win.
2. **Resize policy** — controller-owns-size (my recommendation) vs
   fit-to-smallest.
3. **E2E in M1 or M3?** It is cheap for us architecturally but it complicates
   the web viewer's key handling; shipping unencrypted and retrofitting is the
   usual mistake.
4. **tmux as a hard dependency?** It is the pragmatic choice and matches Vibe X,
   but it means "install tmux" in onboarding, and psmux on Windows is a young
   dependency. The alternative — our own PTY daemon, as in the spike — removes
   the dependency and costs us persistence-across-crash.
5. **Does the mobile market even matter to our users**, or is the real ask
   "let me watch a long local run from another laptop"? That answer changes the
   viewer priorities completely and should be checked before M1.

## 9. Non-goals

Authoring code on a phone. Hosting agents in our cloud. Port forwarding,
publish, or file transfer. Operating a CN PoP network. Native mobile apps in v1.
