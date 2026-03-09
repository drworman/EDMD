# EDMD Release Notes

---

## 20260309b

**Elite Dangerous Monitor Daemon — EDMD**

---

### New Feature — Cargo Block

A **Cargo** dashboard block shows your ship's current hold in real time.

The header displays used and maximum tonnage (`N / MAX t`), colour-coded by
fill level: neutral below 75%, amber at 75–99%, red when full. The body lists
every commodity alphabetically with its quantity. Stolen goods are flagged with
a ⚠ prefix. An empty hold shows a single `— empty —` line.

Cargo data is sourced from `Cargo.json` in your journal directory — the same
companion file EDMC uses — which is always authoritative for the ship hold
regardless of whether an SRV or Fighter is deployed. The block bootstraps
immediately at startup without waiting for a journal event.

---

### New Feature — Materials Block

An **Engineering Materials** dashboard block shows your full materials
inventory across three sections: **RAW**, **MANUFACTURED**, and **ENCODED**.
Each section header shows a running item count. Items are listed alphabetically
with their quantities. Sections with no items show `— none —`.

The block updates in real time on any `Materials`, `MaterialCollected`,
`MaterialDiscarded`, `MaterialTrade`, `EngineerCraft`, `TechnologyBroker`,
or `Synthesis` journal event.

---

### New Feature — Data Contributions (EDDN, EDSM, EDAstro)

A **Data & Integrations** tab has been added to Preferences, providing opt-in
journal uploading to three community data networks:

**EDDN** — Forwards compatible journal events to the Elite Dangerous Data
Network in real time. Supports live and test modes. Reads companion JSON files
(`Market.json`, `Outfitting.json`, `Shipyard.json`) when available. Includes
beta detection, deduplication, and a disk-backed retry queue for transient
network failures.

**EDSM** — Uploads your journal to the Elite Star Map API. Requires a
commander name and API key (configured in Preferences). Events are batched and
flushed on session transitions to stay well within EDSM's rate limits. Fetches
EDSM's own discard list at startup and filters accordingly. Beta sessions are
suppressed automatically.

**EDAstro** — Forwards journal events to EDAstro. No API key required.
Fetches EDAstro's event-interest list at startup; only requested events are
sent. Supports an opt-in for carrier events (`UploadCarrierEvents`) which may
expose fleet carrier position.

All three integrations require a restart to activate or deactivate.
See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for setup.

---

### Improvement — Ghost Overlay for Block Resize

Block resizing now uses the same ghost-frame technique introduced for
drag-to-move in 20260309: a dashed border overlay tracks the new size during
the drag while the block itself stays put, eliminating the stutter and
content-reflow that occurred when the block was resized live. On release, the
block snaps to grid normally.

---

### New Feature — Alerts: Clear Button

The Alerts block now has a **Clear** button pinned to the bottom-right of the
block. Clicking it immediately empties the alert queue.

---

### Bug Fix — Cargo Block: SRV and Fighter Snapshots Overwriting Ship Hold

At session start the game fires a `Cargo` journal event for each active vessel
— ship, SRV, and Fighter — in sequence. Because SRV and Fighter events always
carry an empty inventory, the last event in the sequence was overwriting the
ship's cargo with zero items. The plugin now reads `Cargo.json` directly
instead of parsing the event payload, which eliminates the vessel-ordering
problem entirely.

---

### Bug Fix — Materials Block: Content Not Visible

The three scrolled sections in the Materials block (Raw, Manufactured, Encoded)
had `vexpand = False` and `min-content-height = 0`, causing GTK to allocate
them zero pixels. Items were being written to the widget tree but were not
visible. Sections now expand to fill available block height.

---

### Bug Fix — EDSM / EDAstro: Plugin Load Warning

Both plugins were calling `core.load_setting()` with a `warn_missing=` keyword
argument that does not exist on that method. The correct parameter is `warn=`.
The spurious keyword caused a `TypeError` at startup in some Python versions.

---

### Upgrading from 20260309a

No config changes required for existing users. Users wishing to enable EDDN,
EDSM, or EDAstro should add the relevant sections to their `config.toml` — see
[docs/CONFIGURATION.md](docs/CONFIGURATION.md) — or configure them via
Preferences → Data & Integrations.

---

### Known Limitations (unchanged)

- SLF shield state is not tracked — the game does not expose this via journal
  or `Status.json`
- GTK4 GUI is Linux-only; Windows users have terminal and Discord output
- Inara integration is pending whitelist approval
