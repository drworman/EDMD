"""
builtins/missions/plugin.py — Massacre mission stack tracking.

Owns: active_missions, missions_complete, stack_value,
      mission_value_map, mission_target_faction_map, reset_missions().
GUI block: col=0, row=5, width=8, height=4 (default).
"""

from core.plugin_loader import BasePlugin
from core.emit import Terminal, fmt_credits


class MissionsPlugin(BasePlugin):
    PLUGIN_NAME    = "missions"
    PLUGIN_DISPLAY = "Mission Stack"
    PLUGIN_VERSION = "1.0.0"

    SUBSCRIBED_EVENTS = [
        "Missions",
        "MissionAccepted",
        "MissionRedirected",
        "MissionAbandoned",
        "MissionCompleted",
        "MissionFailed",
    ]

    DEFAULT_COL    = 0
    DEFAULT_ROW    = 5
    DEFAULT_WIDTH  = 8
    DEFAULT_HEIGHT = 4

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_block(self, priority=30)

    def on_event(self, event: dict, state) -> None:
        core    = self.core
        gq      = core.gui_queue
        notify  = core.notify_levels
        settings = core.app_settings
        ev      = event.get("event")

        match ev:

            case "MissionRedirected" if (
                "Mission_Massacre" in event.get("Name", "")
                and not state.in_preload
            ):
                state.missions_complete += 1
                total = len(state.active_missions)
                done  = state.missions_complete
                if done < total:
                    log      = notify["MissionUpdate"]
                    msg_term = f"Mission {done} of {total} complete ({total - done} remaining)"
                else:
                    log      = notify["AllMissionsReady"]
                    msg_term = f"All {total} missions complete — ready to turn in!"
                core.emitter.emit(
                    msg_term=msg_term, emoji="✅", sigil="*  MISS",
                    timestamp=event.get("_logtime"), loglevel=log,
                )
                if gq: gq.put(("mission_update", None))

            case "Missions" if "Active" in event and not state.missions:
                state.active_missions.clear()
                state.missions_complete = 0
                for mission in event["Active"]:
                    exp    = mission.get("Expires", 0)
                    exp_ok = (exp == 0) or (exp > 0)
                    if "Mission_Massacre" in mission["Name"] and exp_ok:
                        state.active_missions.append(mission["MissionID"])
                        if (
                            "Reward" in mission
                            and mission["MissionID"] not in state.mission_value_map
                        ):
                            state.stack_value += mission["Reward"]
                            state.mission_value_map[mission["MissionID"]] = mission["Reward"]

                # Count missions already redirected before EDMD launched
                if state.active_missions:
                    active_set = set(state.active_missions)
                    redirected = set()
                    try:
                        from pathlib import Path
                        import json
                        for jpath in sorted(core.journal_dir.glob("Journal*.log")):
                            try:
                                with open(jpath, mode="r", encoding="utf-8") as jf:
                                    for ln in jf:
                                        try: je = json.loads(ln)
                                        except ValueError: continue
                                        if (
                                            je.get("event") == "MissionRedirected"
                                            and "Mission_Massacre" in je.get("Name", "")
                                            and je.get("MissionID") in active_set
                                        ):
                                            redirected.add(je["MissionID"])
                                        elif je.get("event") in (
                                            "MissionCompleted", "MissionAbandoned", "MissionFailed"
                                        ):
                                            redirected.discard(je.get("MissionID"))
                            except OSError:
                                continue
                    except Exception:
                        pass
                    state.missions_complete = len(redirected & active_set)

                state.missions = True
                core.emitter.emit(
                    msg_term=f"Missions loaded (active massacres: {len(state.active_missions)})",
                    emoji="📋", sigil="*  MISS",
                    timestamp=event.get("_logtime"), loglevel=notify["MissionUpdate"],
                )
                if gq: gq.put(("mission_update", None))

            case "MissionAccepted" if (
                "Mission_Massacre" in event.get("Name", "")
                and not state.in_preload
            ):
                state.active_missions.append(event["MissionID"])
                if "Reward" in event:
                    state.stack_value += event["Reward"]
                    state.mission_value_map[event["MissionID"]] = event["Reward"]
                if "TargetFaction" in event:
                    state.mission_target_faction_map[event["MissionID"]] = event["TargetFaction"]
                total_now = len(state.active_missions)
                core.emitter.emit(
                    msg_term=f"Accepted massacre mission (active: {total_now})",
                    emoji="📋", sigil="*  MISS",
                    timestamp=event.get("_logtime"), loglevel=notify["MissionUpdate"],
                )
                full_stack = settings.get("FullStackSize", 20)
                if not state.in_preload and total_now == full_stack and state.stack_value > 0:
                    _sl = f"Stack full ({total_now} missions) — {fmt_credits(state.stack_value)}"
                    core.emitter.emit(
                        msg_term=_sl, msg_discord=f"**{_sl}**",
                        emoji="🏆", sigil="*  MISS",
                        timestamp=event.get("_logtime"), loglevel=notify["MissionUpdate"],
                    )
                if gq: gq.put(("mission_update", None))

            case "MissionAbandoned" | "MissionCompleted" | "MissionFailed" if (
                state.missions
                and not state.in_preload
                and event.get("MissionID") in state.active_missions
            ):
                mid    = event["MissionID"]
                reward = state.mission_value_map.pop(mid, 0)
                if reward:
                    state.stack_value -= reward
                state.mission_target_faction_map.pop(mid, None)
                state.active_missions.remove(mid)
                if state.missions_complete > 0:
                    state.missions_complete -= 1
                event_label = event["event"][7:].lower()
                core.emitter.emit(
                    msg_term=f"Massacre mission {event_label} (active: {len(state.active_missions)})",
                    emoji="📋", sigil="*  MISS",
                    timestamp=event.get("_logtime"), loglevel=notify["MissionUpdate"],
                )
                if gq: gq.put(("mission_update", None))

    def get_summary_line(self) -> str | None:
        state = self.core.state
        if state.stack_value <= 0:
            return None
        done      = state.missions_complete
        total     = len(state.active_missions)
        remaining = total - done
        status = (
            "all complete — turn in!"
            if remaining == 0
            else f"{done}/{total} complete, {remaining} remaining"
        )
        return f"- Missions: {fmt_credits(state.stack_value)} stack ({status})"
