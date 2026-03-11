"""
builtins/capi/plugin.py — Frontier CAPI integration for EDMD.

Handles OAuth2 PKCE authentication with Frontier's auth service and
polls the Companion API to provide authoritative fleet and balance data.

Auth flow
---------
1. EDMD generates a PKCE code_verifier + code_challenge.
2. Opens the user's browser to Frontier's auth page.
3. Spins up a temporary HTTP listener on 127.0.0.1:{ephemeral port}.
4. The state parameter encodes the port so the GitHub Pages relay knows
   where to forward the code after Frontier redirects.
5. Exchanges the auth code for access + refresh tokens.
6. Tokens stored in plugin data.json (per-profile, gitignored path).

Polling triggers
----------------
- Startup (after preload completes)
- Docked journal event
- Undocked journal event  (outfitting may have changed)
- StoredShips journal event (player opened shipyard)
- Manual refresh (via Preferences → CAPI)

CAPI endpoints used
-------------------
/profile  — full commander profile: current ship + outfitting, stored
            ships, stored modules, credit balance, ranks
/fleetcarrier — fleet carrier state (fuel, balance, capacity, docking)

Config [CAPI] in config.toml
-----------------------------
    Enabled = false   # opt-in; set True after authenticating

Tokens are stored in plugin storage (not config.toml) and are
never written to the repository.
"""

import base64
import hashlib
import http.server
import json
import os
import queue
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from core.plugin_loader import BasePlugin
from core.state import EDMD_DATA_DIR, VERSION

# ── Constants ──────────────────────────────────────────────────────────────────

PLUGIN_NAME    = "capi"
PLUGIN_VERSION = "1.0.0"

CLIENT_ID    = "25ae274d-d16b-45e5-bbf3-d143a401d1a7"
REDIRECT_URI = "https://drworman.github.io/EDMD/auth/callback"
AUTH_BASE    = "https://auth.frontierstore.net"
CAPI_BASE    = "https://companion.orerve.net"
SCOPE        = "auth capi"

# How long to wait for the user to complete browser auth before giving up
AUTH_TIMEOUT_S    = 120
# Minimum gap between CAPI polls (avoid hammering the API)
POLL_COOLDOWN_S   = 30
# Startup delay — wait for preload to finish before first poll
STARTUP_DELAY_S   = 10
# HTTP 422 = access token expired
HTTP_EXPIRED      = 422
# Access token margin — refresh if expiry is within this many seconds
TOKEN_REFRESH_MARGIN_S = 60

TOKEN_FILE = "tokens.json"   # stored in plugin storage, never in repo


# ── PKCE helpers ───────────────────────────────────────────────────────────────

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _make_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge)."""
    verifier  = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


# ── One-shot local HTTP listener ───────────────────────────────────────────────

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Receives the OAuth redirect and puts the code in the result queue."""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        code  = (params.get("code", [None])[0])
        error = (params.get("error", [None])[0])

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        if code:
            self.wfile.write(b"Auth code received. You can close this tab.")
        else:
            self.wfile.write(b"Authentication failed. You can close this tab.")

        self.server._result_queue.put(("code", code) if code
                                      else ("error", error or "unknown"))

    def log_message(self, fmt, *args):
        pass   # suppress default HTTP server logging


def _listen_for_callback(port: int, result_q: queue.Queue, timeout: int) -> None:
    """Run a temporary HTTP server on 127.0.0.1:{port} until code arrives."""
    server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server._result_queue = result_q
    server.timeout = timeout
    server.handle_request()   # single request only
    server.server_close()


# ── Token I/O ──────────────────────────────────────────────────────────────────

def _save_tokens(storage, tokens: dict) -> None:
    try:
        storage.write_json(tokens, TOKEN_FILE)
    except Exception:
        pass

def _load_tokens(storage) -> dict:
    try:
        return storage.read_json(TOKEN_FILE) or {}
    except Exception:
        return {}


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _http_post(url: str, data: dict, timeout: int = 20) -> dict:
    body    = urllib.parse.urlencode(data).encode()
    req     = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", f"EDMD/{VERSION}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())

def _http_get(url: str, token: str, timeout: int = 20) -> dict:
    """GET with Bearer auth, preserving the Authorization header through redirects.

    Python's urllib strips Authorization on redirect (security default).
    companion.orerve.net redirects /profile, so we must handle this manually.
    """
    class _AuthRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
            if new_req is not None:
                new_req.add_unredirected_header("Authorization", f"Bearer {token}")
                new_req.add_unredirected_header("User-Agent", f"EDMD/{VERSION}")
            return new_req

    opener = urllib.request.build_opener(_AuthRedirectHandler)
    req = urllib.request.Request(url)
    req.add_unredirected_header("Authorization", f"Bearer {token}")
    req.add_unredirected_header("User-Agent", f"EDMD/{VERSION}")
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


# ── Plugin ─────────────────────────────────────────────────────────────────────

class CAPIPlugin(BasePlugin):
    """Frontier Companion API integration."""

    PLUGIN_NAME        = "capi"
    PLUGIN_DISPLAY     = "Frontier CAPI"
    PLUGIN_VERSION     = PLUGIN_VERSION
    PLUGIN_DESCRIPTION = "Authoritative fleet, balance, and carrier data from Frontier."
    BLOCK_WIDGET_CLASS = None

    SUBSCRIBED_EVENTS  = [
        # All docking types fire the standard Docked event regardless of
        # station type (fleet carrier, surface outpost, megaship, squadron
        # carrier, orbital station — they all use Docked/Undocked).
        "Docked",
        "Undocked",
        "StoredShips",
        "LoadGame",
        # CarrierJump fires when YOUR fleet carrier jumps while you're aboard.
        # Treat it the same as Docked — you've arrived somewhere new.
        "CarrierJump",
    ]

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def _trace(self, msg: str) -> None:
        """Print a diagnostic message only when --trace / DEBUG_MODE is active."""
        if self.core and getattr(self.core, "trace_mode", False):
            print(f"  [CAPI] {msg}")

    def on_load(self, core) -> None:
        super().on_load(core)
        self.core = core

        self._tokens: dict          = {}
        self._last_poll: float      = 0.0
        self._last_refresh: float   = 0.0   # timestamp of last successful token refresh
        self._poll_queue: queue.Queue = queue.Queue()
        self._auth_result: queue.Queue | None = None
        self._lock = threading.Lock()

        # Load saved tokens — discard any minted with the old scope=capi (missing
        # PII fields) so the user is prompted to re-authenticate cleanly.
        loaded = _load_tokens(self.storage)
        if loaded.get("scope", "auth capi") != "auth capi":
            self._trace("Discarding tokens from old scope — please re-authenticate")
            loaded = {}
        self._tokens = loaded

        # Initialise new CAPI state fields if not yet set by another plugin
        s = core.state
        if not hasattr(s, "capi_ranks"):          s.capi_ranks          = None  # {"Combat": int, ...}
        if not hasattr(s, "capi_progress"):       s.capi_progress       = None  # {"Combat": int, ...} 0-100
        if not hasattr(s, "capi_reputation"):     s.capi_reputation     = None  # {"Federation": float, ...}
        if not hasattr(s, "capi_engineer_ranks"): s.capi_engineer_ranks = None  # [{name, rank, progress, unlocked}]

        # Expose auth trigger to other parts of EDMD (Preferences button)
        # Any code can call: core.plugin_call("capi", "start_auth_flow")
        # and check status via: core.plugin_call("capi", "auth_status")

        # Start poll worker thread
        threading.Thread(
            target=self._poll_worker,
            daemon=True,
            name="capi-poll",
        ).start()

        # Schedule startup poll after preload
        threading.Timer(STARTUP_DELAY_S, self._request_poll).start()

    def on_unload(self) -> None:
        self._poll_queue.put(None)   # sentinel to stop worker

    def on_event(self, event: dict, state) -> None:
        name = event.get("event")
        if name in ("Docked", "Undocked", "StoredShips", "LoadGame", "CarrierJump"):
            self._request_poll()

    # ── Public interface (callable via core.plugin_call) ──────────────────────

    def start_auth_flow(self) -> str:
        """
        Initiate the PKCE auth flow in a background thread.
        Returns immediately with "started" or "already_running".
        GUI should poll auth_status() to learn the outcome.
        """
        with self._lock:
            if self._auth_result is not None:
                return "already_running"
            self._auth_result = queue.Queue()

        threading.Thread(
            target=self._run_auth_flow,
            daemon=True,
            name="capi-auth",
        ).start()
        return "started"

    def auth_status(self) -> dict:
        """
        Return current auth + token status.
        {
          "state":   "connected" | "expired" | "none" | "auth_running" | "auth_failed",
          "cmdr":    str | None,
          "expiry":  float | None,   # unix timestamp
          "last_poll": float | None,
        }
        """
        with self._lock:
            running = self._auth_result is not None

        tokens = self._tokens
        if running:
            state = "auth_running"
        elif tokens.get("access_token"):
            expiry = tokens.get("expiry", 0)
            state = "connected" if time.time() < expiry - TOKEN_REFRESH_MARGIN_S else "expired"
        else:
            state = "none"

        return {
            "state":     state,
            "cmdr":      tokens.get("cmdr"),
            "expiry":    tokens.get("expiry"),
            "last_poll": self._last_poll or None,
        }

    def disconnect(self) -> None:
        """Clear stored tokens."""
        self._tokens = {}
        _save_tokens(self.storage, {})

    def manual_poll(self) -> None:
        """Force a CAPI poll regardless of cooldown."""
        self._last_poll = 0.0
        self._request_poll()

    # ── Auth flow ──────────────────────────────────────────────────────────────

    def _run_auth_flow(self) -> None:
        result_q = self._auth_result
        try:
            verifier, challenge = _make_pkce()

            # Pick an ephemeral port
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]

            # state = "port:nonce" so the relay page knows where to forward
            nonce = secrets.token_hex(8)
            state = f"{port}:{nonce}"

            auth_url = (
                f"{AUTH_BASE}/auth"
                f"?response_type=code"
                f"&client_id={CLIENT_ID}"
                f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
                f"&scope={SCOPE}"
                f"&code_challenge={challenge}"
                f"&code_challenge_method=S256"
                f"&state={state}"
            )

            # Start local listener before opening browser to avoid race
            callback_q: queue.Queue = queue.Queue()
            listener = threading.Thread(
                target=_listen_for_callback,
                args=(port, callback_q, AUTH_TIMEOUT_S),
                daemon=True,
            )
            listener.start()

            webbrowser.open(auth_url)

            # Wait for callback
            try:
                kind, value = callback_q.get(timeout=AUTH_TIMEOUT_S + 5)
            except queue.Empty:
                self._finish_auth("timeout")
                return

            if kind == "error" or not value:
                self._finish_auth("error")
                return

            # Exchange code for tokens
            token_resp = _http_post(f"{AUTH_BASE}/token", {
                "grant_type":    "authorization_code",
                "client_id":     CLIENT_ID,
                "code":          value,
                "redirect_uri":  REDIRECT_URI,
                "code_verifier": verifier,
            })

            access_token  = token_resp.get("access_token")
            refresh_token = token_resp.get("refresh_token")
            expires_in    = token_resp.get("expires_in", 7200)

            if not access_token:
                self._finish_auth("error")
                return

            # Decode commander name from /decode endpoint
            cmdr = None
            try:
                me = _http_get(f"{AUTH_BASE}/decode", access_token)
                cmdr = me.get("usr", {}).get("firstname") or me.get("customer_id")
            except Exception:
                pass

            tokens = {
                "access_token":  access_token,
                "refresh_token": refresh_token,
                "expiry":        time.time() + expires_in,
                "cmdr":          cmdr,
                "scope":         SCOPE,
            }
            self._tokens = tokens
            _save_tokens(self.storage, tokens)

            self._finish_auth("ok")

            # Poll immediately after successful auth
            self._last_poll = 0.0
            self._request_poll()

        except Exception:
            self._finish_auth("error")

    def _finish_auth(self, result: str) -> None:
        with self._lock:
            self._auth_result = None
        # Notify GUI
        gq = self.core.gui_queue if self.core else None
        if gq:
            gq.put(("plugin_refresh", "capi"))

    # ── Token refresh ──────────────────────────────────────────────────────────

    def _refresh_token(self) -> bool:
        """Try to get a new access token using the refresh token.
        Returns True on success, False on any failure.
        On a hard 401 (refresh token itself rejected), clears stored tokens
        so the retry loop stops and the user is prompted to re-authenticate.
        """
        rt = self._tokens.get("refresh_token")
        if not rt:
            return False
        try:
            resp = _http_post(f"{AUTH_BASE}/token", {
                "grant_type":    "refresh_token",
                "client_id":     CLIENT_ID,
                "redirect_uri":  REDIRECT_URI,
                "refresh_token": rt,
            })
            at = resp.get("access_token")
            if not at:
                self._trace(f"Refresh response had no access_token: {resp}")
                return False
            self._tokens["access_token"]  = at
            self._tokens["refresh_token"] = resp.get("refresh_token", rt)
            self._tokens["expiry"]        = time.time() + resp.get("expires_in", 7200)
            _save_tokens(self.storage, self._tokens)
            self._trace("Token refreshed successfully")
            return True
        except urllib.error.HTTPError as e:
            if e.code in (400, 401):
                # Refresh token itself is invalid/expired — clear everything
                # so we stop looping and fall through to "re-auth required"
                self._trace(f"Refresh token rejected (HTTP {e.code}) — clearing tokens")
                self._tokens = {}
                _save_tokens(self.storage, {})
            else:
                self._trace(f"Token refresh HTTP error: {e.code}")
            return False
        except Exception as exc:
            self._trace(f"Token refresh error: {type(exc).__name__}: {exc}")
            return False

    def _valid_token(self) -> str | None:
        """Return a valid access token, refreshing if needed. None if unavailable."""
        tokens = self._tokens
        at = tokens.get("access_token")
        if not at:
            return None
        expiry = tokens.get("expiry", 0)
        if time.time() > expiry - TOKEN_REFRESH_MARGIN_S:
            if not self._refresh_token():
                return None
            at = self._tokens.get("access_token")
        return at

    # ── Polling ────────────────────────────────────────────────────────────────

    def _request_poll(self) -> None:
        """Enqueue a poll request (non-blocking)."""
        try:
            self._poll_queue.put_nowait("poll")
        except queue.Full:
            pass

    def _poll_worker(self) -> None:
        """Background thread — serialises all CAPI requests."""
        while True:
            item = self._poll_queue.get()
            if item is None:
                break
            # Drain any queued duplicates
            while not self._poll_queue.empty():
                try:
                    self._poll_queue.get_nowait()
                except queue.Empty:
                    break

            now = time.time()
            if now - self._last_poll < POLL_COOLDOWN_S:
                time.sleep(POLL_COOLDOWN_S - (now - self._last_poll))

            self._do_poll()

    def _do_poll(self) -> None:
        """Perform a CAPI poll cycle: /profile then /fleetcarrier."""
        token = self._valid_token()
        if not token:
            self._trace("Poll skipped — no valid token")
            return

        profile_ok = False
        try:
            self._poll_profile(token)
            profile_ok = True
        except urllib.error.HTTPError as e:
            if e.code in (HTTP_EXPIRED, 401):
                # Frontier uses token rotation: refreshing invalidates the old
                # refresh token immediately. If we refreshed recently, a second
                # poll arriving with the old token will always 401 — back off
                # rather than hammering the token endpoint.
                since_refresh = time.time() - self._last_refresh
                if since_refresh < 60:
                    self._trace(
                        f"401 but refreshed {since_refresh:.0f}s ago — "
                        "backing off, will retry on next dock"
                    )
                else:
                    self._trace(f"Token rejected (HTTP {e.code}) — refreshing")
                    if self._refresh_token():
                        self._last_refresh = time.time()
                        token = self._tokens.get("access_token")
                        if token:
                            try:
                                self._poll_profile(token)
                                profile_ok = True
                            except Exception as exc2:
                                self._trace(f"Profile poll failed after refresh: {exc2}")
                    else:
                        self._trace("Token refresh failed — re-authenticate via Preferences → CAPI")
                        gq = self.core.gui_queue if self.core else None
                        if gq:
                            gq.put(("plugin_refresh", "capi"))
            else:
                self._trace(f"Profile poll HTTP error: {e.code}")
        except Exception as exc:
            self._trace(f"Profile poll error: {type(exc).__name__}: {exc}")

        try:
            self._poll_carrier(token)
        except Exception:
            pass

        self._last_poll = time.time()

        if profile_ok:
            s = self.core.state
            ranks = getattr(s, "capi_ranks", None)
            rep   = getattr(s, "capi_reputation", None)
            self._trace(
                f"Poll complete — "
                f"ranks={list(ranks) if ranks else 'none'}, "
                f"rep={list(rep) if rep else 'none'}"
            )

        gq = self.core.gui_queue if self.core else None
        if gq:
            gq.put(("plugin_refresh", "assets"))
            gq.put(("plugin_refresh", "commander"))

        # Push authoritative liquid credits to Inara (CAPI is source of truth)
        balance = getattr(self.core.state, "assets_balance", None)
        if balance is not None:
            try:
                self.core.plugin_call("inara", "push_credits", int(balance))
            except Exception:
                pass

    # ── /profile ───────────────────────────────────────────────────────────────

    def _poll_profile(self, token: str) -> None:
        data    = _http_get(f"{CAPI_BASE}/profile", token)
        state   = self.core.state
        ship    = data.get("ship", {})
        ships   = data.get("ships", {})  # dict keyed by shipID string

        # ── Balance ────────────────────────────────────────────────────────────
        commander = data.get("commander", {})
        balance   = commander.get("credits")
        if balance is not None:
            state.assets_balance = float(balance)

        # ── Current ship ───────────────────────────────────────────────────────
        if ship:
            ship_type   = ship.get("name", "")
            ship_type_l = ship.get("nameLocalized") or ship.get("name", "")
            state.assets_current_ship = {
                "_key":         "current",
                "current":      True,
                "ship_id":      ship.get("id"),
                "type":         ship_type,
                "type_display": ship_type_l,
                "name":         ship.get("shipName", ""),
                "ident":        ship.get("shipIdent", ""),
                "system":       getattr(state, "pilot_system", None) or "—",
                "value":        ship.get("value", {}).get("hull", 0),
                "hull":         100,
                "capi":         True,   # flag so journal events don't overwrite
            }

        # ── Stored ships ───────────────────────────────────────────────────────
        current_id = (state.assets_current_ship or {}).get("ship_id")
        stored = []
        for sid_str, s in ships.items():
            try:
                sid = int(sid_str)
            except (ValueError, TypeError):
                sid = sid_str
            if sid == current_id:
                continue
            loc   = s.get("starsystem", {})
            sys_n = loc.get("name", "—") if isinstance(loc, dict) else "—"
            stored.append({
                "_key":         f"ship_{sid}",
                "ship_id":      sid,
                "current":      False,
                "type":         s.get("name", ""),
                "type_display": s.get("nameLocalized") or s.get("name", ""),
                "name":         s.get("shipName", ""),
                "ident":        s.get("shipIdent", ""),
                "system":       sys_n,
                "value":        s.get("value", {}).get("hull", 0),
                "hot":          False,
                "capi":         True,
            })
        # Include current ship in stored list (block deduplicates at render time)
        if state.assets_current_ship:
            state.assets_stored_ships = [state.assets_current_ship] + stored
        else:
            state.assets_stored_ships = stored

        # ── Modules (stored at station) ────────────────────────────────────────
        modules_raw = data.get("modules")
        if isinstance(modules_raw, dict):
            mods = []
            for i, (slot, m) in enumerate(modules_raw.items()):
                internal = m.get("name", "")
                disp     = m.get("nameLocalized") or internal
                mods.append({
                    "_key":         f"{i}_{internal}",
                    "name_internal": internal,
                    "name_display":  disp,
                    "slot":         slot,
                    "system":       "—",
                    "mass":         m.get("mass", 0.0),
                    "value":        m.get("value", 0),
                    "hot":          False,
                })
            if mods:
                state.assets_stored_modules = mods

        # ── Ranks / progress (CAPI is authoritative baseline) ─────────────────
        # Store raw integer indexes; display layers map to names via RANK_NAMES.
        # Never overwrite pilot_rank/pilot_rank_progress here — those are owned
        # by the commander plugin and updated in real-time from Journal events.
        raw_ranks    = commander.get("rank",     {})
        raw_progress = commander.get("progress", {})
        self._trace(f"Profile ranks raw: {raw_ranks}")
        if raw_ranks:
            state.capi_ranks    = {k: int(v) for k, v in raw_ranks.items()
                                   if isinstance(v, (int, float))}
        if raw_progress:
            state.capi_progress = {k: int(v) for k, v in raw_progress.items()
                                   if isinstance(v, (int, float))}

        # ── Reputation ────────────────────────────────────────────────────────
        # Values are floats 0-100 (percentage standing with each superpower).
        raw_rep = commander.get("reputation", {})
        if raw_rep:
            state.capi_reputation = {k: float(v) for k, v in raw_rep.items()
                                     if isinstance(v, (int, float))}

        # ── Engineer progress ─────────────────────────────────────────────────
        raw_eng = commander.get("engineerProgress", [])
        if isinstance(raw_eng, list) and raw_eng:
            engineers = []
            for entry in raw_eng:
                if not isinstance(entry, dict):
                    continue
                engineers.append({
                    "name":     entry.get("Engineer", ""),
                    "rank":     entry.get("Rank"),          # int or None
                    "progress": entry.get("RankProgress"),  # 0-100 or None
                    "unlocked": bool(entry.get("Rank") is not None),
                })
            state.capi_engineer_ranks = engineers

    # ── /fleetcarrier ──────────────────────────────────────────────────────────

    def _poll_carrier(self, token: str) -> None:
        try:
            data = _http_get(f"{CAPI_BASE}/fleetcarrier", token)
        except urllib.error.HTTPError as e:
            # 404 = commander has no fleet carrier — not an error
            if e.code == 404:
                return
            raise

        state = self.core.state
        if not data:
            return

        # ── Diagnostic dump ────────────────────────────────────────────────────
        # Always write the raw response so the operator can inspect real keys.
        # File: ~/.local/share/edmd/fleetcarrier_dump.json  (or XDG equivalent)
        try:
            import json as _json
            _dump = EDMD_DATA_DIR / "fleetcarrier_dump.json"
            _dump.write_text(_json.dumps(data, indent=2, default=str))
            self._trace(f"fleetcarrier raw dump written to {_dump}")
        except Exception as _e:
            self._trace(f"fleetcarrier dump failed: {_e}")

        self._trace(f"fleetcarrier top-level keys: {list(data.keys())}")

        # ── Helpers ────────────────────────────────────────────────────────────
        def _int(v):
            try: return int(v)
            except (TypeError, ValueError): return 0

        def _pct(v):
            try: return round(float(v), 1)
            except (TypeError, ValueError): return 0.0

        def _decode_vanity(s: str) -> str:
            """CAPI hex-encodes vanityName as ASCII bytes e.g. 56454354555241 → VECTURA."""
            try:
                return bytes.fromhex(s).decode("ascii").strip()
            except Exception:
                return s

        # ── Name / callsign ────────────────────────────────────────────────────
        name_obj = data.get("name") or {}
        callsign = name_obj.get("callsign") or data.get("callsign") or "\u2014"
        raw_vanity = name_obj.get("vanityName") or name_obj.get("filteredVanityName") or ""
        carrier_name = _decode_vanity(raw_vanity) if raw_vanity else callsign
        self._trace(f"name callsign={callsign!r}  raw_vanity={raw_vanity!r}  decoded={carrier_name!r}")

        # ── Finance ────────────────────────────────────────────────────────────
        # Keys: bankBalance, bankReservedBalance, service_taxation{...},
        #       maintenance, maintenanceToDate, coreCost, servicesCost
        fin = data.get("finance") or {}
        self._trace(f"finance keys: {list(fin.keys())}")
        bank_bal   = _int(fin.get("bankBalance",         0))
        bank_res   = _int(fin.get("bankReservedBalance", 0))
        bank_avail = bank_bal - bank_res
        taxation   = fin.get("service_taxation") or {}
        self._trace(f"service_taxation: {taxation}")
        maintenance     = _int(fin.get("maintenance",        0))
        maintenance_wtd = _int(fin.get("maintenanceToDate",  0))
        core_cost       = _int(fin.get("coreCost",           0))
        svc_cost        = _int(fin.get("servicesCost",       0))

        # ── Capacity ───────────────────────────────────────────────────────────
        # crew   = space consumed by crew/services (fixed overhead)
        # freeSpace = space available for new cargo
        # cargoForSale + cargoNotForSale + cargoSpaceReserved = cargo currently stored
        cap = data.get("capacity") or {}
        self._trace(f"capacity keys: {list(cap.keys())}")
        crew_space  = _int(cap.get("crew",                0))
        free_space  = _int(cap.get("freeSpace",           0))
        cargo_sale  = _int(cap.get("cargoForSale",        0))
        cargo_nosale= _int(cap.get("cargoNotForSale",     0))
        cargo_res   = _int(cap.get("cargoSpaceReserved",  0))
        cargo_used  = cargo_sale + cargo_nosale + cargo_res
        cargo_total = crew_space + free_space          # = 25 000 for a standard carrier
        # "available cargo space" = free_space (does not include crew overhead)
        ship_packs   = _int(cap.get("shipPacks",    0))
        module_packs = _int(cap.get("modulePacks",  0))
        micro_total  = _int(cap.get("microresourceCapacityTotal",    0))
        micro_free   = _int(cap.get("microresourceCapacityFree",     0))
        micro_used   = _int(cap.get("microresourceCapacityUsed",     0))

        # ── Docking / access ───────────────────────────────────────────────────
        docking   = data.get("dockingAccess")  or "\u2014"
        notorious = bool(data.get("notoriousAccess", False))

        # ── Services ───────────────────────────────────────────────────────────
        # Authoritative status lives at market.services
        services = {}
        mkt = data.get("market") or {}
        raw_svcs = mkt.get("services") or {}
        if isinstance(raw_svcs, dict):
            services = dict(raw_svcs)   # {"shipyard": "ok", "blackmarket": "unavailable", ...}
        self._trace(f"services ({len(services)} entries): {services}")

        carrier = {
            # Identity
            "callsign":         callsign,
            "name":             carrier_name,
            "system":           data.get("currentStarSystem", "\u2014"),
            "theme":            data.get("theme", "\u2014"),
            # Fuel
            "fuel":             _int(data.get("fuel", 0)),
            # Operational state
            "carrier_state":    data.get("state", "\u2014"),
            # Access
            "docking":          docking,
            "notorious":        notorious,
            # Finance
            "balance":          bank_bal,
            "reserve":          bank_res,
            "available":        bank_avail,
            "tax_refuel":       _pct(taxation.get("refuel",          0)),
            "tax_repair":       _pct(taxation.get("repair",          0)),
            "tax_rearm":        _pct(taxation.get("rearm",           0)),
            "tax_pioneer":      _pct(taxation.get("pioneersupplies", 0)),
            "maintenance":      maintenance,
            "maintenance_wtd":  maintenance_wtd,
            # Cargo
            "cargo_total":      cargo_total,
            "cargo_crew":       crew_space,
            "cargo_used":       cargo_used,
            "cargo_free":       free_space,
            # Pack storage
            "ship_packs":       ship_packs,
            "module_packs":     module_packs,
            # Micro-resources
            "micro_total":      micro_total,
            "micro_free":       micro_free,
            "micro_used":       micro_used,
            # Services
            "services":         services,
            # Source flag
            "capi":             True,
        }
        self._trace(f"carrier dict built: {carrier}")
        state.assets_carrier = carrier
