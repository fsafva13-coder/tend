"""Start Tend with one command:  python run.py

Starts the MCP server and the digital twin, waits until both are ready,
opens the page in your browser, and stops both when you press Ctrl+C.
"""

import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent
SERVER_PORT, TWIN_PORT = 8000, 8080
URL = f"http://127.0.0.1:{TWIN_PORT}"


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for(port: int, name: str, proc: subprocess.Popen, seconds: int = 30) -> None:
    for _ in range(seconds * 5):
        if proc.poll() is not None:
            sys.exit(f"{name} stopped unexpectedly. Run it on its own to see the error.")
        if port_open(port):
            return
        time.sleep(0.2)
    sys.exit(f"{name} did not start within {seconds} seconds.")


def main() -> None:
    for port, name in ((SERVER_PORT, "MCP server"), (TWIN_PORT, "digital twin")):
        if port_open(port):
            sys.exit(f"Port {port} is already in use. Is the {name} already running? "
                     "Close the other terminal first.")

    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    server = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, **quiet)
    twin = None
    try:
        print("Starting the Tend MCP server ...")
        wait_for(SERVER_PORT, "The MCP server", server)
        twin = subprocess.Popen([sys.executable, "twin/app.py"], cwd=ROOT, **quiet)
        print("Starting the digital twin ...")
        wait_for(TWIN_PORT, "The digital twin", twin)

        print(f"\nTend is running. Opening {URL}")
        print("Keep this window open. Press Ctrl+C to stop.\n")
        webbrowser.open(URL)
        while server.poll() is None and twin.poll() is None:
            time.sleep(0.5)
        print("One of the programs stopped; shutting down.")
    except KeyboardInterrupt:
        print("\nStopping Tend ...")
    finally:
        for proc in (twin, server):
            if proc and proc.poll() is None:
                proc.terminate()
        for proc in (twin, server):
            if proc:
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        print("Tend stopped.")


if __name__ == "__main__":
    main()
