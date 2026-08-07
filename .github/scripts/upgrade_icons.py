#!/usr/bin/env python3
"""One-time quality upgrade: fetch 600px wiki thumbnails for every manifest
entry, keep whichever source has larger area (WM official icons vs wiki),
and unify file naming to normalized en names (safe: [A-Za-z0-9_.-]).

Naming rule (also documented in AGENTS.md):
  icons/<Normalized_en>.<ext>   e.g. "Soma Prime Set" -> icons/Soma_Prime_Set.png
Reference always goes through manifest.json (en -> path); the file name is
just a stable storage key.

Usage: python3 .github/scripts/upgrade_icons.py
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

API = "https://wiki.warframe.com/api.php"
UA = "wfspeed-assets/1.0 (+https://wfspeed.run; non-commercial icon harvest)"
OUT = "icons"
TMP = ".upgrade_tmp"

PART_SUFFIXES = {
    "Set", "Blueprint", "Barrel", "Receiver", "Stock", "Grip", "Blade",
    "Handle", "Link", "Neuroptics", "Chassis", "Systems", "Head",
    "Ornament", "Guard", "String", "Scabbard", "Pouch", "Limb", "Lower",
    "Upper", "Main", "Weapon", "Skin", "Helmet", "Sigil",
}


def safe(name):
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", name)


def candidate_titles(name):
    cands = [name]
    parts = name.split()
    for _ in range(2):
        if len(parts) <= 1:
            break
        parts = parts[:-1]
        cands.append(" ".join(parts))
    return cands


def http_get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_bytes(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Referer": "https://wfspeed.run/"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def batch_pageimages(titles, size=600):
    out = {}
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        q = urllib.parse.quote("|".join(chunk))
        url = (API + "?action=query&titles=" + q +
               "&prop=pageimages&format=json&pithumbsize=" + str(size) +
               "&redirects=1")
        try:
            data = http_get_json(url)
        except Exception as e:
            print("batch failed:", e, flush=True)
            time.sleep(1)
            continue
        pages = data.get("query", {}).get("pages", {})
        redirects = {r["from"]: r["to"] for r in data.get("query", {}).get("redirects", [])}
        by_title = {}
        for orig in chunk:
            by_title[redirects.get(orig, orig)] = orig
        for _, p in pages.items():
            if "missing" in p:
                continue
            th = (p.get("thumbnail") or {}).get("source")
            if th:
                out[by_title.get(p.get("title"), p.get("title"))] = th
        time.sleep(0.15)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(TMP, exist_ok=True)
    with open("manifest.json", encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. naming conflict check
    seen = {}
    conflicts = []
    for en in manifest:
        new = safe(en)
        if new in seen and seen[new] != en:
            conflicts.append((en, new))
        seen.setdefault(new, en)
    print("naming conflicts:", len(conflicts), flush=True)
    for c in conflicts[:10]:
        print("  ", c, flush=True)

    # 2. query wiki 600px for every en (with part-normalization fallback)
    thumbs = {}
    missing_ok = []
    all_titles = list(manifest.keys())
    found = batch_pageimages(all_titles)
    thumbs.update(found)
    unresolved = [t for t in all_titles if t not in thumbs]
    if unresolved:
        cand_map = {}
        for t in unresolved:
            for c in candidate_titles(t)[1:]:
                cand_map.setdefault(c, t)
        cand_thumbs = batch_pageimages(list(cand_map.keys()))
        for c, orig in cand_map.items():
            if c in cand_thumbs:
                thumbs[orig] = cand_thumbs[c]
    print("wiki 600px matched:", len(thumbs), "/", len(manifest), flush=True)

    # 3. download & compare per entry
    def work(en, old_path, wiki_url):
        ext_old = os.path.splitext(old_path)[1] or ".png"
        if wiki_url:
            ext_wiki = os.path.splitext(wiki_url.split("?")[0])[1] or ".png"
            try:
                data = fetch_bytes(wiki_url)
                if len(data) > 100:
                    tmpf = os.path.join(TMP, safe(en) + ext_wiki)
                    with open(tmpf, "wb") as f:
                        f.write(data)
                    return en, tmpf, ext_wiki, True
            except Exception:
                pass
        return en, None, ext_old, False

    jobs = []
    for en, old_path in manifest.items():
        jobs.append((en, old_path, thumbs.get(en)))
    pool = 8
    results = {}
    with ThreadPoolExecutor(max_workers=pool) as ex:
        futs = [ex.submit(work, *j) for j in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            en, tmpf, ext, got = fut.result()
            results[en] = (tmpf, ext, got)
            if i % 500 == 0:
                print("checked", i, "/", len(jobs), flush=True)

    # 4. pick best (larger area) and rename to normalized name
    from PIL import Image
    changed = kept_wm = used_wiki = 0
    new_manifest = {}
    for en, (tmpf, ext_wiki, got) in results.items():
        old_path = manifest[en]
        oldf = os.path.join(OUT, os.path.basename(old_path))
        new_name = safe(en) + ext_wiki
        new_path = os.path.join(OUT, new_name)
        best = None
        if got and tmpf and os.path.exists(tmpf):
            try:
                with Image.open(tmpf) as im:
                    wa, ha = im.size
            except Exception:
                wa = ha = 0
            try:
                with Image.open(oldf) as im:
                    wo, ho = im.size
            except Exception:
                wo = ho = 0
            if wa * ha >= wo * ho and wa * ha > 0:
                best = tmpf
                used_wiki += 1
            else:
                best = oldf
                kept_wm += 1
        else:
            best = oldf
        if os.path.exists(best):
            if os.path.abspath(new_path) != os.path.abspath(best):
                os.makedirs(os.path.dirname(new_path), exist_ok=True)
                os.replace(best, new_path)
            changed += 1
        new_manifest[en] = "icons/" + new_name

    # cleanup tmp
    for fn in os.listdir(TMP):
        try:
            os.remove(os.path.join(TMP, fn))
        except OSError:
            pass
    try:
        os.rmdir(TMP)
    except OSError:
        pass

    # 5. remove orphans (files not referenced by new manifest)
    referenced = {os.path.basename(p) for p in new_manifest.values()}
    orphans = []
    for fn in os.listdir(OUT):
        if fn not in referenced:
            orphans.append(fn)
    for fn in orphans:
        try:
            os.remove(os.path.join(OUT, fn))
        except OSError:
            pass
    print("orphans removed:", len(orphans), flush=True)

    with open("manifest.json", "w", encoding="utf-8") as f:
        json.dump(new_manifest, f, ensure_ascii=False, indent=0, separators=(",", ":"))
    print("entries:", len(new_manifest), "| wiki-picked:", used_wiki,
          "| wm-kept:", kept_wm, flush=True)


if __name__ == "__main__":
    sys.exit(main())
