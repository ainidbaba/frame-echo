"""Audit and describe the first four Frame Echo exports without changing the study.

The CSV output is a machine-readable analysis intermediate. The main deliverable is
an offline HTML report. No questionnaire, retrieval result or model is modified.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import json
import re
import shutil
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

DIMENSIONS = ("colour", "composition", "content", "overall")
LEGACY = "frame-echo-2026-11-17-self-recorded-r1"
V3 = "frame-echo-diverse-review12-v3-20261118"
COHORT_LABELS = {"legacy20": "Original 20-pair forms", "v3-diverse12": "Diverse 12-artwork forms"}
INPUTS = [
    (f"frame-echo_{LEGACY}_P01.csv", "legacy20", "P01", 20),
    (f"frame-echo_{LEGACY}_P02.csv", "legacy20", "P02", 20),
    (f"frame-echo_{V3}_Q01_N01.csv", "v3-diverse12", "N01", 12),
    (f"frame-echo_{V3}_Q02_N02.csv", "v3-diverse12", "N02", 12),
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_payload(path):
    match = re.search(r'<script id="review-data" type="application/json">(.*?)</script>', path.read_text(), re.S)
    if not match:
        raise ValueError(f"Missing questionnaire payload: {path}")
    return json.loads(match.group(1))


def summary(rows):
    ratings = {}
    for dimension in DIMENSIONS:
        numeric = [r[dimension] for r in rows if isinstance(r[dimension], int)]
        ratings[dimension] = {
            "numeric_n": len(numeric), "unsure_n": sum(r[dimension] == "unsure" for r in rows),
            "missing_n": sum(r[dimension] is None for r in rows),
            "mean": statistics.mean(numeric) if numeric else None,
            "median": statistics.median(numeric) if numeric else None,
            "distribution": {str(n): numeric.count(n) for n in range(1, 6)},
        }
    return {
        "rating_rows": len(rows), "reviewer_codes": sorted({r["reviewer_id"] for r in rows}),
        "unique_artworks": len({r["artwork_id"] for r in rows}),
        "unique_candidate_pairs": len({r["candidate_id"] for r in rows}),
        "ratings": ratings, "relevance": dict(Counter(r["relevance"] or "missing" for r in rows)),
        "colour_ge4_content_le2": sum(isinstance(r["colour"], int) and isinstance(r["content"], int)
                                       and r["colour"] >= 4 and r["content"] <= 2 for r in rows),
        "overall_ge4": sum(isinstance(r["overall"], int) and r["overall"] >= 4 for r in rows),
        "overall_le2": sum(isinstance(r["overall"], int) and r["overall"] <= 2 for r in rows),
    }


def image_uri(path):
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def esc(value):
    return html.escape(str(value))


def table(headers, rows):
    return '<div class="table-wrap"><table><thead><tr>' + "".join(f"<th>{esc(h)}</th>" for h in headers) + \
           "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in rows) + "</tbody></table></div>"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--downloads", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project, output = args.project.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for sub in ("raw", "provenance"):
        (output / sub).mkdir(exist_ok=True)
    pilot = project / "data/pilots/2026-11-17-self-recorded-r1"
    diverse = project / "data/evaluation/2026-11-18-diverse-review12-v3"
    key_paths = {"legacy20": pilot / "organizer/review-key.json", "v3-diverse12": diverse / "organizer/form-item-key.json"}
    protected = [p for p in diverse.rglob("*") if p.is_file()]
    protected += [pilot / "review.html", pilot / "results.json", pilot / "rankings.csv", *key_paths.values()]
    protected_before = {str(p.relative_to(project)): digest(p) for p in set(protected)}
    keys = {name: json.loads(path.read_text()) for name, path in key_paths.items()}
    legacy_key = {i["candidate_id"]: i for i in keys["legacy20"]["items"]}
    v3_key = {(i["questionnaire_id"], i["candidate_id"]): i for i in keys["v3-diverse12"]["items"]}
    model_run = json.loads((pilot / "results.json").read_text())
    artworks = {a["asset_id"]: a for a in model_run["artworks"]}
    payloads = {"N01": read_payload(diverse / "forms/N01.html"), "N02": read_payload(diverse / "forms/N02.html")}
    source_manifest, rows, item_paths, checks = [], [], {}, []
    for filename, cohort, reviewer, expected_n in INPUTS:
        source = (args.downloads / filename) if args.downloads else (output / "raw" / filename)
        source_hash = digest(source)
        records = list(csv.DictReader(source.open(encoding="utf-8-sig", newline="")))
        assert len(records) == expected_n, (filename, "row count")
        assert len({r["candidate_id"] for r in records}) == len(records), (filename, "duplicate candidates")
        assert {r["reviewer_id"] for r in records} == {reviewer}
        assert sorted(int(r["presentation_order"]) for r in records) == list(range(1, expected_n + 1))
        if cohort == "v3-diverse12":
            assert len({r["artwork_id"] for r in records}) == 12
        for r in records:
            candidate = r["candidate_id"]
            item = legacy_key[candidate] if cohort == "legacy20" else v3_key[(r["questionnaire_id"], candidate)]
            assert r["experiment_id"] == (LEGACY if cohort == "legacy20" else V3)
            for column in ("artwork_id", "video_id", "frame_sha256"):
                assert r[column] == item[column], (filename, candidate, column)
            assert int(r["presentation_order"]) == item["presentation_order"]
            timestamp = item["canonical_timestamp"] if cohort == "legacy20" else item["timestamp_seconds"]
            assert abs(float(r["timestamp_seconds"]) - timestamp) < 1e-6
            assert r["completed"] == "true"
            if cohort == "v3-diverse12":
                payload = payloads[reviewer]
                for column in ("dataset_id", "review_version", "source_experiment_id", "questionnaire_id"):
                    assert r[column] == payload[column], (filename, candidate, column)
                assert item["assigned_reviewer_id"] == reviewer
                assigned = item["assigned_method"]
                membership = item["actual_top1_method_membership"]
                role = item["role"]
                source_score = item["assigned_method_score"]
            else:
                assert len(item["memberships"]) == 1
                assigned = item["memberships"][0]["method"]
                membership = assigned
                role = "fixed"
                source_score = item["memberships"][0]["cosine_similarity"]
            base = pilot if cohort == "legacy20" else project
            frame_path, art_path = base / item["frame_path"], base / item["normalized_artwork_path"]
            assert digest(frame_path) == r["frame_sha256"]
            assert digest(art_path) == artworks[r["artwork_id"]]["normalized_sha256"]
            item_paths[candidate] = (art_path, frame_path)
            processed = dict(r)
            for dimension in DIMENSIONS:
                assert r[dimension] in {"1", "2", "3", "4", "5", "unsure"}, (filename, candidate, dimension)
                processed[dimension] = int(r[dimension]) if r[dimension].isdigit() else "unsure"
            assert r["relevance"] in {"yes", "no", "unsure", ""}
            processed.update(cohort=cohort, assigned_method=assigned, actual_top1_method_membership=membership,
                             allocation_role=role, artwork_title=item["artwork_title"], source_file=filename,
                             timestamp_seconds=float(r["timestamp_seconds"]), source_method_score=source_score,
                             source_experiment_id=LEGACY, review_version=r.get("review_version", "original-20-pairs"),
                             questionnaire_id=r.get("questionnaire_id", "legacy20"), dataset_id=r.get("dataset_id", ""),
                             presentation_order=int(r["presentation_order"]), completed=True)
            rows.append(processed)
        raw_target = output / "raw" / filename
        if source.resolve() != raw_target.resolve():
            shutil.copyfile(source, raw_target)
        assert digest(raw_target) == source_hash == digest(source)
        source_manifest.append({"file": "raw/" + filename, "original_path": str(source), "sha256": source_hash,
                                "cohort": cohort, "reviewer_id": reviewer, "rating_rows": len(records)})
        checks.append({"file": filename, "rating_rows": len(records), "all_rows_complete": True,
                       "key_identifiers_and_timestamps_match": True, "image_hashes_match": True,
                       "ratings_valid": True, "candidate_ids_unique_within_file": True})
    for name, path in key_paths.items():
        shutil.copyfile(path, output / "provenance" / (name + "-organizer-key.json"))
    cohorts = {c: [r for r in rows if r["cohort"] == c] for c in COHORT_LABELS}
    summaries = {c: summary(rs) for c, rs in cohorts.items()}
    by_form = {reviewer: summary([r for r in rows if r["reviewer_id"] == reviewer]) for _, _, reviewer, _ in INPUTS}
    legacy_by_method = {m: summary([r for r in cohorts["legacy20"] if r["assigned_method"] == m]) for m in ("colour", "clip")}
    paired = defaultdict(dict)
    for r in cohorts["legacy20"]:
        paired[(r["reviewer_id"], r["artwork_id"], r["video_id"])][r["assigned_method"]] = r
    paired_summary = {}
    for dimension in DIMENSIONS:
        deltas = [d["clip"][dimension] - d["colour"][dimension] for d in paired.values()
                  if all(isinstance(d[m][dimension], int) for m in ("clip", "colour"))]
        paired_summary[dimension] = {"paired_judgements": len(deltas), "mean_clip_minus_colour": statistics.mean(deltas),
                                     "median_clip_minus_colour": statistics.median(deltas),
                                     "clip_higher": sum(v > 0 for v in deltas), "equal": deltas.count(0),
                                     "colour_higher": sum(v < 0 for v in deltas)}
    anchors = [r for r in cohorts["v3-diverse12"] if r["allocation_role"] == "anchor"]
    common_across_versions = sorted(set(r["candidate_id"] for r in cohorts["legacy20"]) & set(r["candidate_id"] for r in cohorts["v3-diverse12"]))
    overall_agreement = sum(len({r["overall"] for r in cohorts["legacy20"] if r["candidate_id"] == c}) == 1
                            for c in {r["candidate_id"] for r in cohorts["legacy20"]})
    result = {"analysis_date": "2026-11-18", "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "Descriptive first feedback round; questionnaire versions kept separate.",
              "total_exports": len(source_manifest), "total_rating_rows": len(rows),
              "reviewer_codes_not_verified_distinct_people": sorted(by_form),
              "total_unique_artworks_bookkeeping_only": len({r["artwork_id"] for r in rows}),
              "total_unique_candidate_pairs_bookkeeping_only": len({r["candidate_id"] for r in rows}),
              "cohorts": summaries, "forms": by_form, "legacy_by_method": legacy_by_method,
              "legacy_within_reviewer_paired_differences": paired_summary,
              "legacy_overall_exact_agreement": {"same_overall": overall_agreement, "candidate_pairs": 20},
              "v3_anchor_responses": anchors,
              "v3_dual_method_membership_rows": sum(";" in r["actual_top1_method_membership"] for r in cohorts["v3-diverse12"]),
              "cross_version_common_candidate_ids": common_across_versions,
              "source_manifest": source_manifest,
              "notes": ["Means supplement full distributions and medians for ordinal ratings.",
                        "64 rating rows are repeated observations, not 64 independent people or items.",
                        "No inference, accuracy claim, method winner, style effect or calibrated score threshold is estimated.",
                        "Only the actual CSV exports are analysed. No response is inferred from browser storage."]}
    write_json(output / "summary.json", result)
    write_json(output / "provenance/input-manifest.json", source_manifest)
    with (output / "analysis-rows.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = list(rows[0])
        for r in rows:
            fields += [k for k in r if k not in fields]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    protected_after = {str(p.relative_to(project)): digest(p) for p in set(protected)}
    assert protected_before == protected_after
    write_json(output / "provenance/validation.json", {"files": checks, "rating_rows": len(rows),
               "numeric_ratings": sum(isinstance(r[d], int) for r in rows for d in DIMENSIONS),
               "protected_source_files_unchanged": True, "protected_source_sha256": protected_before,
               "raw_exports_preserved_byte_for_byte": True})
    write_report(output, rows, item_paths, result)
    print(json.dumps({"output": str(output), "exports": len(source_manifest), "rows": len(rows),
                      "cohorts": {c: s["rating_rows"] for c, s in summaries.items()},
                      "source_files_unchanged": True}, indent=2))


def write_report(output, rows, item_paths, result):
    parts = ['''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Frame Echo — First human feedback</title>
<style>:root{color-scheme:light;--ink:#252a25;--muted:#5d675f;--accent:#914a34}*{box-sizing:border-box}body{margin:0;background:#f6f3ec;color:var(--ink);font:16px/1.65 system-ui,-apple-system,sans-serif}main{max-width:1120px;margin:0 auto;padding:44px 26px 70px}header{margin-bottom:32px}h1{font-size:clamp(29px,4vw,44px);line-height:1.15;max-width:850px;margin:12px 0 18px}h2{font-size:25px;line-height:1.3;margin:36px 0 16px}h3{font-size:20px;line-height:1.35}p{max-width:920px}a{color:var(--accent)}.eyebrow{font-size:12px;letter-spacing:1.8px;color:var(--accent)}.note{color:var(--muted);font-size:14px}.callout{background:#e9eee5;padding:16px 22px;border-left:4px solid #667b62}.table-wrap{overflow:auto;margin:14px 0 22px;background:#fffdfa;border:1px solid #d8dcd2;border-radius:5px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;vertical-align:top;padding:11px 13px;border-bottom:1px solid #e3e5de}th{background:#eef0e9;font-weight:650}td.num{font-variant-numeric:tabular-nums}tr:last-child td{border-bottom:0}.cases{display:grid;grid-template-columns:minmax(0,1fr);gap:24px}.case{min-width:0;padding:24px;background:#fffdfa;border:1px solid #d8dcd2;border-radius:5px}.pair{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px}.pair figure{margin:0}.pair img{display:block;width:100%;height:300px;object-fit:contain;background:#ecece5}.pair figcaption{font-size:13px;color:var(--muted);margin-top:6px}.case h3{margin-top:0}.case .table-wrap{margin-bottom:10px}label{display:inline-flex;gap:8px;align-items:center;margin:0 14px 12px 0;font-size:14px}select,input{font:inherit;padding:7px;background:white;border:1px solid #aeb9aa;border-radius:3px;max-width:100%}.details td{white-space:nowrap}.details td.title{white-space:normal;min-width:170px}.bar{display:flex;height:24px;border-radius:3px;overflow:hidden;background:#eee;max-width:330px;margin:7px 0}.bar span{display:flex;align-items:center;justify-content:center;font-size:11px;color:#fff;min-width:0}.s1{background:#8d4b3a}.s2{background:#a56d47}.s3{background:#7a7b52}.s4{background:#526b5b}.s5{background:#335e57}footer{margin-top:40px;font-size:13px;color:var(--muted)}.caption{font-size:14px;color:var(--muted)}blockquote{margin:15px 0;padding-left:18px;border-left:3px solid #d0c9b9}.links{display:flex;flex-wrap:wrap;gap:12px 22px}@media(max-width:650px){main{padding:25px 16px}.case{padding:16px}.pair{grid-template-columns:1fr}.pair img{height:260px}th,td{padding:8px}.links{display:block}.links a{display:block;margin:8px 0}}@media print{body{background:white}main{max-width:none;padding:0}.case{break-inside:avoid}.filters{display:none}.table-wrap{overflow:visible}details{display:none}}</style></head><body><main>
<header><p class="eyebrow">FRAME ECHO / HUMAN FEEDBACK / 18 NOVEMBER 2026</p><h1>Colour connections often received higher ratings than content or overall similarity</h1><p>Four completed questionnaire exports contain 64 pair evaluations. The original and revised forms are reported separately because their artwork selections, workloads and reviewer codes differ.</p><p class="note">Four anonymous reviewer codes are present. The files alone do not verify that all codes belong to distinct people. This is an exploratory description of the returned forms.</p></header>
<nav class="links"><a href="#summary">Ratings by version</a><a href="#methods">Method comparison</a><a href="#cases">Image cases</a><a href="#records">All 64 records</a><a href="#next">Next steps</a></nav>
<section id="summary"><h2>Ratings by questionnaire version</h2>''']
    parts.append(table(["Version", "Returned forms", "Pair evaluations", "Distinct pairs", "Artworks"],
                 [[COHORT_LABELS[c], ", ".join(s["reviewer_codes"]), s["rating_rows"], s["unique_candidate_pairs"], s["unique_artworks"]]
                  for c, s in result["cohorts"].items()]))
    parts.append('<p class="caption">A pair evaluation is one reviewer code’s response to one artwork–frame pair. Repeated ratings of the same pair are retained. Counts are not independent participant sample sizes.</p>')
    for cohort, s in result["cohorts"].items():
        parts.append(f'<h3>{esc(COHORT_LABELS[cohort])}</h3>')
        parts.append(table(["Criterion", "Numeric ratings", "Mean / 5", "Median / 5", "Counts for ratings 1 / 2 / 3 / 4 / 5"],
                      [[d.title(), s["ratings"][d]["numeric_n"], f'{s["ratings"][d]["mean"]:.3f}', s["ratings"][d]["median"],
                        " / ".join(str(n) for n in s["ratings"][d]["distribution"].values())] for d in DIMENSIONS]))
        dist = s["ratings"]["overall"]["distribution"]
        parts.append('<p class="caption">Overall rating distribution. Rating 1 means very dissimilar and 5 very similar.</p><div class="bar" aria-label="Overall rating counts">' +
                     "".join(f'<span class="s{k}" style="width:{100*v/s["rating_rows"]:.4f}%" title="Rating {k}: {v}">{v if v else ""}</span>' for k, v in dist.items()) + '</div>')
        parts.append(f'<p>Optional connection question: <strong>yes {s["relevance"].get("yes",0)}</strong>, no {s["relevance"].get("no",0)}, not sure {s["relevance"].get("unsure",0)}. '
                     f'Colour was rated 4–5 while content was rated 1–2 in <strong>{s["colour_ge4_content_le2"]} of {s["rating_rows"]}</strong> evaluations.</p>')
    parts.append('<p class="note">All 256 criterion responses are numeric. No missing or “not sure” criterion rating is replaced by zero. Connection-question uncertainty is retained separately. Means are descriptive summaries of ordinal ratings and should be read with their medians and distributions. The colour/content bands above are post hoc descriptive counts, not a validated success criterion.</p>')
    parts.append('<p class="callout">The revised forms have higher average overall ratings in this small return set. Their different images and reviewer codes prevent interpreting this difference as an improvement in the retrieval system. The model and saved rankings were unchanged.</p></section>')
    parts.append('<section id="methods"><h2>What can be compared between methods?</h2><h3>Original forms: matched artwork and video conditions</h3><p>P01 and P02 each rated both methods for the same five artworks and two videos. This yields 20 within-reviewer, artwork–video comparisons. The comparison is descriptive and contains repeated observations from only two reviewer codes.</p>')
    parts.append(table(["Criterion", "Colour mean / 5", "CLIP mean / 5", "Mean CLIP − colour", "CLIP higher / tie / colour higher"],
                 [[d.title(), f'{result["legacy_by_method"]["colour"]["ratings"][d]["mean"]:.3f}',
                   f'{result["legacy_by_method"]["clip"]["ratings"][d]["mean"]:.3f}',
                   f'{result["legacy_within_reviewer_paired_differences"][d]["mean_clip_minus_colour"]:+.2f}',
                   " / ".join(str(result["legacy_within_reviewer_paired_differences"][d][k]) for k in ("clip_higher", "equal", "colour_higher"))] for d in DIMENSIONS]))
    parts.append('<p>Overall ratings averaged 1.75 for the colour method and 1.85 for CLIP. Twelve of the 20 paired judgments were ties. This feedback does not establish a method winner.</p><h3>Diverse forms: four shared artwork–video anchors</h3><p>The anchors below keep the artwork and video fixed, but the reviewer and usually the retrieved frame change. They are comparisons across reviewer codes. Rotating artworks differ between N01 and N02, so their method-wide averages are not used as a controlled comparison.</p>')
    parts.append(table(["Art / video", "Reviewer", "Assigned method", "Actual Top 1 membership", "Frame (seconds)", "Overall / 5", "Connection"],
                  [[f'{r["artwork_id"]} / {r["video_id"]}', r["reviewer_id"], r["assigned_method"], r["actual_top1_method_membership"], f'{r["timestamp_seconds"]:.0f}', r["overall"], r["relevance"]]
                   for r in sorted(result["v3_anchor_responses"], key=lambda r:(r["artwork_id"], r["reviewer_id"]))]))
    parts.append('<p class="note">A80 at 10 seconds is the same image under both methods. A91 at 7 seconds in N01 also has dual Top 1 membership. Each actual judgment is counted once, with assigned method and actual membership retained separately. There is only one exact pair shared across questionnaire versions: A28 / V05 / 74 seconds. Its overall ratings are P01 = 1, P02 = 2 and N01 = 3.</p></section>')
    cases = [
        ("C2d33635c68b7", "A relatively higher-rated result, judged by one reviewer", "The ruin and trees in the artwork are paired with an indoor wall, doorway and potted plant. Vertical structures and vegetation offer a possible broad connection. The setting and depicted objects still differ. N01’s high content rating reflects this person’s response; it is not a confirmed consensus.", "Highest observed overall rating in these four returns; selected after examining ratings."),
        ("Ce65160f1effc", "Similar colours, weak content correspondence", "Green and brown tones in the still life have some relation to the concert lighting and haze. The fruit and vessels differ from the stage and audience. Both original-form reviewers rated content 1 and overall 2, despite colour ratings of 5 and 4. The connection question received yes and not sure, showing that this optional response is distinct from overall similarity.", "Original-form case with high colour ratings and consistently low content and overall ratings."),
        ("Cc34b9423f192", "The same image pair received different judgments", "A fishing scene with people and nets is paired with indoor furniture and dogs. Pale and warm colours and broad divisions may offer limited visual relations. N01 rated overall 3 and N02 rated it 1. Both methods returned exactly this frame, so the rating difference cannot be attributed to a method change.", "Shared anchor with identical artwork and frame across both revised forms."),
        ("C6cca251a0de3", "Reviewers interpreted content differently", "The artwork contains a group of figures and the frame contains several dogs. P01 rated content 4 and P02 rated it 1, while both rated overall 2. A broad group relationship is one possible interpretation, but the ratings alone do not establish why the reviewers differed. P01’s written comment is reproduced below.", "Only case with a written participant comment; content ratings differ substantially."),
        ("C34c147aaed9a", "A first-ranked candidate can still be weak", "The fruit and vessels in the still life are paired with an indoor counter and plant. Both reviewers rated composition and content 1 and answered no to the connection question. This illustrates a weak result within the available video, even though it was CLIP’s highest-ranked sampled candidate.", "Original-form case with low composition/content scores from both reviewers and two no responses."),
    ]
    parts.append('<section id="cases"><h2>Five cases to discuss</h2><p>These examples were selected after reviewing the returned scores to illustrate different outcomes. They are not representative success estimates. Visual explanations are researcher observations. Only quoted comments are participant explanations.</p><div class="cases">')
    for candidate, title, description, rule in cases:
        selected = [r for r in rows if r["candidate_id"] == candidate]
        r = selected[0]
        art_path, frame_path = item_paths[candidate]
        parts.append(f'<article class="case"><h3>{esc(title)}</h3><p><strong>{esc(r["artwork_id"])} — {esc(r["artwork_title"])}</strong><br>{esc(r["video_id"])} at {r["timestamp_seconds"]:.0f} seconds · Top 1 membership: {esc(r["actual_top1_method_membership"])} · {esc(candidate)}</p>')
        parts.append(f'<div class="pair"><figure><img src="{image_uri(art_path)}" alt="Reference artwork {esc(r["artwork_id"])}"><figcaption>Reference artwork. Full normalized image shown.</figcaption></figure><figure><img src="{image_uri(frame_path)}" alt="Retrieved video frame"><figcaption>Retrieved source frame. Full image shown.</figcaption></figure></div>')
        parts.append(table(["Reviewer", "Colour", "Composition", "Content", "Overall", "Connection"], [[s["reviewer_id"], *[s[d] for d in DIMENSIONS], s["relevance"]] for s in selected]))
        parts.append(f'<p>{esc(description)}</p><p class="note">Case selection: {esc(rule)}</p>')
        for s in selected:
            if s["comment"]:
                parts.append(f'<blockquote>{esc(s["comment"])}<br><span class="note">Participant comment, {esc(s["reviewer_id"])}</span></blockquote>')
        parts.append('</article>')
    parts.append('</div></section><section id="records"><h2>All 64 returned pair evaluations</h2><p class="caption">Use the filters to inspect individual responses. Source method scores are omitted from this view because their scales differ and they are not confidence probabilities. The analysis CSV retains them as recorded.</p><div class="filters"><label>Version <select id="version"><option value="">All versions</option><option value="legacy20">Original 20-pair</option><option value="v3-diverse12">Diverse 12-artwork</option></select></label><label>Reviewer <select id="reviewer"><option value="">All codes</option><option>P01</option><option>P02</option><option>N01</option><option>N02</option></select></label><label>Search <input id="search" type="search" placeholder="Artwork, video or candidate ID"></label><p id="row-count" class="note" aria-live="polite">64 evaluations shown.</p></div><div class="table-wrap"><table class="details"><thead><tr>' + ''.join(f'<th>{esc(h)}</th>' for h in ("Version", "Reviewer", "Artwork", "Video", "Frame (s)", "Assigned method", "Actual Top 1", "Colour", "Composition", "Content", "Overall", "Connection")) + '</tr></thead><tbody>')
    for r in rows:
        search = " ".join(str(r[k]) for k in ("candidate_id", "artwork_id", "artwork_title", "video_id"))
        parts.append(f'<tr data-cohort="{esc(r["cohort"])}" data-reviewer="{esc(r["reviewer_id"])}" data-search="{esc(search.lower())}">' + ''.join(f'<td class="{"title" if i == 2 else "num"}">{esc(v)}</td>' for i, v in enumerate((r["cohort"], r["reviewer_id"], r["artwork_id"] + " — " + r["artwork_title"], r["video_id"], f'{r["timestamp_seconds"]:.0f}', r["assigned_method"], r["actual_top1_method_membership"], *[r[d] for d in DIMENSIONS], r["relevance"]))) + '</tr>')
    parts.append('''</tbody></table></div></section><section id="next"><h2>What this feedback supports next</h2><ol><li>Keep completed questionnaires and their version information intact. Record whether reviewer codes correspond to different people before reporting a participant count.</li><li>Use high-colour/low-content cases to explain the limits of colour matching. Check query, frame and rating together rather than relying on rank or cosine score alone.</li><li>Broaden artwork styles and video subjects in a separate supplemental round. Hold some works out of development and keep subject matter comparable across visual styles where possible. Current returns do not isolate a style effect.</li><li>If useful, ask a small number of reviewers to explain what they mean by content and overall connection. Collect explanations without changing their already exported ratings.</li><li>Evaluate rejection of unsuitable matches separately. These ratings alone do not establish a safe score cutoff. A video can lack an appropriate scene.</li></ol><h3>Suggested wording for the thesis</h3><blockquote>Four completed questionnaire exports provided initial feedback on the retrieved image pairs. The original and revised forms were analysed separately. In both groups, colour received higher average ratings than content and overall connection. Selected examples showed that similar colours could coexist with weak subject correspondence, and that different reviewers could judge the same pair differently. These observations identify areas for further evaluation, including more varied artworks and footage. They do not establish an overall accuracy rate or a method advantage.</blockquote></section>''')
    parts.append('<section><h2>Data and provenance</h2><p>All 64 records passed identifier, presentation-order, timestamp, rating-range and image-hash checks. The four raw CSV files were copied byte for byte. Questionnaire pages, allocations and retrieval outputs were not changed.</p><nav class="links"><a href="analysis-rows.csv">Analysis rows (CSV)</a><a href="summary.json">Descriptive summaries (JSON)</a><a href="provenance/input-manifest.json">Input files and SHA-256 hashes</a><a href="provenance/validation.json">Validation record</a></nav>')
    parts.append('<ul>' + ''.join(f'<li><a href="{esc(s["file"])}">{esc(s["reviewer_id"])} raw export ({s["rating_rows"]} pairs)</a></li>' for s in result["source_manifest"]) + '</ul></section><footer>Offline report generated from four actual CSV exports on 18 November 2026. All questionnaire versions remain separate. This report contains no generated participant ratings.</footer></main><script>const filters=["version","reviewer","search"].map(id=>document.getElementById(id));function filterRows(){const [version,reviewer,search]=filters.map(e=>e.value.trim().toLowerCase());let shown=0;document.querySelectorAll(".details tbody tr").forEach(row=>{const visible=(!version||row.dataset.cohort===version)&&(!reviewer||row.dataset.reviewer.toLowerCase()===reviewer)&&(!search||row.dataset.search.includes(search));row.hidden=!visible;if(visible)shown++});document.getElementById("row-count").textContent=shown+" evaluations shown."}filters.forEach(e=>e.addEventListener("input",filterRows));</script></body></html>')
    (output / "index.html").write_text("\n".join(parts), encoding="utf-8")


if __name__ == "__main__":
    main()
