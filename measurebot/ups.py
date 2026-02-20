"""APC UPS status reader via USB HID.

Reads UPS data directly from APC Back-UPS units using HID feature reports.
No special drivers needed — works with the built-in OS HID driver.

Requires the ``hidapi`` package::

    pip install hidapi

Tested on APC Back-UPS RS 1500G. Report IDs likely work across the
Back-UPS USB family (VID 0x051D, PID 0x0002).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

try:
    import hid
except ImportError:
    hid = None  # type: ignore[assignment]

APC_VID = 0x051D
APC_PID = 0x0002

# HID feature report definitions
# Report ID -> (human name, byte count after ID, decode function name)
_REPORTS = {
    0x22: "charge_pct",
    0x23: "runtime_sec",
    0x26: "battery_voltage_raw",
    0x25: "battery_nominal_voltage_raw",
    0x31: "input_voltage",
    0x30: "input_nominal_voltage",
    0x32: "low_transfer_voltage",
    0x33: "high_transfer_voltage",
    0x16: "status_raw",
    0x36: "last_transfer_cause",
    0x35: "sensitivity",
    0x21: "self_test_result",
}

# Reports that decode as uint16 LE (all others are uint8)
_U16_REPORTS = {0x23, 0x26, 0x25, 0x31, 0x32, 0x33}

TRANSFER_CAUSES = {
    0: "No transfer",
    1: "High line voltage",
    2: "Brownout",
    3: "Blackout",
    4: "Small sag",
    5: "Large sag",
    6: "Small spike",
    7: "Large spike",
    8: "Self test",
    9: "Rate of voltage change",
}


@dataclass
class UPSStatus:
    """Decoded UPS status snapshot."""

    timestamp: float = field(default_factory=time.time)

    # Power state
    ac_present: bool = True
    charging: bool = False

    # Battery
    charge_pct: int = 0
    runtime_sec: int = 0
    battery_voltage: float = 0.0
    battery_nominal_voltage: float = 0.0

    # Input
    input_voltage: int = 0
    input_nominal_voltage: int = 0
    low_transfer_voltage: int = 0
    high_transfer_voltage: int = 0

    # Raw status
    status_raw: int = 0
    last_transfer_cause: int = 0
    sensitivity: int = 0
    self_test_result: int = 0

    @property
    def on_battery(self) -> bool:
        return not self.ac_present

    @property
    def runtime_min(self) -> float:
        return self.runtime_sec / 60.0

    @property
    def status_str(self) -> str:
        if not self.ac_present:
            return "ON BATTERY"
        if self.charge_pct >= 100:
            return "ONLINE"
        return "ONLINE (charging)"

    @property
    def transfer_cause_str(self) -> str:
        return TRANSFER_CAUSES.get(self.last_transfer_cause, f"Unknown ({self.last_transfer_cause})")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["on_battery"] = self.on_battery
        d["runtime_min"] = self.runtime_min
        d["status_str"] = self.status_str
        d["transfer_cause_str"] = self.transfer_cause_str
        return d

    def summary(self) -> str:
        lines = [
            f"Status:    {self.status_str}",
            f"Charge:    {self.charge_pct}%",
            f"Runtime:   {self.runtime_min:.1f} min ({self.runtime_sec} sec)",
            f"Batt V:    {self.battery_voltage:.2f}V (nominal {self.battery_nominal_voltage:.2f}V)",
            f"Input V:   {self.input_voltage}V (nominal {self.input_nominal_voltage}V)",
            f"Transfer:  {self.low_transfer_voltage}V low / {self.high_transfer_voltage}V high",
        ]
        return "\n".join(lines)

    def oneliner(self) -> str:
        state = "BATT" if self.on_battery else "AC"
        return f"[{state}] {self.charge_pct}% | {self.runtime_min:.0f}min | {self.input_voltage}V in | {self.battery_voltage:.1f}V batt"


class UPSReader:
    """Reads status from an APC UPS via USB HID.

    Usage::

        reader = UPSReader()
        reader.open()
        status = reader.read()
        print(status.summary())
        reader.close()

    Or as a context manager::

        with UPSReader() as reader:
            status = reader.read()
    """

    def __init__(self, vid: int = APC_VID, pid: int = APC_PID) -> None:
        if hid is None:
            raise ImportError(
                "hidapi is required for UPS monitoring. Install with: pip install hidapi"
            )
        self.vid = vid
        self.pid = pid
        self._dev: hid.device | None = None
        self.product: str = ""
        self.serial: str = ""

    def open(self) -> None:
        """Open the HID device."""
        dev = hid.device()
        dev.open(self.vid, self.pid)
        self.product = dev.get_product_string() or ""
        self.serial = (dev.get_serial_number_string() or "").strip()
        self._dev = dev

    def close(self) -> None:
        """Close the HID device."""
        if self._dev is not None:
            self._dev.close()
            self._dev = None

    def __enter__(self) -> UPSReader:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _feat(self, report_id: int) -> list[int]:
        """Read a HID feature report."""
        if self._dev is None:
            raise RuntimeError("UPS device not open")
        return self._dev.get_feature_report(report_id, 8)

    def read(self) -> UPSStatus:
        """Read all status reports and return decoded status."""
        raw: dict[str, int] = {}
        for report_id, name in _REPORTS.items():
            data = self._feat(report_id)
            if report_id in _U16_REPORTS:
                raw[name] = data[1] | (data[2] << 8) if len(data) >= 3 else 0
            else:
                raw[name] = data[1] if len(data) >= 2 else 0

        status_byte = raw["status_raw"]
        # Bit 0 of the status byte tracks "charging", not "AC present".
        # When battery is full (100%), bit 0 clears even though AC is still on.
        # Use input voltage as the reliable AC indicator: mains voltage > 0 means AC present.
        # A true outage reads 0V input.
        input_v = raw["input_voltage"]
        ac_present = input_v > 0
        charging = bool(status_byte & 0x01)

        return UPSStatus(
            ac_present=ac_present,
            charging=charging,
            charge_pct=raw["charge_pct"],
            runtime_sec=raw["runtime_sec"],
            battery_voltage=raw["battery_voltage_raw"] / 100.0,
            battery_nominal_voltage=raw["battery_nominal_voltage_raw"] / 100.0,
            input_voltage=raw["input_voltage"],
            input_nominal_voltage=raw["input_nominal_voltage"],
            low_transfer_voltage=raw["low_transfer_voltage"],
            high_transfer_voltage=raw["high_transfer_voltage"],
            status_raw=status_byte,
            last_transfer_cause=raw["last_transfer_cause"],
            sensitivity=raw["sensitivity"],
            self_test_result=raw["self_test_result"],
        )
