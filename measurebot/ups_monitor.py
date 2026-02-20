"""Standalone UPS monitor with notifications.

Polls an APC UPS via USB HID and sends alerts via measurebot on power events.

Usage::

    # Single status check
    python -m measurebot.ups_monitor

    # Daemon mode with config file
    python -m measurebot.ups_monitor --daemon --config ups_monitor.json

    # Daemon mode with CLI overrides
    python -m measurebot.ups_monitor --daemon --config ups_monitor.json --poll-interval 10

    # JSON output (single read)
    python -m measurebot.ups_monitor --json

Config file example (JSON)::

    {
        "poll_interval": 30,
        "email": ["aaron@aaronsharpe.science", "zack.gomez@gmail.com"],
        "warn": {
            "battery_pct": 50,
            "on_battery_min": 5,
            "runtime_min": 30
        },
        "crit": {
            "battery_pct": 20,
            "on_battery_min": 10,
            "runtime_min": 10
        }
    }
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from measurebot.ups import UPSReader, UPSStatus

log = logging.getLogger("measurebot.ups_monitor")


@dataclass
class ThresholdConfig:
    """Thresholds for a single alert level (warn or crit)."""

    battery_pct: int | None = None
    on_battery_min: float | None = None
    runtime_min: float | None = None

    def any_set(self) -> bool:
        return any(v is not None for v in (self.battery_pct, self.on_battery_min, self.runtime_min))

    def check(self, status: UPSStatus, on_battery_sec: float) -> str | None:
        """Check if any threshold is breached. Returns reason string or None."""
        if self.battery_pct is not None and status.charge_pct <= self.battery_pct:
            return f"charge {status.charge_pct}% <= {self.battery_pct}%"
        if self.on_battery_min is not None and on_battery_sec >= self.on_battery_min * 60:
            return f"on battery {on_battery_sec / 60:.0f} min >= {self.on_battery_min} min"
        if self.runtime_min is not None and status.runtime_min <= self.runtime_min:
            return f"runtime {status.runtime_min:.0f} min <= {self.runtime_min} min"
        return None


@dataclass
class MonitorConfig:
    """Full monitor configuration."""

    poll_interval: float = 30
    email: list[str] = field(default_factory=list)
    warn: ThresholdConfig = field(default_factory=lambda: ThresholdConfig(battery_pct=50, on_battery_min=5, runtime_min=30))
    crit: ThresholdConfig = field(default_factory=lambda: ThresholdConfig(battery_pct=20, on_battery_min=10, runtime_min=10))

    @classmethod
    def from_file(cls, path: str | Path) -> MonitorConfig:
        """Load config from a JSON file."""
        data = json.loads(Path(path).read_text())
        cfg = cls()
        if "poll_interval" in data:
            cfg.poll_interval = data["poll_interval"]
        if "email" in data:
            cfg.email = data["email"] if isinstance(data["email"], list) else [data["email"]]
        if "warn" in data:
            cfg.warn = ThresholdConfig(**data["warn"])
        if "crit" in data:
            cfg.crit = ThresholdConfig(**data["crit"])
        return cfg


class UPSMonitor:
    """Monitors UPS and fires callbacks on state transitions.

    Tracks AC state and fires warn/crit alerts based on configurable
    thresholds (charge %, time on battery, estimated runtime).

    Callbacks receive (event_name, current_status, message).
    """

    def __init__(
        self,
        reader: UPSReader,
        config: MonitorConfig,
        *,
        on_event: callable | None = None,
    ) -> None:
        self.reader = reader
        self.config = config
        self.on_event = on_event

        # State tracking
        self._prev_ac: bool | None = None
        self._warn_fired = False
        self._crit_fired = False
        self._battery_since: float | None = None
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
                self._last_periodic = now
                self._warn_fired = False
                self._crit_fired = False
                self._fire(
                    "power_lost",
                    status,
                    f"Power lost! On battery — {status.charge_pct}% charge, "
                    f"{status.runtime_min:.0f} min runtime",
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
                    f"Power restored after {duration / 60:.1f} min — "
                    f"{status.charge_pct}% charge, {status.input_voltage}V input",
                )

        # Threshold checks (only while on battery)
        if status.on_battery and self._battery_since is not None:
            on_battery_sec = now - self._battery_since

            if not self._warn_fired:
                reason = self.config.warn.check(status, on_battery_sec)
                if reason:
                    self._warn_fired = True
                    self._fire(
                        "battery_warn",
                        status,
                        f"Battery warning ({reason}) — "
                        f"{status.charge_pct}%, {status.runtime_min:.0f} min remaining",
                    )

            if not self._crit_fired:
                reason = self.config.crit.check(status, on_battery_sec)
                if reason:
                    self._crit_fired = True
                    self._fire(
                        "battery_crit",
                        status,
                        f"BATTERY CRITICAL ({reason}) — "
                        f"{status.charge_pct}%, {status.runtime_min:.0f} min remaining",
                    )

            # Periodic update while on battery (every 5 min)
            if now - self._last_periodic >= 300:
                self._last_periodic = now
                self._fire(
                    "battery_update",
                    status,
                    f"On battery for {on_battery_sec / 60:.0f} min — "
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


def _make_alerter(config: MonitorConfig):
    """Create an alert callback using measurebot.alerts if configured."""
    try:
        from measurebot.alerts import send_email, send_discord_message, send_slack_message

        def _alert(event: str, status: UPSStatus, message: str) -> None:
            subject = f"UPS: {event}"
            body = f"UPS: {message}"
            try:
                send_discord_message(body)
            except Exception:
                log.debug("Discord send failed", exc_info=True)
            try:
                send_slack_message(body)
            except Exception:
                log.debug("Slack send failed", exc_info=True)
            if config.email:
                try:
                    send_email(body, subject=subject, to_email=config.email)
                except Exception:
                    log.debug("Email send failed", exc_info=True)

        return _alert
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
        "--config",
        type=str,
        metavar="PATH",
        help="JSON config file (see module docstring for format)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        metavar="SEC",
        help="Poll interval in seconds (overrides config, default: 30)",
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

    # Load config
    if args.config:
        config = MonitorConfig.from_file(args.config)
        log.info("Loaded config from %s", args.config)
    else:
        config = MonitorConfig()

    # CLI overrides
    if args.poll_interval is not None:
        config.poll_interval = args.poll_interval

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
    alerter = _make_alerter(config)
    monitor = UPSMonitor(reader, config, on_event=alerter)

    log.info(
        "Monitoring every %gs — warn: %s, crit: %s, email: %s",
        config.poll_interval,
        f"pct<={config.warn.battery_pct} / time>={config.warn.on_battery_min}min / runtime<={config.warn.runtime_min}min"
        if config.warn.any_set() else "disabled",
        f"pct<={config.crit.battery_pct} / time>={config.crit.on_battery_min}min / runtime<={config.crit.runtime_min}min"
        if config.crit.any_set() else "disabled",
        ", ".join(config.email) if config.email else "none",
    )

    try:
        while True:
            try:
                status = monitor.check()
                log.debug("%s", status.oneliner())
            except Exception:
                log.exception("UPS read failed")
            time.sleep(config.poll_interval)
    except KeyboardInterrupt:
        log.info("Stopped.")
    finally:
        reader.close()


if __name__ == "__main__":
    main()
