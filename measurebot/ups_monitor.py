"""Standalone UPS monitor with notifications.

Polls an APC UPS via USB HID and sends alerts via measurebot on power events.

Usage::

    # Single status check
    python -m measurebot.ups_monitor

    # Daemon mode — poll and alert on state changes
    python -m measurebot.ups_monitor --daemon

    # Custom thresholds
    python -m measurebot.ups_monitor --daemon --interval 30 --warn-pct 50 --crit-pct 20

    # JSON output (single read)
    python -m measurebot.ups_monitor --json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from measurebot.ups import UPSReader, UPSStatus

log = logging.getLogger("measurebot.ups_monitor")


class UPSMonitor:
    """Monitors UPS and fires callbacks on state transitions.

    States tracked:
    - ac_present: True/False
    - battery_warn: charge dropped below warn_pct
    - battery_crit: charge dropped below crit_pct

    Callbacks receive (event_name, current_status, message).
    """

    def __init__(
        self,
        reader: UPSReader,
        *,
        warn_pct: int = 50,
        crit_pct: int = 20,
        on_event: callable | None = None,
    ) -> None:
        self.reader = reader
        self.warn_pct = warn_pct
        self.crit_pct = crit_pct
        self.on_event = on_event

        # State tracking
        self._prev_ac: bool | None = None
        self._warn_fired = False
        self._crit_fired = False
        self._battery_since: float | None = None  # timestamp when AC was lost
        self._last_periodic: float = 0

    def check(self) -> UPSStatus:
        """Read UPS and fire events on state changes. Returns current status."""
        status = self.reader.read()
        now = time.time()

        # AC state transition
        if self._prev_ac is not None and status.ac_present != self._prev_ac:
            if not status.ac_present:
                # Lost AC
                self._battery_since = now
                self._warn_fired = False
                self._crit_fired = False
                self._fire(
                    "power_lost",
                    status,
                    f"Power lost! On battery — {status.charge_pct}% charge, "
                    f"{status.runtime_min:.0f} min runtime, {status.input_voltage}V input",
                )
            else:
                # AC restored
                duration = now - self._battery_since if self._battery_since else 0
                self._battery_since = None
                self._warn_fired = False
                self._crit_fired = False
                self._fire(
                    "power_restored",
                    status,
                    f"Power restored after {duration:.0f}s — "
                    f"{status.charge_pct}% charge, {status.input_voltage}V input",
                )

        # Battery threshold warnings (only while on battery)
        if status.on_battery:
            if not self._warn_fired and status.charge_pct <= self.warn_pct:
                self._warn_fired = True
                self._fire(
                    "battery_warn",
                    status,
                    f"Battery warning: {status.charge_pct}% (threshold: {self.warn_pct}%) — "
                    f"{status.runtime_min:.0f} min remaining",
                )

            if not self._crit_fired and status.charge_pct <= self.crit_pct:
                self._crit_fired = True
                self._fire(
                    "battery_crit",
                    status,
                    f"BATTERY CRITICAL: {status.charge_pct}% (threshold: {self.crit_pct}%) — "
                    f"{status.runtime_min:.0f} min remaining",
                )

            # Periodic update while on battery (every 5 min)
            if now - self._last_periodic >= 300:
                duration = now - self._battery_since if self._battery_since else 0
                self._last_periodic = now
                self._fire(
                    "battery_update",
                    status,
                    f"On battery for {duration / 60:.0f} min — "
                    f"{status.charge_pct}%, {status.runtime_min:.0f} min remaining",
                )

        self._prev_ac = status.ac_present
        return status

    def _fire(self, event: str, status: UPSStatus, message: str) -> None:
        """Log and dispatch an event."""
        log.info("[%s] %s", event, message)
        if self.on_event:
            try:
                self.on_event(event, status, message)
            except Exception:
                log.exception("Event callback failed for %s", event)


def _make_alerter():
    """Create an alert callback using measurebot.alerts if configured."""
    try:
        from measurebot.alerts import alert
        return lambda event, status, message: alert(
            f"UPS: {message}", subject=f"UPS {event}"
        )
    except Exception:
        log.warning("measurebot alerts not configured — logging only")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="APC UPS monitor with notifications"
    )
    parser.add_argument(
        "--daemon", action="store_true", help="Run continuously, alert on state changes"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=30,
        metavar="SEC",
        help="Poll interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--warn-pct",
        type=int,
        default=50,
        metavar="PCT",
        help="Low battery warning threshold (default: 50%%)",
    )
    parser.add_argument(
        "--crit-pct",
        type=int,
        default=20,
        metavar="PCT",
        help="Critical battery threshold (default: 20%%)",
    )
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose logging"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    reader = UPSReader()
    try:
        reader.open()
    except Exception as e:
        log.error("Cannot open UPS: %s", e)
        sys.exit(1)

    log.info("Connected: %s (S/N: %s)", reader.product, reader.serial)

    if not args.daemon:
        # Single read
        status = reader.read()
        if args.json:
            print(json.dumps(status.to_dict()))
        else:
            print(status.summary())
        reader.close()
        return

    # Daemon mode
    alerter = _make_alerter()
    monitor = UPSMonitor(
        reader,
        warn_pct=args.warn_pct,
        crit_pct=args.crit_pct,
        on_event=alerter,
    )

    log.info(
        "Monitoring every %gs — warn at %d%%, critical at %d%%",
        args.interval,
        args.warn_pct,
        args.crit_pct,
    )

    try:
        while True:
            try:
                status = monitor.check()
                log.debug("%s", status.oneliner())
            except Exception:
                log.exception("UPS read failed")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log.info("Stopped.")
    finally:
        reader.close()


if __name__ == "__main__":
    main()
