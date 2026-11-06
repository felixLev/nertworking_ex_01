##### DO NOT MODIFY THIS FILE #####

"""Entry point for the Sockets Bank GUI client.

Creates the Connection used for all server communication, then launches the GUI.

Usage:
    python client.py [--host 127.0.0.1] [--port 5050]
"""
from __future__ import annotations

import argparse

from connection import Connection
from gui import BankApp


def main() -> None:
    parser = argparse.ArgumentParser(description="Sockets Bank GUI client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5050)
    args = parser.parse_args()

    connection = Connection()
    app = BankApp(connection, host=args.host, port=args.port)
    app.mainloop()


if __name__ == "__main__":
    main()
