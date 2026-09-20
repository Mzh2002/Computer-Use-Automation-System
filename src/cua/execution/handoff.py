"""Terminal operator UI. The browser stays live and continues dispatching events."""

import queue
import threading
import time


def terminal_handoff(surface, reason: str) -> bool:
    print(f"\nAutomation paused: {reason}. Use the SAME open browser to resolve it.")
    print("Type resume when ready, or abort to stop. Operator timeout: 5 minutes.")
    answers = queue.Queue()

    def read():
        try:
            answers.put(input("operator> ").strip().lower())
        except EOFError:
            answers.put("abort")

    threading.Thread(target=read, daemon=True).start()
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        surface.page.wait_for_timeout(100)
        try:
            return answers.get_nowait() == "resume"
        except queue.Empty:
            pass
    return False
