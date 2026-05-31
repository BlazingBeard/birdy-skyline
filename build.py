#!/usr/bin/env python3
"""Birdy Skyline — the ONE build step for a rapp-static-api/1.0.

Reads Birdy's SQLite life list and mints a zero-server static API:

  registry.json        the index (schema-tagged, machine-readable, fetchable raw)
  registry.js          window.BIRDY_REGISTRY = {...}  (so index.html works on file://)
  api/v1/badge.json    shields.io endpoint  ->  "N species"
  api/v1/status.json   compact status endpoint
  cards/<slug>/<sha8>.json   content-addressed trading cards (append-only, immutable)
  frames/<date>/<sha8>.json  content-addressed day frames (append-only, immutable)
  assets/spectrograms/<slug>.png   the card's "sound signature" art
  .nojekyll, manifest.json

Rules honored (rapp-static-api/1.0): one build step; idempotent + stable-write
(no timestamp-only diffs); append-only content (a published sha8 blob is never
deleted or mutated — it's a permanent, pinnable fallback).

Pure standard library. No deps. Run:  python build.py
Spec: https://github.com/kody-w/rapp-static-apis
"""
import os, re, json, sqlite3, hashlib, shutil, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DB   = os.environ.get("BIRDY_DB", os.path.join(ROOT, "..", "data", "birdy.db"))
SPECTRO_BASE = os.environ.get("BIRDY_SPECTROGRAMS", os.path.join(ROOT, "..", "data", "spectrograms"))
# Where this API will be served from once pushed (edit OWNER/REPO or set RAW_BASE).
RAW_BASE = os.environ.get(
    "RAW_BASE", "https://raw.githubusercontent.com/BlazingBeard/birdy-skyline/main"
).rstrip("/")
NAME = "birdy-skyline"
NOW = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
#  Element typing — turn a real bird into a trading-card "type"               #
# --------------------------------------------------------------------------- #
# Maps common-name keywords (checked first) and genus/family vibes to a type.
_TYPE_RULES = [
    ("mind",   ["jay", "crow", "raven", "magpie", "nutcracker"]),                 # corvids
    ("drum",   ["woodpecker", "sapsucker", "flicker"]),                            # picids
    ("aerial", ["flycatcher", "pewee", "phoebe", "kingbird", "wood-pewee"]),       # tyrants
    ("sky",    ["hawk", "eagle", "falcon", "owl", "kite", "harrier", "osprey", "vulture"]),
    ("aqua",   ["duck", "goose", "heron", "egret", "gull", "grebe", "coot", "merganser", "teal", "loon"]),
    ("spark",  ["hummingbird"]),
    ("ground", ["dove", "pigeon", "quail", "grouse", "pheasant", "turkey"]),
    ("tiny",   ["chickadee", "titmouse", "nuthatch", "bushtit", "kinglet", "wren"]),
    ("song",   ["warbler", "sparrow", "finch", "vireo", "tanager", "grosbeak",
                "towhee", "thrush", "robin", "bunting", "blackbird", "oriole",
                "junco", "siskin", "wax", "starling", "swallow", "lark", "pipit",
                "thrasher", "mockingbird", "shrike"]),
]
_TYPE_DEFAULT = "wild"


def type_for(common, sci):
    c = (common or "").lower()
    for tname, keys in _TYPE_RULES:
        if any(k in c for k in keys):
            return tname
    return _TYPE_DEFAULT


# Deterministic flavor attacks, stable per species (seeded by sci-name hash).
_ATTACKS = {
    "mind":   ["Trickster Cache", "Mob Call", "Acorn Barrage", "Mimic Cry"],
    "drum":   ["Bark Volley", "Resonant Drum", "Sap Tap", "Snag Drill"],
    "aerial": ["Hawk & Sally", "Snap Strike", "Perch Ambush", "Wing Flick"],
    "sky":    ["Stoop Dive", "Talon Lock", "Thermal Soar", "Silent Glide"],
    "aqua":   ["Dabble Rush", "Ripple Wake", "Plunge", "Reed Hide"],
    "spark":  ["Hover Buzz", "Nectar Lance", "Iridescent Flash", "Pivot Dart"],
    "ground": ["Covey Burst", "Dust Bathe", "Soft Coo", "Low Strut"],
    "tiny":   ["Chickadee Scold", "Seed Stash", "Upside Cling", "Flit"],
    "song":   ["Dawn Serenade", "Trill Cascade", "Counter-Sing", "Sweet Whistle"],
    "wild":   ["Wild Call", "Brush Dash", "Flush", "Skulk"],
}


def slugify(sci):
    return re.sub(r"[^a-z0-9]+", "-", (sci or "").lower()).strip("-")


def sha256_hex(b):
    return hashlib.sha256(b).hexdigest()


def rarity_for(best_conf, count):
    if best_conf >= 0.99:
        tier, stars = "holo-rare", 3
    elif best_conf >= 0.95:
        tier, stars = "rare", 2
    elif best_conf >= 0.85:
        tier, stars = "uncommon", 1
    else:
        tier, stars = "common", 0
    elusive = count <= 1            # heard exactly once = hard to find again
    return {"tier": tier, "stars": stars, "elusive": elusive}


def attacks_for(type_key, sci):
    pool = _ATTACKS.get(type_key, _ATTACKS["wild"])
    seed = int(sha256_hex(sci.encode())[:8], 16)
    a1 = pool[seed % len(pool)]
    a2 = pool[(seed // 7) % len(pool)]
    if a2 == a1:
        a2 = pool[(seed // 7 + 1) % len(pool)]
    cost1 = 1 + (seed % 2)
    cost2 = 2 + (seed % 3)
    dmg1 = 10 * (1 + seed % 4)
    dmg2 = 20 * (2 + (seed >> 3) % 3)
    return [
        {"name": a1, "cost": cost1, "damage": dmg1},
        {"name": a2, "cost": cost2, "damage": dmg2},
    ]


# --------------------------------------------------------------------------- #
#  Stable-write + content-addressed freezing                                  #
# --------------------------------------------------------------------------- #
def write_json_stable(path, obj, ts_keys=("generated",)):
    """Write JSON; if the only change vs the existing file is a timestamp key,
    keep the old timestamp so git sees no diff (kills scheduled-CI noise)."""
    new = json.loads(json.dumps(obj, ensure_ascii=False))
    if os.path.exists(path):
        try:
            old = json.load(open(path, encoding="utf-8"))
            strip = lambda d: {k: v for k, v in d.items() if k not in ts_keys}
            if strip(new) == strip(old):
                for k in ts_keys:
                    if k in old:
                        new[k] = old[k]
        except Exception:
            pass
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(new, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return new


def freeze(rel_dir, payload_obj, identity_str):
    """Append-only content-addressed write. sha8 is derived from `identity_str`
    so a species' card is one permanent serial that only re-mints when its
    identity (type/rarity/first-heard) evolves. Never deletes prior blobs."""
    sha8 = sha256_hex(identity_str.encode("utf-8"))[:12]
    rel = f"{rel_dir}/{sha8}.json"
    fp = os.path.join(ROOT, rel)
    if not os.path.exists(fp):                       # append-only: never overwrite
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(payload_obj, f, indent=2, ensure_ascii=False)
            f.write("\n")
    return sha8, rel


def copy_spectrogram(rel_spec, slug):
    """Copy the chosen spectrogram into the published API; return relative url."""
    if not rel_spec:
        return None
    src = os.path.join(SPECTRO_BASE, rel_spec.replace("\\", os.sep))
    if not os.path.exists(src):
        return None
    out_rel = f"assets/spectrograms/{slug}.png"
    dst = os.path.join(ROOT, out_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        shutil.copyfile(src, dst)
    except Exception:
        return None
    return out_rel


# --------------------------------------------------------------------------- #
#  Read Birdy + build                                                          #
# --------------------------------------------------------------------------- #
def load_lifers():
    if not os.path.exists(DB):
        raise SystemExit(f"Birdy DB not found at {DB}. Set BIRDY_DB or run Birdy first.")
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    q = """
    SELECT l.scientific_name AS sci, l.first_verified_at_utc AS first_utc,
           s.common_name, s.wiki_summary, s.wiki_thumb_url, s.wiki_url,
           (SELECT COUNT(*) FROM detections d
              WHERE d.scientific_name=l.scientific_name AND d.review_status!='rejected') AS cnt,
           (SELECT MAX(confidence) FROM detections d
              WHERE d.scientific_name=l.scientific_name) AS best_conf,
           (SELECT spectrogram_path FROM detections d
              WHERE d.scientific_name=l.scientific_name AND d.spectrogram_path IS NOT NULL
              ORDER BY confidence DESC LIMIT 1) AS spec
      FROM lifelist l LEFT JOIN species s ON s.scientific_name=l.scientific_name
     ORDER BY l.first_verified_at_utc ASC
    """
    rows = list(c.execute(q))
    # day frames source: all non-rejected detections grouped by local date
    dets = list(c.execute(
        """SELECT detected_local_date AS date, scientific_name AS sci, common_name AS common,
                  confidence AS conf FROM detections WHERE review_status!='rejected'
           ORDER BY detected_local_date ASC, id ASC"""))
    c.close()
    return rows, dets


def main():
    rows, dets = load_lifers()

    # ---- mint cards ----
    cards = []
    for i, r in enumerate(rows, start=1):
        sci = r["sci"]; common = r["common_name"] or sci
        slug = slugify(sci)
        tkey = type_for(common, sci)
        best = float(r["best_conf"] or 0.0)
        cnt = int(r["cnt"] or 0)
        rar = rarity_for(best, cnt)
        first_date = (r["first_utc"] or "")[:10]
        spec_url = copy_spectrogram(r["spec"], slug)
        summary = (r["wiki_summary"] or "").strip()
        if len(summary) > 320:
            summary = summary[:317].rstrip() + "..."

        card = {
            "schema": "birdy-card/1.0",
            "pokedex": f"{i:03d}",
            "name": common,
            "sci": sci,
            "type": tkey,
            "rarity": rar,
            "hp": 30 + cnt,                       # power scales with how often heard
            "detections": cnt,
            "best_conf": round(best, 4),
            "first_heard": first_date,
            "attacks": attacks_for(tkey, sci),
            "spectrogram": spec_url,
            "art": r["wiki_thumb_url"] or None,
            "wiki_url": r["wiki_url"] or None,
            "flavor": summary,
        }
        # serial = hash of permanent identity (re-mints only if the card evolves)
        identity = "|".join([sci, common, tkey, rar["tier"], first_date])
        sha8, rel = freeze(f"cards/{slug}", card, identity)
        card["serial"] = sha8
        card["serial_url"] = f"{RAW_BASE}/{rel}"
        cards.append(card)

    # ---- freeze day frames (append-only) ----
    by_date = {}
    for d in dets:
        by_date.setdefault(d["date"], []).append(
            {"sci": d["sci"], "common": d["common"], "conf": round(float(d["conf"] or 0), 4)})
    frames = []
    for date in sorted(by_date):
        body = json.dumps({"schema": "birdy-frame/1.0", "date": date,
                           "detections": by_date[date]}, ensure_ascii=False, sort_keys=True)
        sha8 = sha256_hex(body.encode())[:12]
        rel = f"frames/{date}/{sha8}.json"
        fp = os.path.join(ROOT, rel)
        if not os.path.exists(fp):
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            open(fp, "w", encoding="utf-8").write(body + "\n")
        frames.append({"date": date, "sha8": sha8, "detections": len(by_date[date]),
                       "url": f"{RAW_BASE}/{rel}"})

    total_det = sum(len(v) for v in by_date.values())
    holo = sum(1 for c in cards if c["rarity"]["stars"] >= 2)
    summary = {"species": len(cards), "frames": len(frames),
               "detections": total_det, "holo_rares": holo}

    registry = {
        "schema": "rapp-static-api/1.0",
        "name": NAME,
        "generated": NOW,
        "raw_base": RAW_BASE,
        "summary": summary,
        "badge": {"schemaVersion": 1, "label": "🐦 birds",
                  "message": f"{len(cards)} species",
                  "color": "brightgreen" if holo else "green"},
        "cards": cards,
        "frames": frames,
    }

    reg = write_json_stable(os.path.join(ROOT, "registry.json"), registry)
    # registry.js — lets index.html load with zero fetch (works on file://)
    with open(os.path.join(ROOT, "registry.js"), "w", encoding="utf-8") as f:
        f.write("window.BIRDY_REGISTRY = ")
        json.dump(reg, f, ensure_ascii=False, indent=2)
        f.write(";\n")

    write_json_stable(os.path.join(ROOT, "api", "v1", "status.json"),
        {"schema": "rapp-static-api-status/1.0", "generated": NOW, "summary": summary,
         "cards": [{"name": c["name"], "sci": c["sci"], "type": c["type"],
                    "rarity": c["rarity"]["tier"], "serial": c["serial"]} for c in cards]})
    write_json_stable(os.path.join(ROOT, "api", "v1", "badge.json"), registry["badge"], ts_keys=())

    open(os.path.join(ROOT, ".nojekyll"), "w").write(
        "Disable Jekyll so every file (incl. JSON + cards) serves byte-exact.\n")
    write_json_stable(os.path.join(ROOT, "manifest.json"),
        {"schema": "rapp-static-api/1.0", "name": NAME, "raw_base": RAW_BASE,
         "source": "Birdy life list (local BirdNET detector)",
         "entries": [{"name": "registry.json",
                      "sources": [{"label": "primary", "url": f"{RAW_BASE}/registry.json"}]}]},
        ts_keys=())

    print(f"{NAME}: {summary['species']} cards "
          f"({summary['holo_rares']} holo+) · {summary['frames']} day-frames · "
          f"{summary['detections']} detections")
    print("  -> registry.json, registry.js, api/v1/*, cards/, frames/, assets/")


if __name__ == "__main__":
    main()
