"""Disposable loopback server shared by tests and the one-command demo."""

import socket
import threading
import time
from pathlib import Path

import uvicorn

from test_environment.app import create_app, reset


class LabServer:
    def __init__(self, database: Path):
        self.database = database

    def __enter__(self):
        reset(self.database)
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        port = self.socket.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        config = uvicorn.Config(
            create_app(self.database),
            host="127.0.0.1",
            port=port,
            access_log=False,
            log_level="error",
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True
        )
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                self.server.should_exit = True
                self.socket.close()
                raise RuntimeError("Local sandbox failed to start")
            time.sleep(0.02)
        return self

    def __exit__(self, *args):
        self.server.should_exit = True
        self.thread.join(timeout=5)
        self.socket.close()
