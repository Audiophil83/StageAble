"""Run a deterministic development X32 OSC simulator."""

from __future__ import annotations

import math
import socket
import struct
import time

from django.core.management.base import BaseCommand
from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.osc_packet import OscPacket

from engine.x32.parameters import CHANNEL_NAME_ADDRESSES, PARAMETERS


class Command(BaseCommand):
    help = "Run a control-only X32 OSC simulator on UDP port 10023"

    def add_arguments(self, parser):
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=10023)

    def handle(self, *args, **options):
        host, port = options["host"], options["port"]
        values = {parameter.address: 0.5 for parameter in PARAMETERS}
        values.update({address: f"CH {channel:02d}" for address, channel in CHANNEL_NAME_ADDRESSES.items()})
        values.update({f"/-ha/{ch:02d}/index": ch for ch in range(32)})
        values.update({f"/headamp/{ch:03d}/phantom": 0 for ch in range(32)})
        clients: dict[tuple[str, int], float] = {}
        meter_clients: dict[tuple[str, int], float] = {}
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((host, port))
        sock.settimeout(0.05)
        self.stdout.write(self.style.SUCCESS(f"X32 simulator listening on {host}:{port}"))
        self.stdout.write(
            "Point StageAble at this address. Identity probes are available for diagnostics, "
            "but full X32-Edit synchronization is not implemented. Press Ctrl-C to stop."
        )
        next_meter = time.monotonic()

        try:
            while True:
                now = time.monotonic()
                try:
                    data, sender = sock.recvfrom(65535)
                    for timed in OscPacket(data).messages:
                        message = timed.message
                        address = message.address
                        params = list(message.params)
                        if address == "/info":
                            self._send(sock, sender, "/info", "V2.10", "osc-server", "X32", "4.06")
                        elif address == "/xinfo":
                            self._send(
                                sock,
                                sender,
                                "/xinfo",
                                host,
                                "StageAble-X32-Sim",
                                "X32",
                                "4.06",
                            )
                        elif address == "/status":
                            self._send(sock, sender, "/status", "active", host, "osc-server")
                        elif address == "/xremote":
                            clients[sender] = now + 10.0
                        elif address == "/meters":
                            meter_clients[sender] = now + 10.0
                        elif address in values:
                            if params:
                                values[address] = params[0]
                                self._send(sock, sender, address, params[0])
                                for client, expiry in list(clients.items()):
                                    if expiry > now and client != sender:
                                        self._send(sock, client, address, params[0])
                            else:
                                self._send(sock, sender, address, values[address])
                except socket.timeout:
                    pass

                if now >= next_meter:
                    levels = [max(0.0, min(1.0, 0.25 + 0.2 * math.sin(now * 2 + i))) for i in range(32)]
                    blob = struct.pack("<I32f", 32, *levels)
                    for client, expiry in list(meter_clients.items()):
                        if expiry > now:
                            self._send(sock, client, "/meters/1", blob)
                        else:
                            meter_clients.pop(client, None)
                    for client, expiry in list(clients.items()):
                        if expiry <= now:
                            clients.pop(client, None)
                    next_meter = now + 0.1
        except KeyboardInterrupt:
            self.stdout.write("X32 simulator stopped")
        finally:
            sock.close()

    @staticmethod
    def _send(sock, target, address, *args):
        builder = OscMessageBuilder(address=address)
        for arg in args:
            builder.add_arg(arg)
        sock.sendto(builder.build().dgram, target)
