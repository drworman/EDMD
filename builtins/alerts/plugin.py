"""
builtins/alerts/plugin.py — Combat and hazard alert tracking.

Maintains a deque of the last 5 alert events with monotonic timestamps.
Feeds both the Alerts dashboard block and the existing emit() pipeline
(terminal + Discord alerts are handled here for these event types).

GUI block: col=0, row=9, width=24, height=3 (default — full width).
"""

import time
from collections import deque
from core.plugin_loader import BasePlugin
from core.emit import Terminal
from core.state import FUEL_CRIT_THRESHOLD, FUEL_WARN_THRESHOLD


class AlertsPlugin(BasePlugin):
    PLUGIN_NAME    = "alerts"
    PLUGIN_DISPLAY = "Alerts"
    PLUGIN_VERSION = "1.0.0"

    SUBSCRIBED_EVENTS = [
        "ShieldState",
        "HullDamage",
        "FighterDestroyed",
        "ReservoirReplenished",
        "EjectCargo",
        "Died",
    ]

    DEFAULT_COL    = 0
    DEFAULT_ROW    = 9
    DEFAULT_WIDTH  = 24
    DEFAULT_HEIGHT = 3

    # Fade timing (seconds)
    FADE_START  = 60
    FADE_END    = 90
    DIM_OPACITY = 0.4

    def on_load(self, core) -> None:
        super().on_load(core)
        # alert_queue: deque of dicts {emoji, text, mono_time}
        self.alert_queue: deque = deque(maxlen=5)
        core.register_block(self, priority=90)
        core.register_alert(self)

    def _push(self, emoji: str, text: str) -> None:
        self.alert_queue.appendleft({
            "emoji":     emoji,
            "text":      text,
            "mono_time": time.monotonic(),
        })
        gq = self.core.gui_queue
        if gq: gq.put(("alerts_update", None))

    def on_event(self, event: dict, state) -> None:
        core    = self.core
        notify  = core.notify_levels
        cfg     = core.cfg
        logtime = event.get("_logtime")
        ev      = event.get("event")

        match ev:

            case "ShieldState":
                if event["ShieldsUp"]:
                    col     = Terminal.GOOD
                    shields = "back up"
                    state.ship_shields            = True
                    state.ship_shields_recharging = False
                    self._push("🛡️", "Ship shields back up")
                else:
                    col     = Terminal.BAD
                    shields = "down!"
                    state.ship_shields            = False
                    state.ship_shields_recharging = True
                    self._push("🛡️", "Ship shields down!")
                gq = core.gui_queue
                if gq: gq.put(("vessel_update", None))
                core.emitter.emit(
                    msg_term=f"{col}Ship shields {shields}{Terminal.END}",
                    msg_discord=f"**Ship shields {shields}**",
                    emoji="🛡️", sigil="^  SHLD",
                    timestamp=logtime, loglevel=notify["ShieldEvent"],
                )

            case "HullDamage" if event.get("PlayerPilot") and not event.get("Fighter"):
                hullhealth = round(event["Health"] * 100)
                state.ship_hull = hullhealth
                gq = core.gui_queue
                if gq: gq.put(("vessel_update", None))
                self._push("⚠️", f"Ship hull: {hullhealth}%")
                core.emitter.emit(
                    msg_term=(
                        f"{Terminal.BAD}Ship hull damaged!{Terminal.END} "
                        f"(Integrity: {hullhealth}%)"
                    ),
                    msg_discord=f"**Ship hull damaged!** (Integrity: {hullhealth}%)",
                    emoji="⚠️", sigil="^  HULL",
                    timestamp=logtime, loglevel=notify["HullEvent"],
                )

            case "FighterDestroyed" if state.prev_event != "StartJump":
                self._push("💀", "Fighter destroyed!")

            case "ReservoirReplenished":
                fuel_pct = round((event["FuelMain"] / state.fuel_tank_size) * 100)
                fuel_time_remain = ""
                ses = core.active_session
                if (
                    ses.fuel_check_time
                    and state.session_start_time
                    and logtime > ses.fuel_check_time
                ):
                    fuel_time = (logtime - ses.fuel_check_time).total_seconds()
                    fuel_hour = (
                        3600 / fuel_time * (ses.fuel_check_level - event["FuelMain"])
                        if fuel_time > 0 else 0
                    )
                    if fuel_hour > 0:
                        from core.emit import fmt_duration
                        fuel_time_remain = f" (~{fmt_duration(event['FuelMain'] / fuel_hour * 3600)})"
                        state.fuel_burn_rate = fuel_hour
                ses.fuel_check_time  = logtime
                ses.fuel_check_level = event["FuelMain"]

                # Persist current fuel level on state so other blocks can read it
                state.fuel_current = event["FuelMain"]

                col = ""; level = ":"; fuel_loglevel = 0
                if event["FuelMain"] < state.fuel_tank_size * FUEL_CRIT_THRESHOLD:
                    col = Terminal.BAD;  fuel_loglevel = notify["FuelCritical"]; level = " critical!"
                    self._push("⛽", f"Fuel critical: {fuel_pct}%")
                elif event["FuelMain"] < state.fuel_tank_size * FUEL_WARN_THRESHOLD:
                    col = Terminal.WARN; fuel_loglevel = notify["FuelWarning"];  level = " low:"
                    self._push("⛽", f"Fuel low: {fuel_pct}%")
                elif state.session_start_time:
                    fuel_loglevel = notify["FuelStatus"]

                core.emitter.emit(
                    msg_term=f"{col}Fuel: {fuel_pct}% remaining{Terminal.END}{fuel_time_remain}",
                    msg_discord=f"**Fuel{level} {fuel_pct}% remaining**{fuel_time_remain}",
                    emoji="⛽", sigil="+  FUEL",
                    timestamp=logtime, loglevel=fuel_loglevel,
                )

            case "EjectCargo" if not event.get("Abandoned") and event.get("Count") == 1:
                name = event.get("Type_Localised") or event["Type"].title()
                self._push("📦", f"Cargo stolen! ({name})")
                core.emitter.emit(
                    msg_term=f"{Terminal.BAD}Cargo stolen!{Terminal.END} ({name})",
                    msg_discord=f"**Cargo stolen!** ({name})",
                    emoji="📦", sigil="^  SHLD",
                    timestamp=logtime, loglevel=notify["CargoLost"],
                    event="CargoLost",
                )

            case "Died":
                self._push("💀", "Ship destroyed!")
                core.emitter.emit(
                    msg_term=f"{Terminal.BAD}Ship destroyed!{Terminal.END}",
                    msg_discord="**Ship destroyed!**",
                    emoji="💀", sigil="!! DEAD",
                    timestamp=logtime, loglevel=notify["Died"],
                )

    def get_alerts(self) -> list[dict]:
        """Return current alerts list for the GUI block renderer."""
        return list(self.alert_queue)

    def clear_alerts(self) -> None:
        """Clear all alerts (called by the GUI Clear button)."""
        self.alert_queue.clear()
        if self.core.gui_queue:
            self.core.gui_queue.put(("alerts_update", None))

    def opacity_for(self, alert: dict) -> float:
        """Return current display opacity for an alert based on its age."""
        age = time.monotonic() - alert["mono_time"]
        if age < self.FADE_START:
            return 1.0
        if age < self.FADE_END:
            frac = (age - self.FADE_START) / (self.FADE_END - self.FADE_START)
            return 1.0 - frac * (1.0 - self.DIM_OPACITY)
        return self.DIM_OPACITY
