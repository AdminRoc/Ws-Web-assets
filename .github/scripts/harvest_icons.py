#!/usr/bin/env python3
"""Harvest item icons from wiki.warframe.com into this assets repo.

Sources (Ws-Web public repo, raw.githubusercontent):
data/item/wm-items.json     -> all Warframe.market items (en names)
data/item/drops-index.json  -> drop-only items not present in wm-items
Resolve each item to a wiki thumbnail via MediaWiki API (pageimages, 300px),
download the image into icons/<NormalizedName>.<ext>, and write manifest.json
mapping original en name -> repo-relative path. Runs daily on a schedule:
existing files are skipped (incremental), so newly added items get picked up
while unchanged icons do not churn the git history.
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
RAW = "https://raw.githubusercontent.com/AdminRoc/Ws-Web/main/data/item/"
OUT_DIR = "icons"

QTY_PREFIX_RE = re.compile(r"^\d+[xX]?\s+")
PURE_CREDITS_RE = re.compile(r"^[\d,]+\s+Credits\s+Cache$", re.I)
PURE_ENDO_RE = re.compile(r"^[\d,]+\s+Endo$", re.I)

# WM 部件名后缀：wiki 无独立页面，归一化到主物品页（如 "Soma Prime Set" -> "Soma Prime"）
PART_SUFFIXES = {
    "Set", "Blueprint", "Barrel", "Receiver", "Stock", "Grip", "Blade",
    "Handle", "Link", "Neuroptics", "Chassis", "Systems", "Head",
    "Ornament", "Guard", "String", "Scabbard", "Pouch", "Limb", "Lower",
    "Upper", "Main", "Weapon", "Set", "Skin", "Helmet", "Sigil",
}


def candidate_titles(name):
    """原样标题优先，其次逐层去尾部件词（最多两层），如
    'Soma Prime Stock' -> ['Soma Prime Stock', 'Soma Prime', 'Soma']"""
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
        url,
        headers={"User-Agent": UA, "Referer": "https://wfspeed.run/"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def normalize(name):
    return QTY_PREFIX_RE.sub("", name).strip()


def is_skippable(name):
    return bool(PURE_CREDITS_RE.match(name) or PURE_ENDO_RE.match(name))


def safe_file(name):
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", name)


def batch_pageimages(titles):
    """titles: list[str]. Returns {title: thumb_url} via prop=pageimages (300px)."""
    out = {}
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        q = urllib.parse.quote("|".join(chunk))
        url = (API + "?action=query&titles=" + q +
               "&prop=pageimages&format=json&pithumbsize=600&redirects=1")
        try:
            data = http_get_json(url)
        except Exception as e:
            print("batch query failed:", e)
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
            t = p.get("title")
            thumb = (p.get("thumbnail") or {}).get("source")
            if not thumb:
                continue
            out[by_title.get(t, t)] = thumb
        time.sleep(0.15)
    return out


def opensearch_fallback(title):
    url = API + "?action=opensearch&search=" + urllib.parse.quote(title) + "&limit=1&format=json"
    try:
        data = http_get_json(url)
    except Exception:
        return None
    cands = data[1] if len(data) > 1 else []
    return cands[0] if cands else None


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    wm = http_get_json(RAW + "wm-items.json")
    drops = http_get_json(RAW + "drops-index.json")
    wm_en = set((it.get("en") or "").lower() for it in wm.get("items", []))
    drop_items = drops.get("items", {})

    # WM 物品若已有有效图标（manifest 已覆盖，由 WM 源下载）则跳过 wiki 查询；
    # 仅 wiki 补漏：WM 无图标(unknown.png) 的物品 + 掉落专属物品
    names = []
    for it in wm.get("items", []):
        if it.get("en") and (not it.get("icon") or it["icon"].endswith("unknown.png")):
            names.append(it["en"])
    for en in drop_items:
        if en.lower() not in wm_en:
            names.append(en)

    norm_map = {}
    skipped = 0
    for en in names:
        if is_skippable(en):
            skipped += 1
            continue
        norm = normalize(en)
        if norm.lower() not in {n.lower() for n in norm_map}:
            norm_map[norm] = en

    print("total items:", len(names), "| skipped currency:", skipped,
          "| unique to query:", len(norm_map))

    thumbs = batch_pageimages(list(norm_map.keys()))
    print("exact/redirect matches:", len(thumbs))

    # 归一化回退：对未命中标题逐层剥离部件后缀再查
    unresolved = [t for t in norm_map if t not in thumbs]
    if unresolved:
        cand_map = {}
        for t in unresolved:
            for c in candidate_titles(t)[1:]:
                cand_map.setdefault(c, t)
        cand_thumbs = batch_pageimages(list(cand_map.keys()))
        for c, orig in cand_map.items():
            if c in cand_thumbs:
                thumbs[orig] = cand_thumbs[c]
        print("resolved via part-normalization:", sum(1 for t in unresolved if t in thumbs))

    unresolved = [t for t in norm_map if t not in thumbs]
    for t in unresolved:
        cand = opensearch_fallback(t)
        if cand and cand != t:
            try:
                d = http_get_json(API + "?action=query&titles=" +
                                  urllib.parse.quote(cand) +
                                  "&prop=pageimages&format=json&pithumbsize=600&redirects=1")
                for _, p in d.get("query", {}).get("pages", {}).items():
                    th = (p.get("thumbnail") or {}).get("source")
                    if th:
                        thumbs[t] = th
            except Exception:
                pass
        time.sleep(0.1)
    print("matched after fallback:", len(thumbs))

    # 与已有 manifest 合并（WM 源下载的条目保留，wiki 只补缺失）
    existing = {}
    if os.path.exists("manifest.json"):
        with open("manifest.json", encoding="utf-8") as f:
            existing = json.load(f)
    manifest = dict(existing)
    new_files = 0

    def dl(url, dest):
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            return False
        try:
            data = fetch_bytes(url)
            if len(data) > 100:
                with open(dest, "wb") as f:
                    f.write(data)
                return True
            return False
        except Exception as e:
            print("download failed:", url, e)
            return False

    jobs = []
    for norm_t, url in thumbs.items():
        en = norm_map[norm_t]
        # 已有条目且文件在 → 跳过（不覆盖、不降级既有高清资产）
        if en in existing and os.path.exists(os.path.join(OUT_DIR, os.path.basename(existing[en]))):
            continue
        ext = os.path.splitext(url.split("?")[0])[1] or ".png"
        # 命名与 manifest 规范一致：en 规范化（非 wiki 页名），保证每日增量零冲突
        fname = safe_file(en) + ext
        dest = os.path.join(OUT_DIR, fname)
        # 大小写不敏感冲突消解（同物品不同拼写，如 Zid-An Asheir vs Zid-an_Asheir）：
        # 复用现有文件路径，避免 Windows 覆盖 / manifest 指向重复文件
        reused = None
        if not os.path.exists(dest):
            low = fname.lower()
            for fn in os.listdir(OUT_DIR):
                if fn.lower() == low and fn != fname:
                    reused = fn
                    break
        if reused:
            jobs.append((en, None, None, "icons/" + reused))
            continue
        jobs.append((en, url, dest, "icons/" + fname))

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(dl, url, dest) for _, url, dest, _ in jobs if url is not None]
        for i, fut in enumerate(as_completed(futs), 1):
            if fut.result():
                new_files += 1
            if i % 100 == 0:
                print("download progress:", i, "/", len(futs), "| new:", new_files, flush=True)

    for en, _, _, rel in jobs:
        manifest[en] = rel

    with open("manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=0, separators=(",", ":"))

    print("manifest entries:", len(manifest), "| new files:", new_files)


if __name__ == "__main__":
    sys.exit(main())
