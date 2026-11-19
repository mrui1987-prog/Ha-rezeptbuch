#!/usr/bin/env python3
"""Waagen-Simulator: Waveshare-Ersatz mit KERN-Waage per TCP (docs/waage.md 8, K07-7).

Verhält sich wie ein Waveshare im Modus TCP-Server mit angeschlossener KERN
KFB-TM im Sendemodus CONT: sendet 10 Zeilen je Sekunde an alle verbundenen
Gegenstellen und führt `T` (Tara) und `Z` (Nullstellen) aus. Nutzt denselben
Simulator-Kern wie der Treiber `simulator` des Add-ons.

Aufruf (Python 3.11 oder neuer, keine weiteren Pakete):

    python simulator.py                 # Ablauf in Schleife, Port 8899
    python simulator.py --fest 2500     # festes Gewicht 2 500 g
    python simulator.py --port 9000 --host 127.0.0.1

Im Add-on dann „Anbindung“ `tcp`, „Adresse des Waveshare“ = Adresse dieses
Rechners, „TCP-Port“ = Port. Beenden mit Strg+C.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "rezeptbuch_waage"))

from app.simulator import LINE_INTERVAL_S, Phase, SimulatedScale  # noqa: E402

DEFAULT_PORT = 8899
COMMANDS = {"T": "tare", "Z": "zero"}
MAX_BUFFER = 64

log = logging.getLogger("waagen_simulator")


class FixedScale(SimulatedScale):
    """Festes Gewicht, immer stabil (zum Prüfen von Tara/Nullstellen von Hand)."""

    def __init__(self, weight_g: int) -> None:
        super().__init__()
        self._phase = Phase(0, float("inf"), "steady", weight_g, weight_g)

    def phase_at(self, t: float) -> Phase:  # type: ignore[override]
        return self._phase


class FakeWaveshare:
    """TCP-Server: verteilt die Zeilen der simulierten Waage, nimmt T/Z an."""

    def __init__(self, scale: SimulatedScale, interval_s: float = LINE_INTERVAL_S,
                 clock=time.monotonic) -> None:
        self.scale = scale
        self.interval_s = interval_s
        self.clock = clock
        self.start = clock()
        self.clients: set[asyncio.StreamWriter] = set()
        self.commands: list[str] = []   # ausgeführte Befehle (für Tests)

    def now(self) -> float:
        return self.clock() - self.start

    def execute(self, token: str) -> None:
        cmd = COMMANDS.get(token.strip().upper())
        if cmd is None:
            if token.strip():
                log.info("Unbekannter Befehl %r ignoriert", token)
            return
        getattr(self.scale, cmd)(self.now())
        self.commands.append(cmd)
        log.info("Befehl %s → %s", token.strip(), "Tara" if cmd == "tare" else "Nullstellen")

    async def handle_client(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        log.info("Verbunden: %s", peer)
        self.clients.add(writer)
        buffer = ""
        try:
            while True:
                data = await reader.read(256)
                if not data:
                    break
                buffer += data.decode("ascii", errors="replace")
                *lines, buffer = buffer.replace("\r", "\n").split("\n")
                for line in lines:
                    self.execute(line)
                # Die Waage nimmt T/Z auch ohne CR LF an (Feldtest, Widerspruch 8)
                if buffer.strip().upper() in COMMANDS:
                    self.execute(buffer)
                    buffer = ""
                if len(buffer) > MAX_BUFFER:
                    buffer = ""
        except (ConnectionError, OSError):
            pass
        finally:
            self.clients.discard(writer)
            writer.close()
            log.info("Getrennt: %s", peer)

    def current_line(self) -> str | None:
        return self.scale.line(self.now())

    async def ticker(self) -> None:
        while True:
            line = self.current_line()
            if line is not None:
                data = (line + "\r\n").encode("ascii")
                for writer in list(self.clients):
                    if writer.is_closing():
                        self.clients.discard(writer)
                        continue
                    writer.write(data)
            await asyncio.sleep(self.interval_s)

    async def serve(self, host: str, port: int) -> asyncio.Server:
        server = await asyncio.start_server(self.handle_client, host, port)
        self._ticker = asyncio.create_task(self.ticker())
        return server

    async def close(self, server: asyncio.Server) -> None:
        self._ticker.cancel()
        for writer in list(self.clients):
            writer.close()
        server.close()
        await server.wait_closed()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Waveshare-Ersatz mit simulierter KERN-Waage (Sendemodus CONT).")
    p.add_argument("--host", default="0.0.0.0",
                   help="Adresse, auf der gelauscht wird (Standard 0.0.0.0 = alle)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help=f"TCP-Port (Standard {DEFAULT_PORT}, wie Waveshare ab Werk)")
    p.add_argument("--fest", type=int, metavar="GRAMM",
                   help="festes Gewicht in Gramm statt des 60-s-Ablaufs")
    p.add_argument("--seed", type=int, default=7, help="Startwert für das Schwanken")
    p.add_argument("-v", "--verbose", action="store_true", help="jede Sekunde die aktuelle Zeile zeigen")
    return p.parse_args(argv)


async def run(args: argparse.Namespace) -> None:
    scale = FixedScale(args.fest) if args.fest is not None else SimulatedScale(args.seed)
    sim = FakeWaveshare(scale)
    server = await sim.serve(args.host, args.port)
    what = (f"festes Gewicht {args.fest} g" if args.fest is not None
            else "Ablauf 60 s (Befüllen, `-----`, 8 s Ausfall)")
    log.info("Waagen-Simulator auf %s:%s – %s. Beenden mit Strg+C.",
             args.host, args.port, what)
    if args.verbose:
        async def show():
            while True:
                log.info("→ %s", sim.current_line())
                await asyncio.sleep(1)
        asyncio.create_task(show())
    try:
        await asyncio.Event().wait()
    finally:
        await sim.close(server)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        log.info("Beendet")


if __name__ == "__main__":
    main()
