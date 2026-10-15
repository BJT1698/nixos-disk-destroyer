"""Metodi di cancellazione con avanzamento reale.

Le sovrascritture sono fatte direttamente qui (non con dd/shred/scrub): si conoscono i byte scritti,
la fine del disco non e' un errore e piu' dischi possono procedere in parallelo.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from disks import Disk, run

CHUNK = 16 * 1024 * 1024
ZERO = bytes(CHUNK)
ONES = b"\xff" * CHUNK


@dataclass
class Method:
    key: str
    title: str
    detail: str
    passes: list[str] = field(default_factory=list)   # "zero", "ones", "random"
    verify: bool = False
    hardware: bool = False


METHODS: list[Method] = [
    Method("auto", "Automatico (consigliato)",
           "Cancellazione hardware del disco se disponibile (NVMe sanitize/format, ATA Secure Erase), "
           "altrimenti 1 passaggio di dati casuali. Equivale a NIST 800-88 Clear/Purge."),
    Method("hardware", "Solo hardware",
           "NVMe sanitize/format o ATA Secure Erase. Veloce e copre anche le aree nascoste degli SSD. "
           "Fallisce sui dischi che non lo supportano.", hardware=True),
    Method("random", "1 passaggio casuale", "Sovrascrive tutto il disco con dati casuali.", ["random"]),
    Method("zero", "1 passaggio di zeri + verifica",
           "Sovrascrive con zeri e poi controlla un campione di settori.", ["zero"], verify=True),
    Method("shred", "4 passaggi (3 casuali + zeri)",
           "Equivalente a shred -n 3 -z. Lento.", ["random", "random", "random", "zero"], verify=True),
    Method("dod", "DoD 5220.22-M (3 passaggi)",
           "Zeri, uni (0xFF), casuale. Molto lento sui dischi grandi.", ["zero", "ones", "random"]),
    Method("quick", "Rapido (solo tabella partizioni)",
           "Cancella firme e tabella partizioni (+ TRIM se SSD). I dati restano recuperabili.", []),
]
METHOD_BY_KEY = {m.key: m for m in METHODS}

PATTERN_NAME = {"zero": "zeri", "ones": "uni (0xFF)", "random": "casuale"}


class WipeError(Exception):
    pass


@dataclass
class Progress:
    step: str = "In attesa"
    fraction: float | None = 0.0     # None = indeterminato
    speed: float = 0.0               # byte/s
    eta: float | None = None         # secondi
    done: bool = False
    ok: bool = False
    error: str = ""
    log: list[str] = field(default_factory=list)


class Job:
    """Cancellazione di un disco in un thread separato."""

    def __init__(self, disk: Disk, method: Method):
        self.disk = disk
        self.method = method
        self.p = Progress()
        self.lock = threading.Lock()
        self.started = time.time()
        self.ended: float | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def log(self, msg: str) -> None:
        with self.lock:
            self.p.log.append(f"{time.strftime('%H:%M:%S')} {self.disk.name}: {msg}")

    def update(self, **kw) -> None:
        with self.lock:
            for k, v in kw.items():
                setattr(self.p, k, v)

    # ---- esecuzione -------------------------------------------------------------
    def _run(self) -> None:
        try:
            self.log(f"inizio: {self.method.title}")
            self._check()
            if self.method.key == "auto":
                hw = self.disk.hw_methods
                if hw:
                    self._hardware(hw[0])
                else:
                    self.log("nessuna cancellazione hardware disponibile: 1 passaggio casuale")
                    self._overwrite(["random"], verify=False)
            elif self.method.hardware:
                hw = self.disk.hw_methods
                if not hw:
                    raise WipeError("il disco non supporta la cancellazione hardware"
                                    + (" (ATA frozen)" if self.disk.ata_frozen else ""))
                self._hardware(hw[0])
            elif self.method.key == "quick":
                self._quick()
            else:
                self._overwrite(self.method.passes, self.method.verify)
            self._new_label()
            self.ended = time.time()
            self.update(step="Completato", fraction=1.0, eta=0, done=True, ok=True)
            self.log(f"completato in {fmt_time(self.ended - self.started)}")
        except Exception as e:      # noqa: BLE001 - ogni errore va mostrato nella TUI
            self.ended = time.time()
            self.update(step="Errore", done=True, ok=False, error=str(e), eta=None)
            self.log(f"ERRORE: {e}")

    def _check(self) -> None:
        if not os.path.exists(self.disk.path):
            raise WipeError(f"{self.disk.path} non esiste piu'")
        mounted = subprocess.run(["lsblk", "-no", "MOUNTPOINTS", self.disk.path],
                                 capture_output=True, text=True).stdout.split()
        if mounted:
            raise WipeError(f"il disco e' montato ({', '.join(mounted)})")

    # ---- sovrascrittura ---------------------------------------------------------
    def _overwrite(self, passes: list[str], verify: bool) -> None:
        size = self.disk.size
        total = size * len(passes)
        for i, pattern in enumerate(passes):
            label = f"Passaggio {i + 1}/{len(passes)}: {PATTERN_NAME[pattern]}"
            self.update(step=label)
            self.log(label)
            fd = os.open(self.disk.path, os.O_WRONLY)
            try:
                written, last_t, last_w, speed = 0, time.time(), 0, 0.0
                buf = ZERO if pattern == "zero" else ONES if pattern == "ones" else None
                since_sync = 0
                while written < size:
                    n = min(CHUNK, size - written)
                    chunk = buf if buf is not None else os.urandom(CHUNK)
                    data = chunk if n == CHUNK else chunk[:n]
                    w = os.write(fd, data)
                    if w <= 0:
                        raise WipeError(f"scrittura interrotta a {written} byte")
                    written += w
                    since_sync += w
                    if since_sync >= 1 << 30:     # ogni GB svuota la cache: velocita' e avanzamento reali
                        os.fsync(fd)
                        since_sync = 0
                    now = time.time()
                    if now - last_t >= 1.0:
                        inst = (written - last_w) / (now - last_t)
                        speed = inst if speed == 0 else speed * 0.7 + inst * 0.3
                        last_t, last_w = now, written
                        done_all = size * i + written
                        self.update(fraction=done_all / total, speed=speed,
                                    eta=(total - done_all) / speed if speed else None)
                os.fsync(fd)
            except OSError as e:
                raise WipeError(f"errore di scrittura: {e.strerror}") from e
            finally:
                os.close(fd)
        if verify and passes[-1] in ("zero", "ones"):
            self._verify(ZERO if passes[-1] == "zero" else ONES)

    def _verify(self, expected: bytes) -> None:
        self.update(step="Verifica a campione", fraction=None, eta=None)
        self.log("verifica di 2048 blocchi casuali")
        block = 64 * 1024
        rng = random.Random()
        fd = os.open(self.disk.path, os.O_RDONLY)
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
            positions = [0, max(0, self.disk.size - block)] + \
                [rng.randrange(0, max(1, self.disk.size - block)) // 512 * 512 for _ in range(2046)]
            for pos in positions:
                data = os.pread(fd, block, pos)
                if data != expected[:len(data)]:
                    raise WipeError(f"verifica fallita all'offset {pos}")
        finally:
            os.close(fd)
        self.log("verifica superata")

    # ---- rapido -------------------------------------------------------------------
    def _quick(self) -> None:
        self.update(step="Cancello firme e partizioni", fraction=None)
        self._cmd(["wipefs", "-a", "-f", self.disk.path])
        if self.disk.discard:
            self.update(step="TRIM di tutto il disco")
            self._cmd(["blkdiscard", "-f", self.disk.path], ok_codes=(0, 1))

    # ---- hardware -----------------------------------------------------------------
    def _hardware(self, how: str) -> None:
        self.log(f"cancellazione hardware: {how}")
        if how.startswith("sanitize-"):
            self._nvme_sanitize(how.split("-", 1)[1])
        elif how.startswith("format-"):
            ses = "2" if how == "format-crypto" else "1"
            self.update(step=f"NVMe format (SES={ses})", fraction=None)
            self._cmd(["nvme", "format", self.disk.path, f"--ses={ses}", "--force"], timeout=6 * 3600)
        elif how.startswith("ata-"):
            self._ata_erase(enhanced=how == "ata-enhanced")

    def _nvme_sanitize(self, kind: str) -> None:
        action = {"block": "2", "crypto": "4"}[kind]
        self.update(step=f"NVMe sanitize ({kind})", fraction=0.0)
        self._cmd(["nvme", "sanitize", self.disk.nvme_ctrl, f"--sanact={action}"])
        t0 = time.time()
        while True:
            time.sleep(2)
            r = run(["nvme", "sanitize-log", self.disk.nvme_ctrl, "-o", "json"])
            try:
                log = json.loads(r.stdout)
                log = next(iter(log.values())) if isinstance(log, dict) and "sprog" not in log else log
                sprog, sstat = int(log.get("sprog", 0)), int(log.get("sstat", 0))
            except (json.JSONDecodeError, StopIteration, AttributeError, ValueError):
                sprog, sstat = 0, 2
            state = sstat & 0x7
            frac = sprog / 65535
            elapsed = time.time() - t0
            self.update(fraction=frac if state == 2 else 1.0,
                        eta=elapsed / frac - elapsed if 0.01 < frac < 1 else None)
            if state == 1:
                return
            if state == 0 and elapsed > 30:
                raise WipeError("sanitize non avviato dal disco")
            if state == 3:
                raise WipeError("sanitize fallito (stato riportato dal disco)")
            if elapsed > 12 * 3600:
                raise WipeError("sanitize non completato entro 12 ore")

    def _ata_erase(self, enhanced: bool) -> None:
        pw = "MVSwipe"
        est = max(1, self.disk.ata_minutes) * 60
        self._cmd(["hdparm", "--user-master", "u", "--security-set-pass", pw, self.disk.path])
        label = "ATA Enhanced Secure Erase" if enhanced else "ATA Secure Erase"
        self.update(step=label, fraction=0.0)
        proc = subprocess.Popen(
            ["hdparm", "--user-master", "u",
             "--security-erase-enhanced" if enhanced else "--security-erase", pw, self.disk.path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        t0 = time.time()
        while proc.poll() is None:
            time.sleep(1)
            el = time.time() - t0
            self.update(fraction=min(0.99, el / est), eta=max(0, est - el))   # stima del disco
        out = proc.stdout.read() if proc.stdout else ""
        if proc.returncode != 0:
            # senza questo il disco resterebbe bloccato con la password ATA appena impostata
            subprocess.run(["hdparm", "--user-master", "u", "--security-disable", pw, self.disk.path],
                           capture_output=True)
            raise WipeError(f"{label} fallito: {out.strip()[-200:]}")

    # ---- comune -------------------------------------------------------------------
    def _new_label(self) -> None:
        """Lascia il disco con una tabella GPT vuota, pronto per l'uso."""
        self.update(step="Nuova tabella partizioni GPT vuota")
        self._cmd(["wipefs", "-a", "-f", self.disk.path], ok_codes=(0, 1))
        self._cmd(["parted", "-s", self.disk.path, "mklabel", "gpt"])

    def _cmd(self, cmd: list[str], ok_codes=(0,), timeout: int = 3600) -> str:
        self.log("$ " + " ".join(cmd))
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode not in ok_codes:
            raise WipeError(f"{cmd[0]} ha restituito {r.returncode}: {(r.stderr or r.stdout).strip()[-200:]}")
        return r.stdout


def fmt_time(sec: float | None) -> str:
    if sec is None:
        return "--:--"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else f"{m:02d}:{s:02d}"


def fmt_speed(bps: float) -> str:
    return f"{bps / 1e6:,.0f} MB/s".replace(",", ".") if bps else ""
