"""Offline check of the diff logic (no Desearch call, no key).

Builds a small snapshot, makes a synthetic later copy with 2 ads removed, 1 ad added
and 1 ad's text edited, and checks that the diff reports exactly that.

Usage:
    python -m pytest test_diff.py
    python test_diff.py path/to/snapshot.json
"""
import copy
import json
import sys

import adlog


def minimal_snapshot():
    def ad(ad_id, text):
        return {
            "ad_id": str(ad_id),
            "text": text,
            "start_date": "2026-07-02",
            "copy_key": "k" + str(ad_id),
            "advertiser": "Example Store",
            "hook": text,
            "library_url": "https://www.facebook.com/ads/library?id=" + str(ad_id),
        }

    return {
        "run_id": "20261005-093112-run1",
        "started_at": "2026-10-05 09:31:12 +0400",
        "stores": {"Example Store": {"ads": [ad(i, "Ad copy " + str(i)) for i in range(1, 5)]}},
    }


def check_diff(snap):
    later = copy.deepcopy(snap)
    later["run_id"] = snap["run_id"] + "-synthetic"
    store = next(iter(later["stores"]))
    ads = later["stores"][store]["ads"]
    removed = [ads[0]["ad_id"], ads[1]["ad_id"]]
    del ads[0:2]
    added = copy.deepcopy(ads[0])
    added["ad_id"] = "999000000000001"
    added["text"] = "Synthetic new ad"
    added["copy_key"] = "synthetic"
    ads.append(added)
    ads[0]["text"] += " (edited)"
    d = adlog.diff_snapshots(snap, later)["stores"][store]
    assert d["disappeared"] == sorted(removed), d["disappeared"]
    assert d["new"] == ["999000000000001"], d["new"]
    assert d["changed"] == [ads[0]["ad_id"]], d["changed"]
    assert len(d["unchanged"]) == len(snap["stores"][store]["ads"]) - 3
    return store, d


def test_diff_reports_removed_added_and_edited():
    store, d = check_diff(minimal_snapshot())
    assert store == "Example Store"
    assert len(d["unchanged"]) == 1


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    snap = json.load(open(path)) if path else minimal_snapshot()
    store, d = check_diff(snap)
    print(
        f"OK {store}: new {d['new']}, disappeared {d['disappeared']}, "
        f"changed {d['changed']}, unchanged {len(d['unchanged'])}"
    )
