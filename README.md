# 🐦 Birdy Skyline — your life list as a zero-server static API + holo trading cards

Turns your local [Birdy](../) BirdNET life list into a **[rapp-static-api/1.0](https://github.com/kody-w/rapp-static-apis)**:
a read-only API served entirely from static files (no server, no database, no runtime),
plus a **Pokémon-style holographic trading-card binder** (`index.html`).

Every confirmed species becomes a card. The card's **serial is the SHA-256 of its identity**, so it's
provably *one-of-one*. Every day is frozen as an immutable, content-addressed frame — a birding diary
that's pinnable forever.

## One build step

```bat
cd C:\code\birdy\skyline
python build.py
```

Reads `..\data\birdy.db` and (re)generates — idempotently, stable-write, append-only:

```
registry.json              the index (schema-tagged, fetchable over raw URLs)
registry.js                window.BIRDY_REGISTRY = {...}  (so index.html works on file://)
api/v1/badge.json          shields.io endpoint → "N species"
api/v1/status.json         compact status
cards/<slug>/<sha8>.json   content-addressed trading cards (immutable, append-only)
frames/<date>/<sha8>.json  content-addressed day frames (immutable, append-only)
assets/spectrograms/*.png  each card's "sound signature" art
.nojekyll, manifest.json
```

## See it

Just open **`index.html`** — no server needed (it loads `registry.js`). Hover a card to tilt the
holo foil; click to flip; hit **✨ Open a pack** for a reveal.

## Card mechanics

| Field | From your data |
|-------|----------------|
| **Type** (Song/Mind/Sky/Aqua/Drum/Aerial/Spark/Ground/Tiny/Wild) | bird family/common-name |
| **HP** | scales with detection count |
| **Rarity** ★–★★★ | best detection confidence (`★★★` holo ≥ 99%) |
| **✦ ELUSIVE** | heard exactly once |
| **Attacks** | deterministic flavor, seeded by the species name |
| **Serial `#sha8`** | SHA-256 of `sci\|common\|type\|rarity\|first_heard` |

## Publish it (as **BlazingBeard**)

```bat
cd C:\code\birdy\skyline
python build.py
git init && git add -A && git commit -m "birdy skyline"
gh repo create BlazingBeard/birdy-skyline --public --source=. --push
gh api -X POST repos/BlazingBeard/birdy-skyline/pages -f source.branch=main -f source.path=/  # enable Pages
```

Then edit `RAW_BASE` at the top of `build.py` (or set the `RAW_BASE` env var) to
`https://raw.githubusercontent.com/BlazingBeard/birdy-skyline/main`, rebuild, and your binder is live at
`https://blazingbeard.github.io/birdy-skyline/` with a CORS-open API anyone can `fetch()`.

README badge:

```md
![birds](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/BlazingBeard/birdy-skyline/main/api/v1/badge.json)
```

## Why it matters

- **Privacy intact** — Birdy stays local; you publish only the life-list JSON you choose to share.
- **Immortal diary** — every day frozen at an immutable `sha8` URL; survives a DB reset.
- **Zero infra, infinite scale** — a CDN-cached static file; CORS-open.
- **Forkable** — the whole state + history lives in git.

---
Spec `rapp-static-api/1.0` (MIT © Kody Wildfeuer). Birdy is MIT; BirdNET model is CC BY-NC-SA
(non-commercial). Wikipedia art © its authors.
