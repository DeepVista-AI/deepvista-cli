# Vibe X (vibecafe.ai/x) — teardown

**Date:** 2026-08-03 · **Status:** analysis, no decisions
**Companion:** [`dv-remote.md`](dv-remote.md) — what we would build · [`../../spikes/dv-remote/`](../../spikes/dv-remote/) — working spike

---

## 1. What it is

Vibe X is one product inside **VibeCafé**, a Chinese-language creator community
(the site also hosts Vibe Usage, a works showcase, a freelance board, Vibe
Friends, and a paid club). It is in invite beta — the `/x` page is a marketing
page plus a waitlist (`POST /api/x/beta/apply`), auth is Clerk
(`clerk.vibecafe.ai`), hosting is Next.js on Vercel.

Its pitch, verbatim: *"Vibe X 是你的随身 Vibe 工作台 … 连接你的本地 Vibe 环境，
即使在手机上也能顺畅交互，让 Coding Agent 随叫随到"* — a pocket workbench that
connects to your local dev environment so your coding agent is reachable from
your phone.

Claimed capabilities, from the page copy:

| Claim | Copy |
| --- | --- |
| Zero setup | *"电脑上装好 App，手机登录即可连接：没有配置文件，也不需要端口映射或公网 IP"* |
| Non-invasive | *"基于终端标准与 Agent 自身能力：不安装 hook、不加插件，也不修改任何配置"* |
| Persistence | *"切换网络、锁屏或更换设备后，会话仍保持原状。进度在各端同步，关键节点会推送到手机"* |
| Hosts | macOS + Linux today, Windows *"即将上线"* |
| Viewers | iOS + Android native apps, browser PWA, *"触屏交互经过专门打磨"* |
| Extras | *"含文件传输、一键发布、端口转发"* — file transfer, publish static output to a public URL, temporary port forwarding with automatic HTTPS |
| CN network | *"网络链路按国内环境选点与调优，弱网、基站切换或短暂离线后的重连都很快"* |

Pricing (beta is free, prices marked indicative): **$14/mo** (2 devices, 5
concurrent sessions, 20 Mbps, 10 GB/mo) → **$42/mo** (5 devices, 20 sessions,
80 GB) → **$140/mo** (unlimited devices/sessions, 100 Mbps, 1000 GB). Annual
billing saves 30%.

---

## 2. The topology — confirmed

The working hypothesis (browser → cloud relay → outbound tunnel → Mac app →
PTY → Claude Code) is right, and the "no port mapping, no public IP" claim
forces it: nothing else survives NAT, CGNAT, corporate firewalls and dynamic
IPs without user configuration. It is Cloudflare-Tunnel-shaped, with an
interactive terminal stream instead of HTTP services.

```
   Mobile browser / native app                    ┌─ this hop is why it works
   ┌──────────────────────┐                       │  behind NAT: both sides
   │ xterm.js + touch bar │                       │  dial OUT, nobody listens
   └──────────┬───────────┘                       │
              │ WSS (viewer session)              │
              ▼                                   │
   ┌─────────────────────────────┐                │
   │ Vibe cloud                  │◄───────────────┘
   │  Clerk auth · session index │
   │  relay (byte copier)        │
   │  push notifications         │
   └─────────────▲───────────────┘
                 │ WSS, opened by the machine, kept alive
                 │
   ┌─────────────┴───────────────────────────────────┐
   │ macOS / Linux host                              │
   │   Vibe X app  ── tmux control-mode client ──┐   │
   │                                             ▼   │
   │                            tmux server (detached)│
   │                                      │ PTY      │
   │                              claude / codex /    │
   │                              gemini / your shell │
   └─────────────────────────────────────────────────┘
```

### 2.1 The substrate is tmux — this is evidenced, not guessed

The most useful thing found in this teardown is not on the product page. The
VibeCafé feed announces that the Vibe X team shipped two upstream PRs to
**[psmux](https://github.com/psmux/psmux)** — a from-scratch native Windows
tmux written in Rust — *"在 psmux 上实现了所有终端工具需要的 tmux 核心基础功能"*:

- [psmux#524](https://github.com/psmux/psmux/pull/524) `fix(send-keys): implement -H literal-byte injection` — **merged 2026-08-02**. Adds tmux's `send-keys -H`, which writes raw hex bytes to the pane instead of key names. The PR text notes iTerm2 3.7 "routes control characters through `-H`" — i.e. this is the **control-mode** input path.
- [psmux#527](https://github.com/psmux/psmux/pull/527) `Implement tmux-compatible resize-window semantics` — open, 2026-08-02.

Those two PRs are exactly, and only, what a remote-viewer product needs from a
multiplexer: **inject arbitrary keystrokes** and **set the window size**. So:

- The Vibe X host app is a **tmux control-mode client** (`tmux -CC`), the same
  contract iTerm2 uses. Output arrives as `%output %<pane> <escaped-bytes>`
  notifications; input goes back as `send-keys -H <hex>`; resize is
  `resize-window`.
- This is what "based on terminal standards, no hooks, no plugins, no shell
  config changes" actually means. It is true, and it is a strong engineering
  choice: session persistence, detach/reattach, scrollback, and multi-client
  attach all come free from a battle-tested daemon that already survives the
  app quitting or crashing.
- It also explains why **Windows is late**: there is no tmux, so they had to go
  fix a Rust reimplementation first. Betting the product on psmux (3.2k stars,
  young) is a real supply-chain dependency.

### 2.2 Four refinements to the mental model

**a) The relay is the boring half; the session owner is the product.** Copying
bytes between two sockets is ~200 lines (see the spike). The hard parts are all
host-side: surviving reattach, repainting a phone screen instantly instead of
replaying megabytes, and reconciling two viewers with different viewports.

**b) "Reattach" and "resume" are different problems, and tmux only solves one.**
Control mode hands you a live `%output` stream, not an addressable one — there
are no byte offsets to resume from. So a returning phone cannot say "give me
everything after byte N"; it has to **resync from a screen snapshot**
(`capture-pane -p -e`) and stream forward. That is the right trade for a
screen-shaped UI and it is why they can claim "会话仍保持原状" (the session looks
just as you left it) rather than "you'll see everything you missed". Products
that want a true scrollback-accurate replay have to buffer the stream
themselves, tagged by offset — which is the design the spike implements and
which tmux does not give you.

**c) "No hooks" and "关键节点会推送到手机" (push at key checkpoints) are in
tension — and this is their most fragile claim.** With no hooks and no plugins,
nothing tells the system that Claude Code just asked for permission to run
`rm -rf`. The only remaining source of truth is the terminal screen, so the
detection is heuristic ANSI/screen scraping, and it breaks every time an agent
CLI restyles its prompts. Every competitor either accepts that fragility or
gives up the "non-invasive" claim (Happy and Omnara both wrap/instrument the
agent instead). **This is the seam where a knowledge-layer product with real
hooks has a structural advantage**, not a marginal one.

**d) A relay is strictly worse for latency than a direct path, and mobile makes
it hurt.** Two TLS hops via a PoP adds RTT, and WSS-over-TCP head-of-line
blocks precisely on the flaky links they advertise handling well. Their answer
is operational (CN PoP selection and tuning, aggressive reconnect); the
architectural answers they have not claimed are QUIC/WebTransport and
Mosh-style local echo prediction, which is what actually makes 200 ms feel
typable. Their pricing meters "带宽" (20/20/100 Mbps) per tier, which suggests
the relay shapes traffic per plan rather than optimising the path per session.

### 2.3 One correction on the security model

"The cloud only transports bytes and ideally never needs your source code" is
the right aspiration but is not what this product can be end-to-end:

- Push notifications and cross-device "progress sync" require *someone* to
  interpret the stream. If that happens in the cloud, the cloud reads your
  terminal. (Doing it host-side and sending small structured events preserves
  E2E — but then you need hooks, back to (c).)
- **File transfer, one-click publish and port forwarding cannot be E2E**: the
  edge terminates TLS for the published URL and proxies plaintext HTTP. Those
  features put the cloud squarely inside the data path.
- So at best the terminal channel is encrypted and the value-added features are
  not. Compare [Happy](https://happy.engineering/docs/security/), which does
  X25519 + AES-256-GCM so the relay demonstrably cannot read the stream, versus
  Omnara, which is explicitly server-readable in exchange for easier
  notifications. Vibe X has not published a crypto design; absent one, assume
  server-readable.

**The threat model that actually matters is not the crypto — it is that this is
a deliberate, always-on RCE channel into a developer machine that bypasses
every inbound control the network has.** Whoever holds a valid web session gets
a shell as you. That makes the load-bearing security features: per-device
pairing and revocation, short-lived scoped attach tokens, an explicit approval
to attach, a cwd/project allowlist, and an audit trail. A stolen Clerk cookie
should not equal a shell, and nothing on the page says it doesn't.

---

## 3. Business read

**The meter tells you what business they think they're in.** Interactive
terminal traffic is tiny — a busy agent session is single-digit KB/s, call it
1–2 MB/hour; 200 hours a month of hard use is well under 1 GB. A 10 GB entry
tier and a 1000 GB top tier are not terminal budgets. They are **file transfer,
port forwarding and publish** budgets. Vibe X is priced as a bandwidth/tunnel
business with a mobile terminal as the acquisition wedge — which is why the tier
axes are devices, concurrent sessions, Mbps and GB rather than seats or repos.

**The moat is not the tunnel.** Cloudflare Tunnel, ngrok, Tailscale, sshx and
ttyd have commoditised NAT traversal, and the relay is a weekend of work. What
is defensible here is (1) CN network operations that actually feel fast on
domestic mobile, (2) mobile UX tuned for the agent approval loop, and (3)
distribution through the VibeCafé community. That is a genuine moat *in that
market* and close to none outside it.

**The strategic risk is first-party.** Claude Code on the web and Codex cloud
already run agents in the vendor's sandbox with a mobile UI. The remaining
reason to relay into your own machine is precisely what those cannot offer:
your repo, your keys, your env, your local services, your uncommitted work.
Any product here should be positioned on *that*, not on "terminal on a phone".

### Landscape

| | Who runs the agent | NAT-free | Relay can read | Mobile UX | Notifications |
| --- | --- | --- | --- | --- | --- |
| **Vibe X** | your Mac/Linux (tmux) | yes, outbound | assume yes | native + PWA, touch bar | yes (screen-derived) |
| **Happy** | your machine (CLI wrapper) | yes | no (X25519/AES-GCM) | native | yes |
| **Omnara** | your machine | yes | yes, by design | web/native | yes |
| **VibeTunnel** | your Mac | via tunnel/LAN | n/a (direct) | browser terminal | no |
| **sshx / ttyd + CF Tunnel** | your machine | yes | yes | raw terminal | no |
| **Tailscale + SSH** | your machine | yes (WireGuard, direct) | no | SSH client | no |
| **Claude Code on the web / Codex cloud** | vendor sandbox | n/a | n/a | first-party | yes |

---

## 4. What is worth stealing, and what isn't

**Steal:**

1. **tmux (and psmux) as the session substrate.** Persistence, detach,
   scrollback and multi-attach for free, no shell instrumentation, credible
   "we don't touch your setup" story.
2. **Outbound-only tunnel, no inbound port, ever.** Non-negotiable; it is the
   entire zero-config claim. (Verified in the spike: the host process holds one
   established socket and zero listeners.)
3. **A viewer that is a PWA first.** Native apps are a distribution detail;
   xterm.js plus a good touch key row (Esc, Ctrl, Tab, arrows — the keys agent
   CLIs actually need) is the product.
4. **Framing it as supervision, not authoring.** "See where the agent got to,
   approve one step, come back and it has moved on" is the honest mobile job.

**Don't:**

1. **Don't meter bandwidth**, and think hard before shipping publish/port
   forwarding at all — that is where the cost, the abuse surface (open proxy,
   phishing pages on your domain) and the loss of E2E all live.
2. **Don't derive notifications from screen scraping** if you have a legitimate
   hook/event source. Fragile, and it silently degrades.
3. **Don't build native mobile apps early.**
4. **Don't ship a relay that can read the stream** without saying so plainly.

Continued in [`dv-remote.md`](dv-remote.md).

---

### Method / confidence

Read: the `/x` marketing page and its Next.js chunks, the VibeCafé home feed,
psmux#524 and #527, psmux's README, and public write-ups of Happy, Omnara and
VibeTunnel. Not read: the host app binary, the native apps, or any wire
traffic — no beta access. So §1 and the psmux findings in §2.1 are evidenced;
the rest of §2 is inference from those findings plus what the claims force, and
§3 is judgement.
