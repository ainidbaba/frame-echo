"""Assigned, offline English questionnaires and their local launcher.

Reuses the existing validated rating instrument without changing historical
pages or generators. The participant payload contains no retrieval conditions;
method assignment belongs in the researcher's separate key.
"""
from __future__ import annotations

import html
import json
from pathlib import Path, PurePosixPath
import re

from scripts.english_review_page import write_english_review_page

REVIEW_VERSION = "v3-diverse-12"
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
_DATA = re.compile(r'(<script id="review-data" type="application/json">)(.*?)(</script>)', re.S)


def _identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{label} must be an anonymous ASCII identifier of 1–64 characters")
    return value


def _replace_once(page: str, old: str, new: str) -> str:
    if page.count(old) != 1:
        raise RuntimeError(f"The underlying review template changed; expected one occurrence of {old[:90]!r}")
    return page.replace(old, new, 1)


def _json_html(value) -> str:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def write_assigned_review_page(
    output_path: Path, items: list[dict], experiment_id: str, seed: int,
    reviewer_id: str, questionnaire_id: str, source_experiment_id: str,
) -> None:
    """Write a 12-artwork form locked to its assigned anonymous reviewer code.

    The original four visual ratings remain blank. CSV keeps the original 16
    columns and adds questionnaire/version/dataset/source-experiment identifiers.
    The supplied item order is retained and source method/rank/score keys are
    dropped by the underlying generator's allowlist.
    """
    reviewer_id = _identifier(reviewer_id, "reviewer_id")
    questionnaire_id = _identifier(questionnaire_id, "questionnaire_id")
    if not isinstance(source_experiment_id, str) or not source_experiment_id.strip():
        raise ValueError("source_experiment_id must be a non-empty string")
    if experiment_id == source_experiment_id:
        raise ValueError("Use a new experiment_id for the revised questionnaire design")
    if not isinstance(items, list) or len(items) != 12:
        raise ValueError("Each questionnaire must contain exactly 12 image pairs")
    if len({x.get("artwork_id") for x in items if isinstance(x, dict)}) != 12:
        raise ValueError("Each questionnaire must contain 12 distinct artworks")

    destination = Path(output_path)
    write_english_review_page(destination, items, experiment_id, seed)
    page = destination.read_text(encoding="utf-8")
    match = _DATA.search(page)
    if not match:
        raise RuntimeError("Generated review page has no documented data block")
    payload = json.loads(match.group(2))
    payload.update(assigned_reviewer_id=reviewer_id, questionnaire_id=questionnaire_id,
                   review_version=REVIEW_VERSION, source_experiment_id=source_experiment_id)
    page = page[:match.start(2)] + _json_html(payload) + page[match.end(2):]
    page = _replace_once(page, "<title>Visual similarity feedback · Frame Echo</title>",
                         f"<title>Frame Echo — {html.escape(reviewer_id)} — 12 artworks</title>")
    page = _replace_once(page, "<h1>Visual similarity feedback</h1>",
                         "<h1>Visual similarity feedback — 12 different artworks</h1>")
    page = _replace_once(page, '<p class="intro">Compare the artwork and video frame,',
                         '<p class="intro">Each of the 12 pairs uses a different artwork. Compare the artwork and video frame,')
    page = _replace_once(page, 'placeholder="P01" maxlength="64"',
                         f'value="{html.escape(reviewer_id)}" placeholder="{html.escape(reviewer_id)}" readonly maxlength="64"')
    page = _replace_once(page, "Load / switch ID", "Start / resume")
    page = _replace_once(page,
        "Enter an anonymous ID such as P01 to begin. Switching IDs loads that reviewer's own records.",
        "This is the assigned ID for this questionnaire. Select Start / resume to begin or load its saved responses.")
    page = _replace_once(page,
        "After you enter an ID, this page will try to save your progress in this browser. You can export a CSV at any time.",
        "After you start, this page will try to save your progress in this browser. Export a CSV before finishing.")
    page = _replace_once(page,
        "Browser storage is unavailable. Responses are held in this page's memory only. You can still switch reviewer IDs, but export a CSV before closing the page.",
        "Browser storage is unavailable. Responses are held in this page's memory only. Export a CSV before closing the page.")
    page = _replace_once(page, '<section class="panel" aria-label="Reviewer setup">',
        '<p class="status"><a href="../index.html">Choose another participant</a> · Export a CSV before leaving this questionnaire.</p>\n  <section class="panel" aria-label="Reviewer setup">')
    page = _replace_once(page, '    const nextId = reviewerInput.value.trim();',
        '    const nextId = reviewerInput.value.trim();\n'
        '    if (nextId !== data.assigned_reviewer_id) {\n'
        '      error("This questionnaire is assigned to " + data.assigned_reviewer_id + ". Return to the start page to choose another participant.");\n'
        '      reviewerInput.value = data.assigned_reviewer_id;\n'
        '      return false;\n'
        '    }')
    original_columns = '["experiment_id","reviewer_id","candidate_id","artwork_id","video_id","frame_sha256","presentation_order","timestamp_seconds","colour","composition","content","overall","relevance","quality_flags","comment","completed"]'
    new_columns = original_columns[:-1] + ',"questionnaire_id","review_version","dataset_id","source_experiment_id"]'
    page = _replace_once(page, original_columns, new_columns)
    page = _replace_once(page,
        'comment:answer.comment, completed:complete(answer) ? "true" : "false"};',
        'comment:answer.comment, completed:complete(answer) ? "true" : "false",\n'
        '        questionnaire_id:data.questionnaire_id, review_version:data.review_version,\n'
        '        dataset_id:data.dataset_id, source_experiment_id:data.source_experiment_id};')
    page = _replace_once(page,
        'link.download = `frame-echo_${safeFilename(data.experiment_id)}_${safeFilename(state.reviewerId)}.csv`;',
        'link.download = `frame-echo_${safeFilename(data.experiment_id)}_${safeFilename(data.questionnaire_id)}_${safeFilename(state.reviewerId)}.csv`;')
    destination.write_text(page, encoding="utf-8")


def write_launcher(output_path: Path, forms: list[dict]) -> None:
    """Write an offline questionnaire chooser with no condition or image data."""
    if not isinstance(forms, list) or not forms:
        raise ValueError("forms must be a non-empty list")
    clean = []
    for form in forms:
        if not isinstance(form, dict):
            raise ValueError("Each form must be a dictionary")
        reviewer = _identifier(form.get("reviewer_id"), "reviewer_id")
        questionnaire = _identifier(form.get("questionnaire_id"), "questionnaire_id")
        relative = form.get("relative_path")
        if (not isinstance(relative, str) or not re.fullmatch(r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.html", relative)
                or ".." in PurePosixPath(relative).parts or PurePosixPath(relative).is_absolute()):
            raise ValueError("relative_path must be a local relative HTML path without parent traversal")
        clean.append(dict(reviewer_id=reviewer, questionnaire_id=questionnaire, relative_path=relative))
    for field in ["reviewer_id", "questionnaire_id", "relative_path"]:
        if len({f[field] for f in clean}) != len(clean):
            raise ValueError(f"Each {field} must be unique")
    initial = clean[0]
    options = "".join(f'<option value="{html.escape(f["reviewer_id"], quote=True)}">{html.escape(f["reviewer_id"])} — {html.escape(f["questionnaire_id"])}</option>' for f in clean)
    page = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="referrer" content="no-referrer"><title>Frame Echo — Choose a questionnaire</title>
<style>:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#f5f2e9;color:#252a25;font:16px/1.65 system-ui,-apple-system,sans-serif}main{max-width:820px;margin:7vh auto;padding:24px}h1{font-size:clamp(28px,5vw,40px);line-height:1.2;margin:10px 0 18px}.eyebrow{font-size:12px;letter-spacing:2px;color:#a44b32}p{margin:12px 0}.card{margin:26px 0;padding:26px;background:#fffdf8;border:1px solid #d9ddcf;border-radius:5px}label{display:block;font-weight:650;margin-bottom:8px}select,a.button{font:inherit;border-radius:3px;padding:10px 14px}select{background:white;border:1px solid #bac2b3;width:100%;max-width:360px}.button{display:inline-block;background:#a44b32;color:white;text-decoration:none;margin-top:18px}.muted{color:#65705f;font-size:14px}a:focus-visible,select:focus-visible{outline:3px solid #bc7258;outline-offset:3px}ol{padding-left:22px}li{margin:8px 0}@media(max-width:500px){main{margin:20px auto;padding:18px}.card{padding:20px}.button{width:100%;text-align:center}}</style></head>
<body><main><p class="eyebrow">FRAME ECHO / VISUAL FEEDBACK</p><h1>Choose a questionnaire</h1>
<p>Assign one unused ID to each new participant. Each questionnaire contains 12 different artworks. Different IDs open different artwork combinations.</p>
<div class="card"><label for="participant">Participant ID and questionnaire</label><select id="participant">__OPTIONS__</select><br><a class="button" id="open-questionnaire" href="__INITIAL_PATH__">Open questionnaire</a><p class="muted" id="selected-form">__INITIAL_LABEL__</p></div>
<ol><li>Choose the participant's assigned ID and open the questionnaire.</li><li>Select Start / resume. A new participant starts with blank responses.</li><li>Rate all 12 pairs and export a CSV before returning here.</li></ol>
<p class="muted">__COUNT__ questionnaires are prepared for use; this is not a record of completed participants. Use the same ID to resume a person's existing questionnaire. Keep each ID assigned to one person.</p>
<p class="muted">Earlier fixed-questionnaire responses remain in their original pages. This chooser opens the new artwork-combination questionnaires.</p>
<script id="questionnaire-list" type="application/json">__FORMS__</script><script>"use strict";(()=>{const forms=JSON.parse(document.getElementById("questionnaire-list").textContent);const select=document.getElementById("participant"),link=document.getElementById("open-questionnaire"),label=document.getElementById("selected-form");function update(){const form=forms.find(f=>f.reviewer_id===select.value);if(!form)return;link.href=form.relative_path;label.textContent=form.reviewer_id+" — "+form.questionnaire_id;}select.addEventListener("change",update);update();})();</script>
</main></body></html>'''
    page = (page.replace("__OPTIONS__", options)
            .replace("__INITIAL_PATH__", html.escape(initial["relative_path"], quote=True))
            .replace("__INITIAL_LABEL__", html.escape(initial["reviewer_id"] + " — " + initial["questionnaire_id"]))
            .replace("__COUNT__", str(len(clean)))
            .replace("__FORMS__", _json_html(clean)))
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(page, encoding="utf-8")
