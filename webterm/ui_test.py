"""Drives the real UI in a real browser: tabs, typing, restore-after-close.

    cd webterm && uv run --with aiohttp --with playwright python ui_test.py

Writes screenshots next to the docs so the PR can show what it looks like.
Set CHROME to override the browser binary.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

HERE = Path(__file__).parent
SHOTS = HERE.parent / "docs" / "assets"
CHROME = os.environ.get("CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
TOKEN = "ui-test-token"
ROWS = ".term.active .xterm-rows"

results: list[tuple[bool, str]] = []


def check(ok: object, label: str) -> None:
    results.append((bool(ok), label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}", flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_port(port: int, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise TimeoutError("server never came up")


def screen_text(page: Page) -> str:
    return page.inner_text(ROWS)


def type_into_terminal(page: Page, text: str) -> None:
    page.click(".term.active .xterm-screen")
    page.keyboard.type(text)
    page.keyboard.press("Enter")


def wait_for_match(page: Page, pattern: str, timeout: float = 10.0) -> str | None:
    """Wait for a regex, not a substring — a bare marker also matches the shell's
    own echo of the command that produces it, which races."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = re.search(pattern, screen_text(page), re.M)
        if found:
            return found.group(1)
        page.wait_for_timeout(100)
    return None


def wait_for_text(page: Page, needle: str, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if needle in screen_text(page):
            return True
        page.wait_for_timeout(100)
    return False


def run(url: str) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])

        print("\n1) the page boots straight into a usable terminal", flush=True)
        desktop = browser.new_context(viewport={"width": 1280, "height": 800})
        page = desktop.new_page()
        page.goto(url)
        page.wait_for_selector(ROWS, timeout=15000)
        check(page.locator(".tab").count() == 1, "one session was auto-created")
        page.wait_for_function("() => document.querySelector('#status').dataset.state === 'online'", timeout=10000)
        check(page.locator("#status").get_attribute("data-state") == "online", "the socket reports connected")

        type_into_terminal(page, "echo HELLO_FROM_BROWSER")
        check(wait_for_text(page, "HELLO_FROM_BROWSER"), "typing runs a command and the output renders")
        type_into_terminal(page, "echo pid=$$")
        pid_before = wait_for_match(page, r"^pid=(\d+)\s*$")
        check(pid_before, f"the shell reports its pid ({pid_before})")

        print("\n2) tabs open, switch, and are independent", flush=True)
        page.click("#new-tab")
        page.wait_for_selector("#profiles li button")
        page.click("#profiles li button")  # first profile = the default shell
        page.wait_for_function("() => document.querySelectorAll('.tab').length === 2", timeout=10000)
        check(page.locator(".tab").count() == 2, "a second tab opened")
        type_into_terminal(page, "echo SECOND_TAB_OUTPUT")
        check(wait_for_text(page, "SECOND_TAB_OUTPUT"), "the new tab runs its own shell")
        check("HELLO_FROM_BROWSER" not in screen_text(page), "the two tabs do not share a screen")

        page.screenshot(path=str(SHOTS / "webterm-desktop.png"))

        first_tab = page.locator(".tab .label").first
        first_tab.click()
        page.wait_for_timeout(300)
        check("HELLO_FROM_BROWSER" in screen_text(page), "switching back shows the first session's scrollback")

        print("\n3) close the browser, open it again — sessions are still there", flush=True)
        desktop.close()  # every tab gone, localStorage gone, cookies gone
        fresh = browser.new_context(viewport={"width": 1280, "height": 800})
        page2 = fresh.new_page()
        page2.goto(url)
        page2.wait_for_selector(ROWS, timeout=15000)
        page2.wait_for_function("() => document.querySelectorAll('.tab').length === 2", timeout=10000)
        check(page2.locator(".tab").count() == 2, "both sessions were restored, not recreated")
        check(wait_for_text(page2, "HELLO_FROM_BROWSER"), "the restored tab is repainted with its scrollback")
        page2.wait_for_timeout(600)
        # Once for the echoed command line, once for its output. Any more means
        # the scrollback got painted twice — boot() and ws.onopen both attaching.
        painted = screen_text(page2).count("HELLO_FROM_BROWSER")
        check(painted == 2, f"scrollback painted exactly once (found the marker {painted}x, expected 2)")

        print("\n4) the shell is the same process, not a new one", flush=True)
        type_into_terminal(page2, "echo pid=$$")
        pid_after = wait_for_match(page2, r"^pid=(\d+)\s*$")
        check(pid_after, "the restored session accepts input")
        pids = set(re.findall(r"^pid=(\d+)\s*$", screen_text(page2), re.M))
        check(
            pid_after == pid_before and pids == {pid_before},
            f"same shell process before and after the browser restart ({pid_before} vs {sorted(pids)})",
        )

        print("\n5) a dropped connection reconnects by itself", flush=True)
        page2.evaluate("() => window.dispatchEvent(new Event('offline'))")
        page2.evaluate("() => app.ws.close()")
        page2.wait_for_function("() => document.querySelector('#status').dataset.state !== 'online'", timeout=5000)
        check(True, "the status pill drops out of 'connected'")
        page2.wait_for_function("() => document.querySelector('#status').dataset.state === 'online'", timeout=15000)
        check(page2.locator("#status").get_attribute("data-state") == "online", "it reconnects with no user action")
        type_into_terminal(page2, "echo AFTER_RECONNECT")
        check(wait_for_text(page2, "AFTER_RECONNECT"), "the session is usable again after reconnecting")
        fresh.close()

        print("\n6) touch layout gets a key row", flush=True)
        phone = browser.new_context(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=2
        )
        page3 = phone.new_page()
        page3.goto(url)
        page3.wait_for_selector(ROWS, timeout=15000)
        check(page3.locator("#keys").is_visible(), "the esc/ctrl/arrows row is shown on touch devices")
        page3.tap(".term.active .xterm-screen")
        page3.keyboard.type("printf 'phone %s\\n' ok")
        page3.keyboard.press("Enter")
        check(wait_for_text(page3, "phone ok"), "typing works in the mobile layout")
        page3.wait_for_timeout(400)
        page3.screenshot(path=str(SHOTS / "webterm-mobile.png"))
        phone.close()
        browser.close()


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "server.py", "--port", str(port), "--token", TOKEN, "--command", "/bin/bash"],
        cwd=HERE,
    )
    try:
        wait_for_port(port)
        run(f"http://127.0.0.1:{port}/?token={TOKEN}")
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    for label in failed:
        print(f"  FAILED: {label}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
