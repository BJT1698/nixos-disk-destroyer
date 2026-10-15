"""Rilevamento dei dischi e delle loro capacita' di cancellazione (software e hardware)."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field

EXCLUDED_PREFIXES = ("loop", "sr", "zram", "ram", "dm-", "md", "fd", "nbd")


def run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


@dataclass
class Disk:
    name: str                      # sda, nvme0n1
    path: str                      # /dev/sda
    size: int                      # byte
    model: str = ""
    serial: str = ""
    transport: str = ""            # sata, nvme, usb, virtio...
    rotational: bool = False
    removable: bool = False
    mounted: list[str] = field(default_factory=list)
    discard: bool = False
    # NVMe
    nvme_ctrl: str = ""            # /dev/nvme0
    sanitize: list[str] = field(default_factory=list)   # "crypto", "block", "overwrite"
    format_crypto: bool = False
    format_ok: bool = False
    # ATA
    ata_security: bool = False
    ata_frozen: bool = False
    ata_enhanced: bool = False
    ata_minutes: int = 0

    @property
    def kind(self) -> str:
        if self.name.startswith("nvme"):
            return "NVMe"
        if self.transport == "usb":
            return "USB"
        return "HDD" if self.rotational else "SSD"

    @property
    def size_text(self) -> str:
        return human_size(self.size)

    @property
    def hw_methods(self) -> list[str]:
        """Metodi di cancellazione hardware utilizzabili, dal piu' al meno preferibile."""
        m = []
        if self.nvme_ctrl:
            m += [f"sanitize-{s}" for s in ("crypto", "block") if s in self.sanitize]
            if self.format_ok:
                m += ["format-crypto"] if self.format_crypto else []
                m += ["format-user"]
        if self.ata_security and not self.ata_frozen:
            m += ["ata-enhanced"] if self.ata_enhanced else []
            m += ["ata-erase"]
        return m

    @property
    def hw_text(self) -> str:
        if self.nvme_ctrl:
            parts = [f"sanitize {'/'.join(self.sanitize)}"] if self.sanitize else []
            if self.format_ok:
                parts.append("format crypto" if self.format_crypto else "format")
            return ", ".join(parts) or "no"
        if self.ata_security:
            txt = "Secure Erase" + (" enh." if self.ata_enhanced else "")
            return txt + (" (frozen)" if self.ata_frozen else "")
        return "no"


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1000 or unit == "PB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} PB"


def _mountpoints(dev: dict) -> list[str]:
    mps = [m for m in (dev.get("mountpoints") or []) if m]
    for child in dev.get("children") or []:
        mps += _mountpoints(child)
    return mps


def _nvme_caps(disk: Disk) -> None:
    m = re.match(r"(nvme\d+)n\d+", disk.name)
    if not m:
        return
    disk.nvme_ctrl = f"/dev/{m.group(1)}"
    r = run(["nvme", "id-ctrl", disk.nvme_ctrl, "-o", "json"])
    if r.returncode != 0:
        return
    try:
        ctrl = json.loads(r.stdout)
    except json.JSONDecodeError:
        return
    sanicap = int(ctrl.get("sanicap", 0))
    disk.sanitize = [n for bit, n in ((0, "crypto"), (1, "block"), (2, "overwrite")) if sanicap & (1 << bit)]
    oacs, fna = int(ctrl.get("oacs", 0)), int(ctrl.get("fna", 0))
    disk.format_ok = bool(oacs & 0x2)
    disk.format_crypto = bool(fna & 0x4)


def _ata_caps(disk: Disk) -> None:
    if disk.transport not in ("sata", "ata") and not disk.name.startswith("sd"):
        return
    r = run(["hdparm", "-I", disk.path])
    if r.returncode != 0 or "Security:" not in r.stdout:
        return
    sec = r.stdout.split("Security:", 1)[1]
    sec = sec.split("Logical Unit WWN", 1)[0].split("Checksum", 1)[0]
    lines = [l.strip() for l in sec.splitlines()]
    disk.ata_security = "supported" in lines
    disk.ata_frozen = "frozen" in lines          # "not frozen" e' una riga diversa
    disk.ata_enhanced = "supported: enhanced erase" in lines
    m = re.search(r"(\d+)min for SECURITY ERASE UNIT", sec)
    disk.ata_minutes = int(m.group(1)) if m else 0
    if disk.ata_enhanced:
        m = re.search(r"(\d+)min for ENHANCED SECURITY ERASE UNIT", sec)
        disk.ata_minutes = int(m.group(1)) if m else disk.ata_minutes


def scan() -> list[Disk]:
    r = run(["lsblk", "-J", "-b", "-o",
             "NAME,PATH,TYPE,SIZE,MODEL,SERIAL,ROTA,TRAN,RM,DISC-MAX,MOUNTPOINTS"])
    data = json.loads(r.stdout or '{"blockdevices": []}')
    disks: list[Disk] = []
    for dev in data.get("blockdevices", []):
        name = dev.get("name", "")
        if dev.get("type") != "disk" or name.startswith(EXCLUDED_PREFIXES) or not dev.get("size"):
            continue
        d = Disk(
            name=name,
            path=dev.get("path") or f"/dev/{name}",
            size=int(dev["size"]),
            model=(dev.get("model") or "").strip(),
            serial=(dev.get("serial") or "").strip(),
            transport=(dev.get("tran") or "").strip(),
            rotational=bool(dev.get("rota")),
            removable=bool(dev.get("rm")),
            mounted=_mountpoints(dev),
            discard=int(dev.get("disc-max") or 0) > 0,
        )
        try:
            _nvme_caps(d)
            _ata_caps(d)
        except (OSError, subprocess.TimeoutExpired):
            pass
        disks.append(d)
    return disks
