"""Small sd_notify implementation; no optional Python/systemd dependency."""
import os
import socket


def notify(message):
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return False  # Normal when run directly from a terminal.
    if address.startswith("@"):
        address = "\0" + address[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
        client.settimeout(1)
        client.connect(address)
        client.sendall(message.encode())
    return True
