"""Small desktop UI showing the Remoteable server address."""

from __future__ import annotations

import subprocess
import webbrowser
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from subprocess import Popen

import tkinter as tk
from tkinter import ttk


def copy_to_clipboard(root: tk.Tk, text: str) -> None:
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()


class RemoteableStatusWindow:
    def __init__(self, url: str, display: str, process: Popen[str]) -> None:
        self.url = url
        self.process = process

        self.root = tk.Tk()
        self.root.title("Remoteable")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)

        frame = ttk.Frame(self.root, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Remoteable is running", font=("", 13, "bold")).grid(
            row=0, column=0, columnspan=2, pady=(0, 8)
        )

        self.status = ttk.Label(frame, text="Click the address to open or copy it.")
        self.status.grid(row=1, column=0, columnspan=2, pady=(0, 12))

        self.address = tk.Label(
            frame,
            text=url,
            fg="#0066cc",
            cursor="hand2",
            font=("", 14, "underline"),
        )
        self.address.grid(row=2, column=0, columnspan=2, pady=(0, 16))
        self.address.bind("<Button-1>", self._open_url)

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=2)

        ttk.Button(buttons, text="Copy Address", command=self._copy_url).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(buttons, text="Quit", command=self._quit).grid(row=0, column=1)

        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        self.root.after(2000, self._watch_server)

    def _open_url(self, _event: object | None = None) -> None:
        webbrowser.open(self.url)

    def _copy_url(self) -> None:
        copy_to_clipboard(self.root, self.url)
        self.status.configure(text="Address copied to clipboard.")

    def _watch_server(self) -> None:
        if self.process.poll() is not None:
            code = self.process.returncode
            self.status.configure(
                text=f"Server stopped unexpectedly (exit code {code})."
            )
            self.root.after(3000, self.root.destroy)
            return
        self.root.after(2000, self._watch_server)

    def _quit(self) -> None:
        from engine.serve import stop_daphne

        stop_daphne(self.process)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def run(url: str, display: str, process: Popen[str]) -> None:
    RemoteableStatusWindow(url, display, process).run()
