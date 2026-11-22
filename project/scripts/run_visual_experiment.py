"""Controlled development comparison for balanced visual retrieval.

Keeps the first pilot intact. Produces rankings and a blank human feedback page;
it does not estimate accuracy or fabricate participant responses.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import html
import json
import os
from pathlib import Path
import random
import shutil
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageOps

EXPERIMENT_ID = "visual-round2-2026-11-10-v1"
VARIANTS = {
    "A": "原版 CLIP · 中心裁剪",
    "B": "仅转场筛选 · 中心裁剪",
    "C": "仅保留整图",
    "D": "保留整图＋转场筛选",
    "E": "综合视觉 · 内容＋颜色＋空间颜色布局",
}
REVIEW_PAIRS = [("V01", "A05"), ("V02", "A01"), ("V03", "A03")]
REVIEW_SEED = 20261110


def run(root: Path):
    sys.path.insert(0, str(root))
    from app.frame_quality import analyze_video_quality, DEFAULT_THRESHOLDS, QUALITY_VERSION
    from app.retrieval import get_encoder
    from app.visual_similarity import (cosine_scores, global_and_layout_features, weighted_rank_fusion,
                                       select_scored_frames, full_frame_preprocess, DEFAULT_WEIGHTS, BALANCED_MODEL_ID)
    from app.video import timestamp_label
    from scripts.run_pilot import sha256, write_json, write_csv, image_uri, encode_images
    from scripts.review_page import write_review_page
    import torch

    baseline_dir = root / "data/pilots/2026-11-10"
    output = root / "data/pilots/2026-11-10-round2"
    output.mkdir(parents=True, exist_ok=True)
    baseline_file = baseline_dir / "results.json"
    baseline_hash = sha256(baseline_file)
    data = json.loads(baseline_file.read_text(encoding="utf-8"))
    for video in data["videos"]:
        if sha256(root / video["path"]) != video["sha256"]:
            raise RuntimeError("A source video changed; this comparison requires the original inputs.")
        if any(sha256(root / frame["path"]) != frame["sha256"] for frame in video["frames"]):
            raise RuntimeError("A shared first-pilot frame changed.")
    for artwork in data["artworks"]:
        for field, fingerprint in (("original_path", "original_sha256"), ("normalized_path", "normalized_sha256")):
            if sha256(root / artwork[field]) != artwork[fingerprint]:
                raise RuntimeError("An artwork input changed.")
    model_path = root / "data/models/open_clip_model.safetensors"
    if sha256(model_path) != data["checkpoint"]["sha256"]:
        raise RuntimeError("The model differs from the first pilot.")
    code_paths = ["app/frame_quality.py", "app/visual_similarity.py", "app/retrieval.py", "scripts/run_visual_experiment.py", "scripts/review_page.py"]
    plan = {"experiment_id": EXPERIMENT_ID, "date": "2026-11-10", "goal": "Overall visual relationship: colour, composition and content",
            "design": "Development experiment; no relevance labels or participant responses yet",
            "baseline_results_sha256": baseline_hash, "settings": data["settings"], "variants": VARIANTS,
            "quality": {"version": QUALITY_VERSION, "probe_offset_seconds": 0.15, "thresholds": asdict(DEFAULT_THRESHOLDS)},
            "fusion": {"weights": DEFAULT_WEIGHTS, "k": 60, "ties": "average ranks for exact ties", "pool": "eligible candidates only",
                       "status": "predeclared heuristic, not tuned optimum", "layout": "coarse spatial colour distribution, not full composition understanding"},
            "review": {"pairs": REVIEW_PAIRS, "selection": "deduplicated union of each version's top 3", "seed": REVIEW_SEED,
                       "role": "targeted diagnostic cases chosen from the first pilot, not an independent validation set"},
            "checkpoint": data["checkpoint"], "code_hashes": {name: sha256(root / name) for name in code_paths}}
    plan_file = output / "plan.json"
    if plan_file.exists() and json.loads(plan_file.read_text(encoding="utf-8")) != plan:
        raise RuntimeError("The experiment plan or code changed. Use a new experiment ID/directory, preserving the old run.")
    write_json(plan_file, plan)
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    quality, eligibility = {}, {}
    quality_rows = []
    for video in data["videos"]:
        video_id = video["asset_id"]
        started = time.perf_counter()
        items = analyze_video_quality(root / video["path"], [f["timestamp"] for f in video["frames"]], probe_offset=0.15)
        assert len(items) == len(video["frames"])
        quality[video_id] = items
        eligibility[video_id] = np.asarray([item["eligible"] for item in items], dtype=bool)
        for frame, item in zip(video["frames"], items):
            assert abs(frame["timestamp"] - item["timestamp"]) < 1e-8
            quality_rows.append({"video_id": video_id, "timestamp_seconds": frame["timestamp"], "frame_sha256": frame["sha256"],
                                 "eligible": item["eligible"], "reasons": item["reason"], "mean_luma": item["mean_luma"],
                                 "white_fraction": item["white_fraction"], "black_fraction": item["black_fraction"],
                                 "laplacian_variance": item["laplacian_variance"], "previous_difference": item["prev_diff"], "next_difference": item["next_diff"]})
        print(f"QUALITY {video_id}: {int((~eligibility[video_id]).sum())}/{len(items)} candidates excluded by fixed heuristic ({time.perf_counter()-started:.2f}s)", flush=True)
    write_json(output / "quality-diagnostics.json", quality)
    write_csv(output / "quality-diagnostics.csv", quality_rows)

    encoder = get_encoder("clip", model_path)
    center_preprocess = str(encoder.preprocess)
    encoder.preprocess = full_frame_preprocess(encoder.preprocess)
    full_preprocess = str(encoder.preprocess)
    query_paths = [root / artwork["normalized_path"] for artwork in data["artworks"]]
    full_queries = encode_images(encoder, query_paths, 8)
    records, cases = [], []
    full_feature_dir = output / "features"
    full_feature_dir.mkdir(exist_ok=True)
    for video in data["videos"]:
        video_id = video["asset_id"]
        center = np.load(baseline_dir / "features" / f"{video_id}_clip.npz")
        colour = np.load(baseline_dir / "features" / f"{video_id}_colour.npz")
        global_frames, layout_frames = global_and_layout_features(colour["frames"])
        global_queries, layout_queries = global_and_layout_features(colour["queries"])
        full_frames = encode_images(encoder, [root / frame["path"] for frame in video["frames"]], 16)
        np.savez_compressed(full_feature_dir / f"{video_id}_clip_full.npz", frames=full_frames, queries=full_queries,
                            timestamps=np.asarray([frame["timestamp"] for frame in video["frames"]]))
        assert full_frames.shape == (len(video["frames"]), 512)
        assert np.allclose(np.linalg.norm(full_frames, axis=1), 1, atol=1e-5)
        times = np.asarray([frame["timestamp"] for frame in video["frames"]])
        mask = eligibility[video_id]
        for query_index, artwork in enumerate(data["artworks"]):
            center_scores = cosine_scores(center["queries"][query_index], center["frames"])
            full_scores = cosine_scores(full_queries[query_index], full_frames)
            global_scores = cosine_scores(global_queries[query_index], global_frames)
            layout_scores = cosine_scores(layout_queries[query_index], layout_frames)
            fusion_scores = np.zeros(len(times), dtype=float)
            fusion_scores[mask] = weighted_rank_fusion({"content": full_scores[mask], "colour": global_scores[mask], "layout": layout_scores[mask]})
            configurations = {"A": (center_scores, None), "B": (center_scores, mask), "C": (full_scores, None),
                              "D": (full_scores, mask), "E": (fusion_scores, mask)}
            for variant, (scores, eligible) in configurations.items():
                selected = select_scored_frames(scores, times, data["settings"]["top_k"], data["settings"]["min_gap"], eligible)
                matches = []
                for rank, match in enumerate(selected, 1):
                    frame = video["frames"][match["index"]]
                    record = {"experiment_id": EXPERIMENT_ID, "variant": variant, "variant_label": VARIANTS[variant],
                              "video_id": video_id, "artwork_id": artwork["asset_id"], "rank": rank,
                              "timestamp_seconds": match["timestamp"], "timestamp_label": timestamp_label(match["timestamp"]),
                              "score": match["score"], "score_type": "weighted_RRF" if variant == "E" else "cosine",
                              "frame_index": match["index"], "frame_path": frame["path"], "frame_sha256": frame["sha256"],
                              "quality_eligible": bool(mask[match["index"]]), "quality_reason": quality[video_id][match["index"]]["reason"],
                              "content_full_cosine": float(full_scores[match["index"]]), "global_colour_cosine": float(global_scores[match["index"]]),
                              "spatial_colour_cosine": float(layout_scores[match["index"]])}
                    matches.append(record)
                    records.append(record)
                cases.append({"video_id": video_id, "artwork_id": artwork["asset_id"], "variant": variant, "matches": matches})
                if variant == "A":
                    original = next(case for case in data["cases"] if case["video_id"] == video_id and case["artwork_id"] == artwork["asset_id"] and case["method"] == "clip")
                    assert [row["timestamp_seconds"] for row in matches] == [row["timestamp_seconds"] for row in original["matches"]], "Baseline must reproduce first pilot exactly."
                    assert np.allclose([row["score"] for row in matches], [row["cosine_similarity"] for row in original["matches"]], atol=1e-7)
        print(f"RANKED {video_id}: five variants × five queries", flush=True)
    assert len(cases) == 75
    for case in cases:
        scores = [row["score"] for row in case["matches"]]
        assert scores == sorted(scores, reverse=True)
        times = [row["timestamp_seconds"] for row in case["matches"]]
        assert all(abs(a - b) + 1e-9 >= data["settings"]["min_gap"] for i, a in enumerate(times) for b in times[i + 1:])
        if case["variant"] in {"B", "D", "E"}:
            assert all(row["quality_eligible"] for row in case["matches"])
    diagnostics = []
    for video in data["videos"]:
        for variant in VARIANTS:
            relevant_cases = [case for case in cases if case["video_id"] == video["asset_id"] and case["variant"] == variant and case["matches"]]
            first = [case["matches"][0]["frame_sha256"] for case in relevant_cases]
            counts = Counter(first)
            diagnostics.append({"video_id": video["asset_id"], "variant": variant, "queries_with_results": len(first),
                                "unique_top1_frames": len(counts), "largest_group_sharing_top1": max(counts.values(), default=0)})
    failure_index = min(range(len(data["videos"][0]["frames"])), key=lambda i: abs(data["videos"][0]["frames"][i]["timestamp"] - 78.022))
    failure = {"video_id": "V01", "artwork_id": "A05", "timestamp_seconds": data["videos"][0]["frames"][failure_index]["timestamp"],
               "quality": quality["V01"][failure_index], "variants": {}}
    for variant in VARIANTS:
        case = next(case for case in cases if case["video_id"] == "V01" and case["artwork_id"] == "A05" and case["variant"] == variant)
        rank = next((row["rank"] for row in case["matches"] if row["frame_index"] == failure_index), None)
        failure["variants"][variant] = {"selected_rank": rank, "top1_timestamp": case["matches"][0]["timestamp_seconds"] if case["matches"] else None}
    result = {"plan": plan, "artworks": data["artworks"], "videos": data["videos"], "cases": cases,
              "quality_summary": {video["asset_id"]: {"total": len(video["frames"]), "excluded": int((~eligibility[video["asset_id"]]).sum()),
                                  "reasons": dict(Counter(reason for row in quality[video["asset_id"]] for reason in row["reasons"]))} for video in data["videos"]},
              "query_discrimination_diagnostics": diagnostics, "known_transition_case": failure,
              "center_preprocess": center_preprocess, "full_preprocess": full_preprocess, "baseline_unchanged": sha256(baseline_file) == baseline_hash,
              "status": "functional comparison complete; human ratings pending"}
    write_csv(output / "rankings.csv", records)
    write_csv(output / "query-discrimination.csv", diagnostics)
    write_json(output / "results.json", result)
    make_reports(root, output, result, image_uri, write_json, write_csv, write_review_page)
    print(json.dumps({"conditions": len(cases), "ranked_records": len(records), "quality_summary": result["quality_summary"],
                      "known_transition_selected_rank": {key: value["selected_rank"] for key, value in failure["variants"].items()},
                      "output": str(output)}, ensure_ascii=False), flush=True)


def make_reports(root, output, result, image_uri, write_json, write_csv, write_review_page):
    images = {}
    def uri(key, path):
        if key not in images:
            images[key] = image_uri(root / path, (520, 360))
        return key
    for artwork in result["artworks"]:
        uri(artwork["asset_id"], artwork["normalized_path"])
    for case in result["cases"]:
        for match in case["matches"]:
            uri(case["video_id"] + ":" + match["frame_sha256"], match["frame_path"])
    payload = {"variants": VARIANTS, "artworks": result["artworks"], "videos": [{"asset_id":v["asset_id"], "description":v["description"]} for v in result["videos"]],
               "cases": result["cases"], "images": images}
    serialized = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    template = '''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Frame Echo · 综合视觉排序对照</title>
<style>body{margin:0;background:#f5f2e9;color:#242722;font:15px/1.6 system-ui}main{max-width:1350px;margin:auto;padding:28px}h1{font-size:30px}.note{padding:14px 18px;background:#e6ebdf;border-left:3px solid #788668}label{display:inline-flex;gap:8px;align-items:center;margin:8px 18px 8px 0}select{padding:9px;max-width:95%;font:inherit;border:1px solid #bbc1b1;background:#fffaf0}.reference{display:flex;align-items:center;gap:24px;margin:20px 0}.reference img{width:240px;height:200px;object-fit:contain;background:#e7e5da}.compare{display:grid;grid-template-columns:1fr 1fr;gap:22px}.panel{background:#fcfaf5;padding:16px;border:1px solid #d8d9cd}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.card{font-size:12px}.card img{width:100%;height:170px;object-fit:contain;background:#e9e8dd}a{color:#a7472f}.muted{color:#737b67;font-size:12px}.warning{color:#8d3d2a}@media(max-width:800px){main{padding:16px}.compare{grid-template-columns:1fr}.reference{display:block}.grid{grid-template-columns:repeat(2,1fr)}}:focus-visible{outline:3px solid #a7472f;outline-offset:3px}</style>
<main><h1>综合视觉排序 · 第二轮开发实验</h1><p class="note">比较内容、颜色和空间颜色布局的组合。共 5 个版本，仍使用相同的 3 段视频、5 张作品和 353 张候选帧。这是开发对照，尚未证明精度提升。</p>
<p><a href="review.html">打开简短图像反馈页</a> · <a href="rankings.csv">导出完整排名</a> · <a href="quality-diagnostics.csv">查看筛选诊断</a></p>
<label>视频<select id="video"></select></label><label>艺术作品<select id="artwork"></select></label>
<div class="reference"><img id="reference" alt="查询作品"><div><h2 id="title"></h2><p id="artist"></p><a id="source">馆藏来源</a></div></div>
<div class="compare"><section class="panel"><label>左侧版本<select id="left"></select></label><div id="left-results"></div></section><section class="panel"><label>右侧版本<select id="right"></select></label><div id="right-results"></div></section></div>
<p class="muted">各版本分数仅用于自身排序；综合版本为排名融合分数，不是概率。筛选规则会漏检或误判；保留整图与中心裁剪的效果也需人工判断。原始第一轮记录保留。</p></main>
<script type="application/json" id="payload">__PAYLOAD__</script><script>
const d=JSON.parse(document.getElementById('payload').textContent);const $=id=>document.getElementById(id);
function option(value,label){const e=document.createElement('option');e.value=value;e.textContent=label;return e;}
d.videos.forEach(v=>$('video').append(option(v.asset_id,v.asset_id+' · '+v.description)));d.artworks.forEach(a=>$('artwork').append(option(a.asset_id,a.asset_id+' · '+a.title)));
for(const [id,name] of Object.entries(d.variants)){ $('left').append(option(id,id+' · '+name));$('right').append(option(id,id+' · '+name)); }$('left').value='A';$('right').value='E';
function renderPanel(side){const variant=$(side).value;const c=d.cases.find(c=>c.variant===variant&&c.video_id===$('video').value&&c.artwork_id===$('artwork').value);const target=$(side+'-results');target.replaceChildren();const summary=document.createElement('p');summary.className='muted';summary.textContent=c.matches.length+' 个候选 · 至少间隔 3 秒';target.append(summary);const grid=document.createElement('div');grid.className='grid';for(const m of c.matches){const card=document.createElement('div');card.className='card';const image=document.createElement('img');image.src=d.images[c.video_id+':'+m.frame_sha256];image.alt='候选视频帧';const text=document.createElement('p');text.textContent='#'+m.rank+' · '+m.timestamp_label;const score=document.createElement('div');score.className='muted';score.textContent=m.score_type+' '+Number(m.score).toFixed(5);card.append(image,text,score);if(!m.quality_eligible){const warning=document.createElement('div');warning.className='warning';warning.textContent='转场规则标记：'+m.quality_reason;card.append(warning)}grid.append(card)}target.append(grid)}
function render(){const a=d.artworks.find(a=>a.asset_id===$('artwork').value);$('reference').src=d.images[a.asset_id];$('title').textContent=a.title;$('artist').textContent=a.artist+' · '+a.date;$('source').href=a.object_url;renderPanel('left');renderPanel('right')}for(const id of ['video','artwork','left','right'])$(id).addEventListener('change',render);render();
</script></html>'''
    (output / "index.html").write_text(template.replace("__PAYLOAD__", serialized), encoding="utf-8")
    # Targeted, predeclared cases; these are development feedback, not held-out tests.
    candidates, membership = {}, {}
    for video_id, artwork_id in REVIEW_PAIRS:
        for case in result["cases"]:
            if (case["video_id"], case["artwork_id"]) != (video_id, artwork_id):
                continue
            artwork = next(a for a in result["artworks"] if a["asset_id"] == artwork_id)
            for match in case["matches"][:3]:
                key = artwork_id + ":" + video_id + ":" + match["frame_sha256"]
                if key not in candidates:
                    candidate_id = "C" + hashlib.sha256(key.encode()).hexdigest()[:12]
                    candidates[key] = {"candidate_id": candidate_id, "artwork_id": artwork_id, "artwork_title": artwork["title"],
                                       "artist": artwork["artist"], "video_id": video_id, "frame_sha256": match["frame_sha256"],
                                       "reference_image": images[artwork_id], "frame_image": images[video_id+":"+match["frame_sha256"]],
                                       "canonical_timestamp": match["timestamp_seconds"]}
                    membership[candidate_id] = []
                membership[candidates[key]["candidate_id"]].append({"variant": case["variant"], "rank": match["rank"], "timestamp_seconds": match["timestamp_seconds"]})
    items = list(candidates.values())
    random.Random(REVIEW_SEED).shuffle(items)
    for order, item in enumerate(items, 1):
        item["presentation_order"] = order
    write_review_page(output / "review.html", items, EXPERIMENT_ID, REVIEW_SEED)
    write_json(output / "review-key.json", {"pairs": REVIEW_PAIRS, "seed": REVIEW_SEED, "items": [{key:value for key,value in item.items() if key not in {"reference_image", "frame_image"}} for item in items], "membership": membership})
    # The blank CSV has a schema only; it contains no simulated human ratings.
    fields = "experiment_id,reviewer_id,candidate_id,artwork_id,video_id,frame_sha256,presentation_order,timestamp_seconds,colour,composition,content,overall,relevance,quality_flags,comment,completed\n"
    (output / "review-template.csv").write_text(fields, encoding="utf-8")
    print(f"REVIEW: {len(items)} unique query/frame pairs, no ratings populated", flush=True)
    # Full-frame top-one comparison without turning input policies into a visual crop.
    board = Image.new("RGB", (1440, len(result["artworks"]) * 205 + 45), "#f5f2e9")
    draw = ImageDraw.Draw(board)
    draw.text((12, 10), "V01 / reference | A baseline | B filter | C full-frame | D full+filter | E balanced visual", fill="#242722")
    for row, artwork in enumerate(result["artworks"]):
        paths = [(root / artwork["normalized_path"], artwork["asset_id"] + " reference")]
        for variant in VARIANTS:
            case = next(c for c in result["cases"] if c["video_id"] == "V01" and c["artwork_id"] == artwork["asset_id"] and c["variant"] == variant)
            if case["matches"]:
                match = case["matches"][0]
                paths.append((root / match["frame_path"], variant + " " + match["timestamp_label"]))
            else:
                paths.append((None, variant + " no candidates"))
        for column, (path, label) in enumerate(paths):
            if path is not None:
                with Image.open(path) as image:
                    tile = ImageOps.contain(image.convert("RGB"), (230, 166))
                board.paste(tile, (column * 240 + (240-tile.width)//2, 38+row*205+(166-tile.height)//2))
            draw.text((column*240+6, 38+row*205+175), label, fill="#242722")
    board.save(output / "v01-top1-comparison.jpg", quality=94)
    summary = {"experiment_id": EXPERIMENT_ID, "condition_count": len(result["cases"]), "ranking_records": sum(len(c["matches"]) for c in result["cases"]),
               "review_item_count": len(items), "quality_summary": result["quality_summary"],
               "known_transition_case": result["known_transition_case"], "baseline_unchanged": result["baseline_unchanged"],
               "accuracy_or_relevance_improvement": "not measured; real human feedback pending"}
    write_json(output / "summary.json", summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    options = parser.parse_args()
    run(options.project_root.resolve())
