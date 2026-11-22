"""Independent English fixed-set form for the artwork supplement.

Reuses the existing offline rating instrument without modifying its generators,
questionnaires, answers or local-storage namespaces. Only this new form receives
the supplement's metadata. Retrieval labels stay in the organizer's key.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from scripts.english_review_page import write_english_review_page


REVIEW_VERSION = "style-supplement-12-v1"
EXPORT_COLUMNS = [
    "experiment_id", "reviewer_id", "candidate_id", "artwork_id", "video_id",
    "frame_sha256", "presentation_order", "timestamp_seconds", "colour",
    "composition", "content", "overall", "relevance", "quality_flags", "comment",
    "completed", "questionnaire_id", "review_version", "dataset_id",
    "source_experiment_id",
]
_DATA = re.compile(
    r'(<script id="review-data" type="application/json">)(.*?)(</script>)', re.S
)
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ITEM_KEYS = {
    "candidate_id", "artwork_id", "artwork_title", "artist", "video_id",
    "frame_sha256", "presentation_order", "reference_image", "frame_image",
    "canonical_timestamp",
}


def _replace_once(page: str, old: str, new: str) -> str:
    if page.count(old) != 1:
        raise RuntimeError(
            "The English rating template changed. Review this adapter before use: "
            + old[:90]
        )
    return page.replace(old, new, 1)


def _json_html(value: dict) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026").replace("<", "\\u003c")
        .replace(">", "\\u003e").replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def write_supplement_review_page(
    output_path: Path,
    items: list[dict],
    experiment_id: str,
    seed: int,
    questionnaire_id: str,
    source_experiment_id: str,
    selection_plan_sha256: str,
) -> dict:
    """Write one fixed 12-work questionnaire with free anonymous reviewer IDs.

    Returns the page's dataset/version identifiers for the organizer manifest.
    Every reviewer sees the same supplied items and order. All responses start
    blank, while progress is separated by experiment, dataset and reviewer ID.
    The 20-column CSV contains rating responses plus questionnaire provenance.
    No method, source rank, cosine score or visual-quality prediction is added
    to the participant item payload.
    """
    if not isinstance(items, list) or len(items) != 12:
        raise ValueError("The supplemental questionnaire needs exactly 12 pairs")
    if any(not isinstance(item, dict) for item in items):
        raise TypeError("Every supplemental pair must be a dictionary")
    if {item.get("artwork_id") for item in items} != {
        f"S{i:02d}" for i in range(1, 13)
    }:
        raise ValueError("Use each of the twelve new S01–S12 artworks exactly once")
    if not isinstance(questionnaire_id, str) or not _ID.fullmatch(questionnaire_id):
        raise ValueError("questionnaire_id must be a short ASCII identifier")
    if not isinstance(source_experiment_id, str) or not source_experiment_id.strip():
        raise ValueError("source_experiment_id must be non-empty")
    if experiment_id == source_experiment_id:
        raise ValueError("The questionnaire needs its own experiment identity")
    if not isinstance(selection_plan_sha256, str) or not _HASH.fullmatch(selection_plan_sha256):
        raise ValueError("selection_plan_sha256 must be a lowercase SHA-256 hash")

    destination = Path(output_path)
    if destination.suffix.lower() != ".html":
        raise ValueError("The questionnaire destination must be an HTML file")
    write_english_review_page(destination, items, experiment_id, seed)
    page = destination.read_text(encoding="utf-8")
    match = _DATA.search(page)
    if not match:
        raise RuntimeError("Generated English page has no candidate-data block")
    payload = json.loads(match.group(2))
    if any(set(item) != _ITEM_KEYS for item in payload["items"]):
        raise RuntimeError("Unexpected fields would expose retrieval conditions")
    if len(payload["items"]) != 12:
        raise RuntimeError("The generated page changed the fixed pair count")
    payload.update(
        questionnaire_id=questionnaire_id,
        review_version=REVIEW_VERSION,
        source_experiment_id=source_experiment_id,
        selection_plan_sha256=selection_plan_sha256,
    )
    page = page[:match.start(2)] + _json_html(payload) + page[match.end(2):]
    replacements = [
        (
            "<title>Visual similarity feedback · Frame Echo</title>",
            "<title>Frame Echo — Supplemental visual similarity feedback</title>",
        ),
        (
            "<h1>Visual similarity feedback</h1>",
            "<h1>Visual similarity feedback — 12 artworks</h1>",
        ),
        (
            '<p class="intro">Compare the artwork and video frame,',
            '<p class="intro">Each of these 12 pairs uses a different artwork. '
            'Compare the artwork and video frame,',
        ),
        ('placeholder="P01" maxlength="64"', 'placeholder="R01" maxlength="64"'),
        ("Load / switch ID", "Start / resume"),
        (
            "Enter an anonymous ID such as P01 to begin. Switching IDs loads that reviewer's own records.",
            "Enter your anonymous ID to begin, for example R01. Every reviewer sees the same 12 pairs. "
            "Export a CSV before changing to another reviewer's ID.",
        ),
        (
            "After you enter an ID, this page will try to save your progress in this browser. You can export a CSV at any time.",
            "This page saves responses separately for each reviewer ID when browser storage is available. "
            "Export a CSV before changing IDs or finishing.",
        ),
        (
            "Enter a reviewer ID of 1–64 characters, such as P01. Do not use a name or contact details.",
            "Enter a reviewer ID of 1–64 characters, such as R01. Do not use a name or contact details.",
        ),
    ]
    for old, new in replacements:
        page = _replace_once(page, old, new)
    page = _replace_once(
        page,
        "</style>",
        "@media(max-width:430px) { .rating-grid { grid-template-columns:1fr; } "
        ".rating-grid small { min-height:0; } }\n</style>",
    )
    old_columns = (
        '["experiment_id","reviewer_id","candidate_id","artwork_id",'
        '"video_id","frame_sha256","presentation_order","timestamp_seconds",'
        '"colour","composition","content","overall","relevance",'
        '"quality_flags","comment","completed"]'
    )
    new_columns = json.dumps(EXPORT_COLUMNS, separators=(",", ":"))
    page = _replace_once(page, old_columns, new_columns)
    page = _replace_once(
        page,
        'comment:answer.comment, completed:complete(answer) ? "true" : "false"};',
        'comment:answer.comment, completed:complete(answer) ? "true" : "false",\n'
        '        questionnaire_id:data.questionnaire_id, review_version:data.review_version,\n'
        '        dataset_id:data.dataset_id, source_experiment_id:data.source_experiment_id};',
    )
    page = _replace_once(
        page,
        'link.download = `frame-echo_${safeFilename(data.experiment_id)}_${safeFilename(state.reviewerId)}.csv`;',
        'link.download = `frame-echo_${safeFilename(data.experiment_id)}_${safeFilename(data.questionnaire_id)}_${safeFilename(state.reviewerId)}.csv`;',
    )
    # Check translated UI separately from source artwork names in the data block.
    if re.search(r"[\u3400-\u9fff]", _DATA.sub("", page)):
        raise RuntimeError("A participant-facing UI string is not in English")
    if 'value="R01"' in page or 'assigned_reviewer_id' in payload:
        raise RuntimeError("Reviewer IDs must begin blank and remain editable")
    if 'function keyFor(reviewerId) { return "frame-echo-feedback:" + JSON.stringify([data.experiment_id, data.dataset_id, reviewerId]); }' not in page:
        raise RuntimeError("The expected experiment/dataset/reviewer storage isolation changed")
    destination.write_text(page, encoding="utf-8")
    return {
        "experiment_id": experiment_id,
        "questionnaire_id": questionnaire_id,
        "review_version": REVIEW_VERSION,
        "dataset_id": payload["dataset_id"],
        "source_experiment_id": source_experiment_id,
        "selection_plan_sha256": selection_plan_sha256,
        "pairs": 12,
        "different_artworks": 12,
        "export_columns": EXPORT_COLUMNS,
    }
