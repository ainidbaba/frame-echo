"""Expand artwork coverage while retaining the first pilot's three video inputs.

No network access, model training, human ratings or accuracy estimation occurs.
Cached original frame features are used only after compatibility and reproduction
checks. A new run directory preserves both earlier experiments unchanged.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageOps


METHODS = ("colour", "clip")
EXPERIMENT_ID = "expanded-artworks-2026-11-13-v1"
SETTINGS = {"interval": 1.0, "top_k": 6, "min_gap": 3.0, "min_score": None}


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_path(root: Path, value) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def recorded_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def ensure(condition, message):
    if not condition:
        raise RuntimeError(message)


def verify_file(root: Path, name, digest, description):
    path = source_path(root, name)
    ensure(path.is_file() and fingerprint(path) == digest, f"Missing or changed {description}: {path}")
    return path


def validate_features(values, count, dimension):
    ensure(values.shape == (count, dimension), "Feature dimensions do not match the input pool.")
    ensure(np.isfinite(values).all(), "A feature contains non-finite values.")
    ensure(np.allclose(np.linalg.norm(values, axis=1), 1, atol=1e-5), "Features are not unit normalised.")


def validate_case(case, frame_pool, rank_matches):
    matches = case["matches"]
    ensure(len(matches) == SETTINGS["top_k"], "This dataset should return all six time-separated candidates.")
    scores = [row["cosine_similarity"] for row in matches]
    times = [row["timestamp_seconds"] for row in matches]
    ensure(np.isfinite(scores).all() and all(-1 <= v <= 1 for v in scores), "Invalid cosine score.")
    ensure(scores == sorted(scores, reverse=True), "Results are not sorted by score.")
    ensure([row["rank"] for row in matches] == list(range(1, len(matches) + 1)), "Invalid ranks.")
    ensure(all(abs(a - b) + 1e-9 >= SETTINGS["min_gap"] for i, a in enumerate(times) for b in times[i + 1:]), "Time suppression failed.")
    ensure(len(times) == len(set(times)), "Repeated selected timestamp.")
    for row in matches:
        ensure(row["timestamp_seconds"] in frame_pool, "A result timestamp is outside the shared pool.")
        frame = frame_pool[row["timestamp_seconds"]]
        ensure(row["frame_sha256"] == frame["sha256"] and row["frame_path"] == frame["path"], "Wrong source frame attached to a result.")


def load_new_artworks(root, supplied, baseline, output, prepare_reference, expected_count):
    entries = supplied.get("artworks", supplied.get("items")) if isinstance(supplied, dict) else supplied
    ensure(isinstance(entries, list), "Manifest must be an artwork list or an object with artworks[].")
    old_by_id = {art["asset_id"]: art for art in baseline["artworks"]}
    artworks = [dict(art, cohort="original_five") for art in baseline["artworks"]]
    for artwork in artworks:
        verify_file(root, artwork["original_path"], artwork["original_sha256"], "original artwork")
        verify_file(root, artwork["normalized_path"], artwork["normalized_sha256"], "original query")
    for entry in entries:
        asset_id = entry.get("asset_id") or entry.get("id")
        ensure(isinstance(asset_id, str), "Every artwork requires an id.")
        filename = next((entry[key] for key in ("original_path", "local_path", "path", "filename") if entry.get(key)), None)
        ensure(filename, f"Missing original path for {asset_id}.")
        original = source_path(root, filename)
        expected_hash = entry.get("original_sha256") or entry.get("sha256")
        ensure(expected_hash, f"Missing pre-ranking source hash for {asset_id}.")
        ensure(original.is_file() and fingerprint(original) == expected_hash, f"New artwork checksum mismatch: {asset_id}.")
        if asset_id in old_by_id:
            ensure(expected_hash == old_by_id[asset_id]["original_sha256"], f"Old artwork changed in supplied manifest: {asset_id}.")
            continue
        ensure(entry.get("is_public_domain") is True or entry.get("isPublicDomain") is True, f"Explicit public-domain verification required for {asset_id}.")
        object_url = entry.get("object_url") or entry.get("source_url")
        image_url = entry.get("image_url") or entry.get("source_image_url")
        reason = entry.get("selection_rationale") or entry.get("selection_reason") or entry.get("rationale")
        ensure(object_url and image_url and reason, f"Source URLs and pre-ranking selection rationale required for {asset_id}.")
        normalized = output / "queries" / f"{asset_id}.png"
        normalized.parent.mkdir(parents=True, exist_ok=True)
        prepare_reference(original, normalized)
        with Image.open(original) as im:
            dimensions = [im.width, im.height]
        institution = entry.get("institution") or entry.get("museum")
        ensure(institution, f"Museum institution must be named explicitly for {asset_id}.")
        artworks.append({
            "asset_id": asset_id, "institution": institution,
            "object_id": entry.get("object_id", entry.get("objectID")), "title": entry["title"],
            "artist": entry.get("artist", entry.get("artistDisplayName", "Unknown")),
            "date": entry.get("date", entry.get("objectDate", "Unknown")), "object_url": object_url,
            "api_url": entry.get("api_url", ""), "image_url": image_url, "is_public_domain": True,
            "usage_basis": entry.get("usage_basis", "Institution public-domain flag verified before retrieval"),
            "selection_rationale": reason, "theme": entry.get("theme", ""),
            "original_path": recorded_path(root, original), "original_sha256": expected_hash,
            "normalized_path": recorded_path(root, normalized), "normalized_sha256": fingerprint(normalized),
            "dimensions": dimensions, "downloaded_at_utc": entry.get("downloaded_at_utc", ""),
            "license_status": entry.get("license_status", entry.get("share_license_status", "")),
            "source_metadata_path": entry.get("source_metadata_path", ""), "cohort": "new_artworks",
        })
    artworks.sort(key=lambda a: int(a["asset_id"][1:]))
    ensure(len(artworks) == expected_count and [a["asset_id"] for a in artworks] == [f"A{i:02d}" for i in range(1, expected_count + 1)], f"Expected exactly A01–A{expected_count:02d}, keeping the first five unchanged.")
    for field in ("asset_id", "original_sha256", "normalized_sha256"):
        ensure(len({a[field] for a in artworks}) == expected_count, f"Artwork count includes duplicates: {field}.")
    identities = [(a["institution"], a["object_id"]) for a in artworks]
    ensure(len(set(identities)) == expected_count, "The same museum object cannot count as multiple artworks.")
    return artworks


def cached_frames(root, baseline_dir, baseline, video, method, encoder, queries, rank_matches, force):
    file = baseline_dir / "features" / f"{video['asset_id']}_{method}.npz"
    expected_times = np.asarray([f["timestamp"] for f in video["frames"]])
    preprocess = str(getattr(encoder, "preprocess", "RGB -> resize144x144 -> HSV global+3x3 histograms"))
    record = {"method": method, "video_id": video["asset_id"], "cache_path": recorded_path(root, file),
              "cache_sha256_before": fingerprint(file) if file.is_file() else None, "reuse": False,
              "scope": "Feature hashes were not in the 2026-11-10 metadata. Checks cover current raw input hashes, current model, preprocessing, current original-five queries, vector/timestamp shape and reproduction of all original rankings."}
    try:
        ensure(not force, "Re-encoding explicitly requested.")
        old_cases = [c for c in baseline["cases"] if c["video_id"] == video["asset_id"] and c["method"] == method]
        ensure(len(old_cases) == 5, "Original comparison cases missing.")
        ensure(all(c["preprocess"] == preprocess for c in old_cases), "Preprocessing representation changed.")
        with np.load(file, allow_pickle=False) as cache:
            features, old_queries, times = cache["frames"].copy(), cache["queries"].copy(), cache["timestamps"].copy()
        validate_features(features, len(video["frames"]), encoder.dimension)
        validate_features(old_queries, 5, encoder.dimension)
        ensure(np.array_equal(times, expected_times), "Cached timestamps differ from the frame manifest.")
        ensure(np.allclose(old_queries, queries[:5], atol=1e-6, rtol=1e-6), "Cached original queries differ from the current encoder.")
        for index, artwork in enumerate(baseline["artworks"]):
            original = next(c for c in old_cases if c["artwork_id"] == artwork["asset_id"])
            ranked = rank_matches(queries[index], features, expected_times, SETTINGS["top_k"], SETTINGS["min_gap"], min_score=None)
            ensure([r["timestamp"] for r in ranked] == [r["timestamp_seconds"] for r in original["matches"]], "Cached features failed original-ranking reproduction.")
            ensure(np.allclose([r["score"] for r in ranked], [r["cosine_similarity"] for r in original["matches"]], atol=1e-6, rtol=1e-6), "Cached scores failed original-ranking reproduction.")
        record.update(reuse=True, reproduced_original_conditions=5, validation="passed")
        return features, record
    except (RuntimeError, OSError, KeyError, ValueError) as exc:
        record.update(validation="rebuild required", reason=str(exc))
        return None, record


def render_report(root, output, data, image_uri):
    images = {}
    for a in data["artworks"]:
        images[a["asset_id"]] = image_uri(source_path(root, a["normalized_path"]), (520, 380))
    for c in data["cases"]:
        for m in c["matches"]:
            key = m["video_id"] + ":" + m["frame_sha256"]
            if key not in images:
                images[key] = image_uri(source_path(root, m["frame_path"]), (520, 380))
    payload = {"artworks": data["artworks"], "videos": [{"asset_id":v["asset_id"],"description":v["description"]} for v in data["videos"]], "cases":data["cases"], "images":images}
    serialized = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Frame Echo: expanded artwork test</title>
<style>body{margin:0;background:#f5f2e9;color:#242722;font:16px/1.6 system-ui}main{max-width:1320px;margin:auto;padding:28px}h1{font-size:32px}.note{padding:16px;background:#e6ebdf;border-left:3px solid #788668}label{display:inline-flex;gap:9px;align-items:center;margin:8px 22px 8px 0}select{padding:9px;font:inherit;max-width:80vw}.reference{display:flex;gap:25px;align-items:center;margin:24px 0}.reference img{width:260px;height:210px;object-fit:contain}.compare{display:grid;grid-template-columns:1fr 1fr;gap:24px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.match img{width:100%;height:170px;object-fit:contain;background:#ece9df}.match p{font-size:13px;margin:4px 0}small{color:#67715f}a{color:#a14f36}@media(max-width:800px){main{padding:16px}.reference{display:block}.compare{grid-template-columns:1fr}.grid{grid-template-columns:repeat(2,1fr)}}</style>
<main><h1>Expanded artwork development test</h1><p class="note">3 original online reference videos, __TOTAL_ARTWORKS__ public-domain artworks and 353 shared sampled frames. The full comparison contains __CONDITIONS__ conditions and __RANKED_RECORDS__ ranked results. This is a development test, with no participant ratings or accuracy estimate. Original video sources remain pending. New personal videos have not been added.</p>
<p>All __TOTAL_ARTWORKS__ artworks run against all 3 videos using colour and CLIP. Sampling stays at 1 second, with up to 6 results at least 3 seconds apart. The minimum similarity gate is disabled for this controlled baseline comparison. Method scores are not probabilities and cannot be compared as a common calibrated scale.</p>
<p><a href="rankings.csv">Rankings CSV</a> · <a href="results.json">Full metadata</a> · <a href="artworks.csv">Artwork catalogue</a></p>
<label>Video<select id="video"></select></label><label>Artwork<select id="artwork"></select></label>
<div class="reference"><img id="reference" alt="Reference artwork"><div><h2 id="title"></h2><p id="artist"></p><p id="rationale"></p><a id="source">Official public-domain artwork source</a></div></div>
<div class="compare"><section><h2>Colour &amp; spatial layout</h2><div id="colour"></div></section><section><h2>CLIP image features</h2><div id="clip"></div></section></div>
<p class="note">Coverage expanded from 5 to __TOTAL_ARTWORKS__ artworks. The same three videos and sampled frames are reused, so this is not an independent video validation set. Colour uses full images while the original CLIP pipeline uses a centre crop. Temporal spacing does not guarantee different scene content. Neither accepted results nor scores constitute human relevance labels.</p></main>
<script type="application/json" id="payload">__PAYLOAD__</script><script>
const data=JSON.parse(document.getElementById('payload').textContent),$=id=>document.getElementById(id);
function option(id,label){const el=document.createElement('option');el.value=id;el.textContent=label;return el}
data.videos.forEach(v=>$('video').append(option(v.asset_id,v.asset_id+' — '+v.description)));
data.artworks.forEach(a=>$('artwork').append(option(a.asset_id,a.asset_id+' — '+a.title)));
function render(){const a=data.artworks.find(a=>a.asset_id===$('artwork').value);$('reference').src=data.images[a.asset_id];$('title').textContent=a.asset_id+': '+a.title;$('artist').textContent=a.artist+' ('+a.date+')';$('rationale').textContent=a.selection_rationale;$('source').href=a.object_url;for(const method of ['colour','clip']){const target=$(method);target.replaceChildren();const grid=document.createElement('div');grid.className='grid';const c=data.cases.find(c=>c.artwork_id===a.asset_id&&c.video_id===$('video').value&&c.method===method);for(const m of c.matches){const card=document.createElement('div');card.className='match';const img=document.createElement('img');img.src=data.images[m.video_id+':'+m.frame_sha256];img.alt='Sampled frame at '+m.timestamp_label;const p=document.createElement('p');p.textContent='#'+m.rank+' '+m.timestamp_label;const s=document.createElement('small');s.textContent='Cosine score '+Number(m.cosine_similarity).toFixed(4);card.append(img,p,s);grid.append(card)}target.append(grid)}}
$('video').addEventListener('change',render);$('artwork').addEventListener('change',render);render();</script></html>'''
    page = page.replace("__PAYLOAD__", serialized).replace("__TOTAL_ARTWORKS__", str(len(data["artworks"]))).replace("__CONDITIONS__", str(len(data["cases"]))).replace("__RANKED_RECORDS__", str(sum(len(c["matches"]) for c in data["cases"])))
    (output / "index.html").write_text(page, encoding="utf-8")
    # A labelled catalogue makes the unique query set inspectable at a glance.
    columns = 10
    rows = (len(data["artworks"]) + columns - 1) // columns
    catalogue = Image.new("RGB", (2000, rows * 175 + 45), "#f5f2e9")
    catalogue_draw = ImageDraw.Draw(catalogue)
    catalogue_draw.text((12, 10), f"{len(data['artworks'])} unique artwork queries: A01-A05 retained, later IDs added before ranking", fill="#242722")
    for index, artwork in enumerate(data["artworks"]):
        with Image.open(source_path(root, artwork["normalized_path"])) as image:
            tile = ImageOps.contain(image.convert("RGB"), (184, 140))
        col, row = index % columns, index // columns
        x, y = col * 200 + (200 - tile.width) // 2, 40 + row * 175 + (140 - tile.height) // 2
        catalogue.paste(tile, (x, y))
        catalogue_draw.text((col * 200 + 10, 40 + row * 175 + 145), artwork["asset_id"], fill="#242722")
    catalogue.save(output / "artwork-selection-overview.jpg", quality=94)
    # Evidence contact sheets preserve each original image's aspect ratio.
    for start in range(0, len(data["artworks"]), 5):
        selected = data["artworks"][start:start + 5]
        board = Image.new("RGB", (1680, len(selected) * 215 + 50), "#f5f2e9")
        draw = ImageDraw.Draw(board)
        draw.text((12, 10), "REFERENCE | V01 colour / CLIP | V02 colour / CLIP | V03 colour / CLIP: top-ranked full frames", fill="#242722")
        for row, a in enumerate(selected):
            files = [(source_path(root, a["normalized_path"]), a["asset_id"] + " reference")]
            for v in data["videos"]:
                for method in METHODS:
                    c = next(c for c in data["cases"] if c["video_id"] == v["asset_id"] and c["artwork_id"] == a["asset_id"] and c["method"] == method)
                    m = c["matches"][0]
                    files.append((source_path(root, m["frame_path"]), f"{v['asset_id']} {method} {m['timestamp_label']}"))
            for col, (file, label) in enumerate(files):
                with Image.open(file) as im:
                    tile = ImageOps.contain(im.convert("RGB"), (230, 174))
                x, y = col * 240 + (240 - tile.width) // 2, 40 + row * 215 + (174 - tile.height) // 2
                board.paste(tile, (x, y))
                draw.text((col * 240 + 6, 40 + row * 215 + 181), label, fill="#242722")
        board.save(output / f"top1-overview-{start // 5 + 1:02d}.jpg", quality=94)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path, required=True, help="Frozen metadata for new artworks, or all artworks including unchanged A01–A05.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force-reencode", action="store_true")
    parser.add_argument("--expected-artworks", type=int, default=100)
    args = parser.parse_args()
    ensure(args.expected_artworks > 5, "The expanded set must include more than the original five artworks.")
    root = args.project_root.resolve()
    sys.path.insert(0, str(root))
    from app.main import _prepare_reference
    from app.retrieval import get_encoder, rank_matches
    from app.video import timestamp_label
    from scripts.run_pilot import encode_images, image_uri, write_csv, write_json
    import torch
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    output = args.output.resolve() if args.output else root / f"data/pilots/2026-11-13-expanded-artworks-{args.expected_artworks}"
    ensure(not output.exists() or not any(output.iterdir()), "Output must be a new empty directory. Earlier results will not be overwritten.")
    output.mkdir(parents=True, exist_ok=True)
    manifest = args.manifest.resolve()
    manifest_hash = fingerprint(manifest)
    supplied = json.loads(manifest.read_text(encoding="utf-8"))
    baseline_dir = root / "data/pilots/2026-11-10"
    baseline_file = baseline_dir / "results.json"
    baseline_hash = fingerprint(baseline_file)
    baseline_manifest_hash = fingerprint(baseline_dir / "manifest.json")
    round2_file = root / "data/pilots/2026-11-10-round2/results.json"
    round2_hash = fingerprint(round2_file)
    baseline = json.loads(baseline_file.read_text(encoding="utf-8"))
    ensure(baseline["settings"] == {k: SETTINGS[k] for k in ("interval", "top_k", "min_gap")}, "Baseline parameter mismatch.")
    ensure([a["asset_id"] for a in baseline["artworks"]] == [f"A{i:02d}" for i in range(1, 6)], "Original artwork order changed.")
    videos = baseline["videos"]
    ensure([v["asset_id"] for v in videos] == ["V01", "V02", "V03"], "Expected the same three original video inputs.")
    ensure(len({v["sha256"] for v in videos}) == 3, "Duplicate videos cannot inflate video count.")
    for v in videos:
        verify_file(root, v["path"], v["sha256"], "source video")
        for frame in v["frames"]:
            verify_file(root, frame["path"], frame["sha256"], "shared sampled frame")
        times = [f["timestamp"] for f in v["frames"]]
        ensure(len(times) == len(set(times)) and times == sorted(times), "Frame timestamps must be ordered and unique.")
    ensure(sum(len(v["frames"]) for v in videos) == 353, "The shared first-pilot frame pool changed.")
    model_path = root / "data/models/open_clip_model.safetensors"
    ensure(fingerprint(model_path) == baseline["checkpoint"]["sha256"], "Local model differs from first-pilot download record.")
    artworks = load_new_artworks(root, supplied, baseline, output, _prepare_reference, args.expected_artworks)
    runtime = {"python":sys.version,"platform":platform.platform(),"device":"cpu","torch_threads":torch.get_num_threads(),
               "packages":{n:importlib.metadata.version(n) for n in ("numpy","Pillow","opencv-python-headless","torch","open_clip_torch")}}
    code_files = [root / n for n in ("app/retrieval.py", "app/main.py", "app/video.py", "scripts/run_pilot.py")] + [Path(__file__).resolve()]
    plan = {"experiment_id":EXPERIMENT_ID,"date":"2026-11-13","created_at_utc":datetime.now(timezone.utc).isoformat(),
            "design":"Artwork-coverage development test. Original videos reused. No human labels, training or accuracy claim.",
            "selection_frozen_before_ranking":True,"settings":SETTINGS,"methods":list(METHODS),"artworks":artworks,"videos":videos,
            "new_artwork_manifest_path":recorded_path(root, manifest),"new_artwork_manifest_sha256":manifest_hash,
            "baseline_results_sha256":baseline_hash,"baseline_manifest_sha256":baseline_manifest_hash,
            "round2_results_sha256":round2_hash,"checkpoint":baseline["checkpoint"],"environment":runtime,
            "code_hashes":{recorded_path(root,p):fingerprint(p) for p in code_files},
            "planned_counts":{"videos":3,"artworks":len(artworks),"original_artworks":5,"new_artworks":len(artworks)-5,"shared_frames":353,"conditions":len(artworks)*6,"original_conditions":30,"new_conditions":(len(artworks)-5)*6,"ranked_records":len(artworks)*36}}
    write_json(output / "plan.json", plan)
    write_json(output / "manifest.json", {k:v for k,v in plan.items() if k not in {"code_hashes","environment","checkpoint"}})
    rows, cases, timings, cache_records = [], [], [], []
    for method in METHODS:
        started = time.perf_counter()
        encoder = get_encoder(method, model_path)
        timings.append({"stage":"load_model","method":method,"video_id":"","seconds":time.perf_counter()-started})
        preprocess = str(getattr(encoder,"preprocess","RGB -> resize144x144 -> HSV global+3x3 histograms"))
        started = time.perf_counter()
        queries = encode_images(encoder,[source_path(root,a["normalized_path"]) for a in artworks],8)
        validate_features(queries,len(artworks),encoder.dimension)
        timings.append({"stage":"encode_queries","method":method,"video_id":"","seconds":time.perf_counter()-started})
        for video in videos:
            started = time.perf_counter()
            features, cache = cached_frames(root,baseline_dir,baseline,video,method,encoder,queries,rank_matches,args.force_reencode)
            if features is None:
                features = encode_images(encoder,[source_path(root,f["path"]) for f in video["frames"]],16 if method == "clip" else 32)
                validate_features(features,len(video["frames"]),encoder.dimension)
                cache["rebuild_completed"] = True
            elapsed = time.perf_counter()-started
            cache_records.append(cache)
            timings.append({"stage":"reuse_checked_features" if cache["reuse"] else "encode_video","method":method,"video_id":video["asset_id"],"seconds":elapsed})
            feature_file = output / "features" / f"{video['asset_id']}_{method}.npz"
            feature_file.parent.mkdir(exist_ok=True)
            times = [f["timestamp"] for f in video["frames"]]
            np.savez_compressed(feature_file,frames=features,queries=queries,timestamps=np.asarray(times))
            cache["new_feature_path"] = recorded_path(root,feature_file)
            cache["new_feature_sha256"] = fingerprint(feature_file)
            for artwork, query in zip(artworks,queries):
                selected = rank_matches(query,features,times,SETTINGS["top_k"],SETTINGS["min_gap"],min_score=None)
                matches = []
                for rank, match in enumerate(selected,1):
                    frame = video["frames"][match["index"]]
                    row = {"experiment_id":EXPERIMENT_ID,"video_id":video["asset_id"],"artwork_id":artwork["asset_id"],"artwork_title":artwork["title"],
                           "artwork_cohort":artwork["cohort"],"method":method,"model_id":encoder.model_id,"rank":rank,
                           "timestamp_seconds":match["timestamp"],"timestamp_label":timestamp_label(match["timestamp"]),"cosine_similarity":match["score"],
                           "interval_seconds":1.0,"minimum_gap_seconds":3.0,"minimum_score":"","requested_top_k":6,"sampled_frames":len(times),
                           "frame_path":frame["path"],"frame_sha256":frame["sha256"],"video_sha256":video["sha256"],"artwork_sha256":artwork["original_sha256"],
                           "normalized_query_sha256":artwork["normalized_sha256"],"timestamp_source":video["info"]["timestamp_source"],
                           "duration_source":video["info"]["duration_source"],"synthetic":False,"identity_match_status":"not assessed","human_relevance_label":"not collected"}
                    matches.append(row); rows.append(row)
                case = {"video_id":video["asset_id"],"artwork_id":artwork["asset_id"],"method":method,"preprocess":preprocess,
                        "cohort":artwork["cohort"],"matches":matches}
                validate_case(case,{f["timestamp"]:f for f in video["frames"]},rank_matches)
                if artwork["cohort"] == "original_five":
                    original = next(c for c in baseline["cases"] if c["video_id"]==video["asset_id"] and c["artwork_id"]==artwork["asset_id"] and c["method"]==method)
                    ensure([r["timestamp_seconds"] for r in matches]==[r["timestamp_seconds"] for r in original["matches"]],"An original condition did not reproduce the first pilot.")
                    ensure(np.allclose([r["cosine_similarity"] for r in matches],[r["cosine_similarity"] for r in original["matches"]],atol=1e-6,rtol=1e-6),"Original condition scores did not reproduce.")
                cases.append(case)
            print(f"RANKED {video['asset_id']} / {method}: {len(artworks)} artworks, {len(times)} frames, cache reused={cache['reuse']}",flush=True)
    expected = {(v["asset_id"],a["asset_id"],m) for v in videos for a in artworks for m in METHODS}
    ensure(len(cases)==len(artworks)*6 and {(c["video_id"],c["artwork_id"],c["method"]) for c in cases}==expected,"Incomplete or duplicate cross-product conditions.")
    ensure(len(rows)==len(artworks)*36,"Wrong ranked-record count.")
    ensure(Counter(c["cohort"] for c in cases)=={"original_five":30,"new_artworks":(len(artworks)-5)*6},"Wrong original/new condition membership.")
    ensure(fingerprint(baseline_file)==baseline_hash and fingerprint(baseline_dir/"manifest.json")==baseline_manifest_hash and fingerprint(round2_file)==round2_hash,"An earlier experiment changed during this run.")
    ensure(fingerprint(manifest)==manifest_hash,"The artwork selection changed during ranking.")
    for c in cache_records:
        if c["cache_sha256_before"]:
            ensure(fingerprint(source_path(root,c["cache_path"]))==c["cache_sha256_before"],"An original feature cache changed.")
    result = {**plan,"status":"complete","cases":cases,"timings":timings,"cache_validation":cache_records,
              "verified_counts":plan["planned_counts"],"original_30_conditions_reproduced":True,"earlier_experiments_unchanged":True,
              "human_evaluation_status":"not collected","accuracy_status":"not estimated"}
    write_csv(output/"rankings.csv",rows)
    write_csv(output/"timings.csv",timings)
    write_csv(output/"artworks.csv",[{k:a.get(k,"") for k in ("asset_id","cohort","title","artist","date","institution","object_id","object_url","image_url","is_public_domain","selection_rationale","original_path","original_sha256")} for a in artworks])
    write_json(output/"results.json",result)
    render_report(root,output,result,image_uri)
    print(json.dumps({"status":"complete","counts":result["verified_counts"],"baseline_reproduced":True,"output":str(output)},indent=2),flush=True)


if __name__ == "__main__":
    main()
