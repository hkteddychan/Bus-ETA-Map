#!/usr/bin/env python3
"""Refresh KMB / GMB / MTR route+stop reference data for Bus-ETA-Map.

Outputs three JSON files in the repo root:
  - kmb_data.json   (KMB + LWB routes/stops, from data.etabus.gov.hk)
  - gmb_data.json   (GMB route list per region + stops from data.etagmb.gov.hk)
  - mtr_data.json   (MTR heavy-rail lines + Light Rail routes/stops from opendata.mtr.com.hk)

All inputs are public, anonymous, stdlib-only. Every successful fetch writes
`refreshed_at` (UTC ISO) and `source` into the JSON so the git commit proves the
chain ran. If an upstream fails we keep the prior JSON (or write a small stub)
and still record the failure in the JSON so the cron keeps ticking.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

UA = {"User-Agent": "Bus-ETA-Map/1.0 (+github actions)"}
TIMEOUT = 20
HERE = os.path.dirname(os.path.abspath(__file__))


def _get(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        print(f"  ! {url} -> {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _get_json(url: str) -> Any | None:
    body = _get(url)
    if body is None:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        print(f"  ! {url} -> JSONDecodeError: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# KMB  (data.etabus.gov.hk)
# ---------------------------------------------------------------------------

KMB_BASE = "https://data.etabus.gov.hk/v1/transport/kmb"
LWB_BASE = "https://data.etabus.gov.hk/v1/transport/lwb"


def _load_existing(name: str, require_keys: tuple[str, ...] = ()) -> dict | None:
    """Read the previously committed version of `name` from git so we can
    carry forward keys whose upstream endpoint has sunset (e.g. LWB).

    `require_keys` — only accept a ref that contains all of these keys
    non-empty (used so we skip HEAD if its first-time workflow commit
    hadn't yet merged the carried data back in)."""
    import subprocess

    refs = ["HEAD", "HEAD~1", "HEAD~2", "HEAD~3", "HEAD~4", "HEAD~5"]
    for ref in refs:
        try:
            out = subprocess.run(
                ["git", "show", f"{ref}:{name}"],
                cwd=HERE, capture_output=True, check=True, text=True,
            )
            data = json.loads(out.stdout)
            if require_keys and not all(data.get(k) for k in require_keys):
                continue
            return data
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
            continue
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        return None
    try:
        return json.load(open(path, "r", encoding="utf-8"))
    except Exception:
        return None


def fetch_kmb() -> dict:
    routes_raw = _get_json(f"{KMB_BASE}/route")
    stops_raw = _get_json(f"{KMB_BASE}/stop")
    # LWB endpoint (data.etabus.gov.hk/v1/transport/lwb/*) returns 422 since
    # the operator sunset; preserve the last good copy from a recent commit.
    lwb_existing = _load_existing("kmb_data.json", require_keys=("lwb_routes",)) or {}

    out: dict = {
        "refreshed_at": _now_iso(),
        "source": "data.etabus.gov.hk (KMB) + LWB carried over",
        "kmb_routes": [],
        "kmb_stops": [],
        "lwb_routes": list(lwb_existing.get("lwb_routes") or []),
        "lwb_stops": list(lwb_existing.get("lwb_stops") or []),
        "errors": [],
    }

    if routes_raw and "data" in routes_raw:
        for r in routes_raw["data"]:
            out["kmb_routes"].append({
                "route": r.get("route"),
                "bound": r.get("bound"),
                "service_type": r.get("service_type"),
                "orig_en": r.get("orig_en"),
                "orig_tc": r.get("orig_tc"),
                "orig_sc": r.get("orig_sc"),
                "dest_en": r.get("dest_en"),
                "dest_tc": r.get("dest_tc"),
                "dest_sc": r.get("dest_sc"),
            })
    else:
        out["errors"].append("kmb_route")

    if stops_raw and "data" in stops_raw:
        for s in stops_raw["data"]:
            out["kmb_stops"].append({
                "stop": s.get("stop"),
                "name_en": s.get("name_en"),
                "name_tc": s.get("name_tc"),
                "name_sc": s.get("name_sc"),
                "lat": s.get("lat"),
                "long": s.get("long"),
            })
    else:
        out["errors"].append("kmb_stop")

    if not out["lwb_routes"]:
        out["errors"].append("lwb_route_kept_from_disk")

    return out


# ---------------------------------------------------------------------------
# GMB  (data.etagmb.gov.hk)
# ---------------------------------------------------------------------------
# Endpoints used:
#   GET /route/{region}            -> {"data":{"routes":["1","10P", ...]}}
#   GET /stop-route/{stop_id}      -> {"data":[{"route_id","route_seq","stop_seq","name_*"}, ...]}
#   GET /route/{numeric_route_id}  -> {"data":[{"route_id","region","route_code","directions":[...]}, ...]}
#   GET /route-stop/{route_id}/{route_seq} -> {"data":{"route_stops":[{"seq","stop_id","name_*","lat","lng"}]}}
#   GET /stop/{stop_id}            -> {"data":{"coordinates":{"wgs84":{"latitude","longitude"}}, ...}}

GMB_BASE = "https://data.etagmb.gov.hk"
GMB_REGIONS = ["HKI", "KLN", "NT"]
SEED_STOPS = [
    # HKI: well-known terminals and interchanges
    "20003337", "20006944", "20011235", "20007153", "20001661",  # Central / Wan Chai / Causeway Bay area
    # KLN
    "30000117", "30000118", "30000119",  # Tsim Sha Tsui area (placeholder)
    # NT
    "40000120", "40000121", "40000122",  # Tuen Mun area (placeholder)
]


def _seed_stops_from_existing() -> list[str]:
    """Fall back to stop IDs from a previous gmb_data.json so subsequent runs
    get a non-empty starting point even if upstream seeding endpoints change."""
    path = os.path.join(HERE, "gmb_data.json")
    if not os.path.exists(path):
        return SEED_STOPS
    try:
        prev = json.load(open(path, "r", encoding="utf-8"))
    except Exception:
        return SEED_STOPS
    ids = [str(s.get("stop_id")) for s in prev.get("stops", []) if s.get("stop_id")]
    # take a handful spread across the file
    if not ids:
        return SEED_STOPS
    step = max(1, len(ids) // 20)
    return ids[::step][:20]


def fetch_gmb() -> dict:
    out: dict = {
        "refreshed_at": _now_iso(),
        "source": "data.etagmb.gov.hk (GMB HKI/KLN/NT)",
        "wfs_features": 0,
        "routes": [],
        "stops": [],
        "errors": [],
    }

    # 1) regional route code lists
    for region in GMB_REGIONS:
        rl = _get_json(f"{GMB_BASE}/route/{region}")
        if not rl:
            out["errors"].append(f"gmb_route_{region}")
            continue
        for route_code in rl.get("data", {}).get("routes", []):
            out["routes"].append({"region": region, "route_code": route_code})

    # 2) discover numeric route_ids from a small seed of stops
    seed_ids = _seed_stops_from_existing()
    route_id_to_region: dict[int, str] = {}

    for sid in seed_ids:
        sr = _get_json(f"{GMB_BASE}/stop-route/{sid}")
        if not sr or not isinstance(sr.get("data"), list):
            out["errors"].append(f"gmb_stop_route_{sid}")
            continue
        for row in sr["data"]:
            rid = row.get("route_id")
            if rid is None:
                continue
            # determine region from route_id leading digit (200=HKI, 300=KLN, 400=NT)
            sid_prefix = str(rid)[0]
            region = {"2": "HKI", "3": "KLN", "4": "NT"}.get(sid_prefix, "HKI")
            route_id_to_region[rid] = region

    # 3) for each discovered route_id, pull route + each direction's route-stop
    seen_stops: set[str] = set()
    stops_fetched = 0
    ROUTE_CAP = 60  # keep cron under 4 minutes

    for rid, region in list(route_id_to_region.items())[:ROUTE_CAP]:
        rd = _get_json(f"{GMB_BASE}/route/{rid}")
        if not rd or not isinstance(rd.get("data"), list) or not rd["data"]:
            continue
        for numeric_route in rd["data"]:
            for direction in numeric_route.get("directions", []) or []:
                rs_raw = _get_json(
                    f"{GMB_BASE}/route-stop/{rid}/{direction.get('route_seq')}"
                )
                if not rs_raw:
                    out["errors"].append(f"gmb_route_stop_{rid}_{direction.get('route_seq')}")
                    continue
                route_stops = (rs_raw.get("data") or {}).get("route_stops") or []
                for s in route_stops:
                    stop_id = str(s.get("stop_id"))
                    if not stop_id or stop_id in seen_stops:
                        continue
                    seen_stops.add(stop_id)
                    out["stops"].append({
                        "stop_id": stop_id,
                        "name_en": s.get("name_en", ""),
                        "name_tc": s.get("name_tc", ""),
                        "name_sc": s.get("name_sc", ""),
                        "lat": s.get("lat"),
                        "lng": s.get("lng"),
                        "region": region,
                    })
                    stops_fetched += 1

    out["wfs_features"] = len(out["stops"])
    return out


# ---------------------------------------------------------------------------
# MTR  (opendata.mtr.com.hk)
# ---------------------------------------------------------------------------

MTR_HR_URL = "https://opendata.mtr.com.hk/data/mtr_lines_and_stations.csv"
MTR_LR_URL = "https://opendata.mtr.com.hk/data/light_rail_routes_and_stops.csv"


def _parse_mtr_csv(body: bytes) -> list[dict]:
    text = body.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    return [row for row in reader]


def fetch_mtr() -> dict:
    out: dict = {
        "refreshed_at": _now_iso(),
        "source": "opendata.mtr.com.hk (mtr_lines_and_stations + light_rail_routes_and_stops)",
        "metadata": {},
        "routes": [],
        "stops": [],
        "errors": [],
    }

    hr_body = _get(MTR_HR_URL)
    lr_body = _get(MTR_LR_URL)

    if hr_body is None:
        out["errors"].append("mtr_heavy_rail")
    if lr_body is None:
        out["errors"].append("mtr_light_rail")

    routes_by_ref: dict[str, dict] = {}
    seen_stops: set[str] = set()

    if hr_body is not None:
        for row in _parse_mtr_csv(hr_body):
            ref = row.get("Line Code", "").strip()
            if not ref:
                continue
            rid = f"{ref}_{row.get('Direction', '').strip()}"
            entry = routes_by_ref.setdefault(rid, {
                "ROUTE_ID": rid,
                "ROUTE_NAME_CHI": "",
                "ROUTE_NAME_ENG": "",
                "IS_CIRCULAR": "0",
                "LINE_UP": ref,
                "LINE_DOWN": ref,
                "REFERENCE_ID": ref,
                "stops": [],
            })
            sid = row.get("Station ID", "").strip()
            entry["stops"].append({
                "ROUTE_ID": rid,
                "DIRECTION": row.get("Direction", "").strip(),
                "STATION_SEQNO": row.get("Sequence", "").strip(),
                "STATION_ID": sid,
                "STATION_LATITUDE": "",
                "STATION_LONGITUDE": "",
                "STATION_NAME_CHI": row.get("Chinese Name", "").strip(),
                "STATION_NAME_ENG": row.get("English Name", "").strip(),
                "REFERENCE_ID": ref,
            })
            if sid and sid not in seen_stops:
                seen_stops.add(sid)
                out["stops"].append({
                    "STOP_ID": sid,
                    "LINE": ref,
                    "STATION_NAME_CHI": row.get("Chinese Name", "").strip(),
                    "STATION_NAME_ENG": row.get("English Name", "").strip(),
                })

    if lr_body is not None:
        for row in _parse_mtr_csv(lr_body):
            ref = row.get("Line Code", "").strip()
            if not ref:
                continue
            rid = f"LRT_{ref}_{row.get('Direction', '').strip()}"
            entry = routes_by_ref.setdefault(rid, {
                "ROUTE_ID": rid,
                "ROUTE_NAME_CHI": "",
                "ROUTE_NAME_ENG": "",
                "IS_CIRCULAR": "1",
                "LINE_UP": ref,
                "LINE_DOWN": ref,
                "REFERENCE_ID": ref,
                "stops": [],
            })
            sid = row.get("Stop ID", "").strip()
            entry["stops"].append({
                "ROUTE_ID": rid,
                "DIRECTION": row.get("Direction", "").strip(),
                "STATION_SEQNO": row.get("Sequence", "").strip(),
                "STATION_ID": sid,
                "STATION_CODE": row.get("Stop Code", "").strip(),
                "STATION_LATITUDE": "",
                "STATION_LONGITUDE": "",
                "STATION_NAME_CHI": row.get("Chinese Name", "").strip(),
                "STATION_NAME_ENG": row.get("English Name", "").strip(),
                "REFERENCE_ID": ref,
            })
            if sid and sid not in seen_stops:
                seen_stops.add(sid)
                out["stops"].append({
                    "STOP_ID": sid,
                    "LINE": ref,
                    "STATION_NAME_CHI": row.get("Chinese Name", "").strip(),
                    "STATION_NAME_ENG": row.get("English Name", "").strip(),
                })

    out["routes"] = list(routes_by_ref.values())
    out["metadata"] = {
        "total_routes": len(out["routes"]),
        "total_stops": sum(len(r["stops"]) for r in out["routes"]),
        "unique_routes": len({r["REFERENCE_ID"] for r in out["routes"]}),
        "unique_stops": len(seen_stops),
    }
    return out


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe_write(name: str, payload: dict) -> bool:
    path = os.path.join(HERE, name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    routes_count = len(payload.get("routes", payload.get("kmb_routes", [])))
    stops_count = len(payload.get("stops", payload.get("kmb_stops", [])))
    print(
        f"  wrote {name} ({os.path.getsize(path)/1024:.1f} KB) "
        f"routes={routes_count} stops={stops_count}"
    )
    return True


def _stub(name: str, reason: str) -> dict:
    return {
        "refreshed_at": _now_iso(),
        "source": "stub (upstream unreachable)",
        "error": reason,
        "routes": [],
        "stops": [],
    }


def main() -> int:
    print("== fetching KMB/LWB ==")
    kmb = fetch_kmb()
    if not kmb.get("kmb_routes"):
        kmb = _stub("kmb_data.json", "KMB upstream unreachable")
    _safe_write("kmb_data.json", kmb)

    print("== fetching GMB ==")
    gmb = fetch_gmb()
    if not gmb.get("routes"):
        gmb = _stub("gmb_data.json", "GMB upstream unreachable")
    _safe_write("gmb_data.json", gmb)

    print("== fetching MTR ==")
    mtr = fetch_mtr()
    if not mtr.get("routes"):
        mtr = _stub("mtr_data.json", "MTR upstream unreachable")
    _safe_write("mtr_data.json", mtr)

    print("== done ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
