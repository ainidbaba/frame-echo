"""Generate a self-contained, condition-blinded offline visual feedback page.

Input items are already ordered by the experiment driver. Only the documented
fields are embedded: accidental ranking or method-membership fields are dropped.
Answers start blank and are never inferred from retrieval scores.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
from pathlib import Path


_ITEM_KEYS = (
    "candidate_id", "artwork_id", "artwork_title", "artist", "video_id",
    "frame_sha256", "presentation_order", "reference_image", "frame_image",
    "canonical_timestamp",
)


def _normalise_items(items: list[dict]) -> list[dict]:
    if not isinstance(items, list):
        raise TypeError("items must be a list of dictionaries")
    clean, candidate_ids, orders = [], set(), set()
    for raw in items:
        if not isinstance(raw, dict) or any(key not in raw for key in _ITEM_KEYS):
            raise ValueError("Each item must contain all documented candidate fields")
        item = {key: raw[key] for key in _ITEM_KEYS}
        for key in ("candidate_id", "artwork_id", "artwork_title", "artist", "video_id", "frame_sha256"):
            if not isinstance(item[key], str) or not item[key].strip():
                raise ValueError(f"{key} must be a non-empty string")
        if item["candidate_id"] in candidate_ids:
            raise ValueError("candidate_id must be unique")
        candidate_ids.add(item["candidate_id"])
        order = item["presentation_order"]
        if isinstance(order, bool) or not isinstance(order, int) or order < 1 or order in orders:
            raise ValueError("presentation_order must be a unique positive integer")
        orders.add(order)
        stamp = item["canonical_timestamp"]
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or stamp < 0:
            raise ValueError("canonical_timestamp must be finite and non-negative")
        for key in ("reference_image", "frame_image"):
            uri = item[key]
            prefix = "data:image/jpeg;base64,"
            if not isinstance(uri, str) or not uri.startswith(prefix):
                raise ValueError("Images must be embedded JPEG data URLs")
            try:
                if not base64.b64decode(uri[len(prefix):], validate=True):
                    raise ValueError("Empty image")
            except Exception as error:
                raise ValueError("Invalid embedded image data") from error
        clean.append(item)
    return clean


def write_review_page(output_path: Path, items: list[dict], experiment_id: str, seed: int) -> None:
    """Write an offline feedback page without exposing retrieval conditions.

    The supplied order is retained. Timestamp and frame identity are available to
    the CSV export, but never added to the visible interface. A page-specific
    fingerprint prevents records for a different candidate set being reused.
    """
    if not isinstance(experiment_id, str) or not experiment_id.strip():
        raise ValueError("experiment_id must be a non-empty string")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    candidates = _normalise_items(items)
    identity = json.dumps(candidates, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    dataset_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    payload = {"experiment_id": experiment_id, "seed": seed, "dataset_id": dataset_id, "items": candidates}
    embedded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    embedded = embedded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    embedded = embedded.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(_TEMPLATE.replace("__FRAME_ECHO_REVIEW_DATA__", embedded), encoding="utf-8")


_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <title>综合视觉相似度反馈 · Frame Echo</title>
  <style>
    :root { color-scheme:light; --paper:#f5f2e9; --panel:#fffdf8; --ink:#252a25; --muted:#65705f; --line:#d9ddcf; --accent:#a44b32; }
    * { box-sizing:border-box; } body { margin:0; background:var(--paper); color:var(--ink); font:15px/1.65 system-ui,-apple-system,sans-serif; }
    main { max-width:1160px; margin:auto; padding:32px 24px 64px; } h1 { margin:0 0 8px; font-size:clamp(25px,4vw,36px); letter-spacing:-.8px; line-height:1.25; }
    h2 { font-size:20px; margin:0; line-height:1.45; } p { margin:8px 0; } .eyebrow { font-size:11px; letter-spacing:2px; color:var(--accent); margin-bottom:8px; }
    .intro { max-width:870px; color:var(--muted); } .panel { background:var(--panel); border:1px solid var(--line); border-radius:5px; padding:20px; margin-top:20px; }
    .reviewer { display:flex; align-items:end; flex-wrap:wrap; gap:12px; } label { display:block; font-weight:600; } .reviewer label { font-size:13px; }
    input,select,textarea,button { font:inherit; color:inherit; } input,select,textarea { background:white; border:1px solid #bac2b3; border-radius:3px; padding:9px 10px; }
    input { width:180px; } textarea { width:100%; min-height:86px; resize:vertical; } button { border:1px solid #aab39f; border-radius:3px; background:#faf9f2; padding:9px 15px; cursor:pointer; }
    button.primary { background:var(--accent); color:white; border-color:var(--accent); } button:disabled { cursor:not-allowed; opacity:.45; }
    button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,h2:focus-visible { outline:3px solid #bc7258; outline-offset:3px; }
    .status { font-size:13px; color:var(--muted); margin:10px 0 0; } .notice { padding:10px 12px; background:#edf0e6; border-left:3px solid #87936f; }
    .error { color:#913b2d; background:#fae9df; border-left:3px solid #b2573d; padding:10px 12px; } [hidden] { display:none!important; }
    .progress-line { display:flex; align-items:center; flex-wrap:wrap; justify-content:space-between; gap:10px; margin-bottom:12px; font-size:13px; }
    progress { display:block; width:100%; height:8px; accent-color:var(--accent); margin:0 0 20px; } .pair-title { margin-bottom:15px; }
    .pair-meta { color:var(--muted); font-size:12px; } .pair-grid { display:grid; grid-template-columns:1fr 1fr; gap:18px; } figure { margin:0; min-width:0; }
    figcaption { font-size:12px; font-weight:600; letter-spacing:.5px; margin-bottom:8px; } .image-box { background:#e6e8df; border:1px solid #d5d9cc; height:340px; display:flex; align-items:center; justify-content:center; padding:8px; }
    .image-box img { width:100%; height:100%; object-fit:contain; } fieldset { border:0; margin:0; padding:0; min-width:0; } legend { font-size:17px; font-weight:650; margin-bottom:8px; }
    .explain { color:var(--muted); font-size:13px; margin-bottom:16px; } .rating-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; }
    .rating-grid label { font-size:13px; } .rating-grid small { display:block; font-weight:400; color:var(--muted); font-size:11px; min-height:37px; margin:4px 0 8px; line-height:1.5; }
    select { width:100%; font-size:14px; } .relevance { margin-top:20px; } .relevance select { max-width:340px; margin-top:8px; } .quality { border-top:1px solid var(--line); margin-top:20px; padding-top:17px; }
    .quality legend { font-size:13px; padding-top:17px; } .checkboxes { display:flex; flex-wrap:wrap; gap:10px 20px; margin-bottom:16px; } .checkboxes label { display:flex; align-items:center; gap:7px; font-size:13px; font-weight:400; }
    .checkboxes input { width:17px; height:17px; margin:0; accent-color:var(--accent); } .comment-label { font-size:13px; margin-bottom:7px; } .navigation { display:flex; justify-content:space-between; gap:12px; margin-top:20px; }
    .footer-row { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:15px; } footer { color:var(--muted); font-size:12px; margin-top:18px; } .count { font-variant-numeric:tabular-nums; }
    .visually-hidden { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
    @media(max-width:700px) { main { padding:22px 14px 40px; } .panel { padding:16px; } .pair-grid { grid-template-columns:1fr; gap:14px; } .image-box { height:280px; } .rating-grid { grid-template-columns:1fr 1fr; gap:16px; } .rating-grid small { min-height:34px; } }
    @media(prefers-reduced-motion:reduce) { * { scroll-behavior:auto!important; } }
  </style>
</head>
<body>
<main>
  <header>
    <p class="eyebrow">FRAME ECHO / VISUAL FEEDBACK</p>
    <h1>综合视觉相似度反馈</h1>
    <p class="intro">请观察艺术作品与视频画面的颜色、构图和内容，独立判断它们的视觉关联。每一对都可以选择“不确定”；备注和画面质量问题为选填。这里收集的是开发反馈，页面不会自动判断你的答案。</p>
  </header>
  <section class="panel" aria-label="评价者设置">
    <form id="reviewer-form" class="reviewer">
      <div><label for="reviewer-id">评价者编号</label><input id="reviewer-id" name="reviewer_id" placeholder="P01" maxlength="64" autocomplete="off" spellcheck="false" aria-describedby="reviewer-help"></div>
      <button type="submit">载入 / 切换编号</button>
      <p id="reviewer-active" class="status">尚未载入编号</p>
    </form>
    <p id="reviewer-help" class="status">请填写简短编号后开始记录；更换编号会载入该编号自己的记录。</p>
    <p id="storage-notice" class="status notice" role="status">填写编号后会尝试保存到当前浏览器；你也可以随时导出 CSV。</p>
    <p id="action-notice" class="error" role="alert" hidden></p>
  </section>
  <section class="panel" id="pair-panel" aria-labelledby="pair-heading">
    <div class="progress-line"><strong id="position" class="count"></strong><span id="completion-count" class="count" aria-live="polite"></span></div>
    <progress id="completion-progress" max="1" value="0" aria-label="已完整填写的配对数量"></progress>
    <div class="pair-title"><h2 id="pair-heading" tabindex="-1"></h2><p id="artist" class="pair-meta"></p></div>
    <div class="pair-grid">
      <figure><figcaption>艺术作品</figcaption><div class="image-box"><img id="reference-image" alt="待比较的艺术作品"></div></figure>
      <figure><figcaption>候选视频画面</figcaption><div class="image-box"><img id="frame-image" alt="待评价的视频画面"></div></figure>
    </div>
    <p id="candidate-label" class="pair-meta"></p>
  </section>
  <form class="panel" id="rating-form" autocomplete="off">
    <fieldset id="rating-fields" disabled>
      <legend>你的判断</legend>
      <p class="explain">1 = 很不相似，5 = 很相似。请分别判断各项；整体关联可以考虑你自己的综合感受。</p>
      <div class="rating-grid">
        <div><label for="colour">颜色<small>色调、明暗和颜色之间的关系</small></label><select id="colour" name="colour" class="rating-select" aria-label="颜色相似度"></select></div>
        <div><label for="composition">构图<small>形状、主体位置和视觉空间的安排</small></label><select id="composition" name="composition" class="rating-select" aria-label="构图相似度"></select></div>
        <div><label for="content">内容<small>画面中的人物、物体或场景</small></label><select id="content" name="content" class="rating-select" aria-label="内容相似度"></select></div>
        <div><label for="overall">整体关联<small>两幅画面放在一起是否有说服力</small></label><select id="overall" name="overall" class="rating-select" aria-label="整体视觉关联"></select></div>
      </div>
      <div class="relevance"><label for="relevance">你认为这个视频画面与作品具有视觉关联吗？</label><select id="relevance" name="relevance"><option value="">请选择</option><option value="yes">有相关性</option><option value="no">没有相关性</option><option value="unsure">不确定</option></select></div>
      <fieldset class="quality"><legend>画面质量问题（选填，可多选）</legend><div class="checkboxes">
        <label><input type="checkbox" name="quality" value="transition">转场 / 镜头叠加</label>
        <label><input type="checkbox" name="quality" value="blur">模糊</label>
        <label><input type="checkbox" name="quality" value="occlusion">遮挡</label>
        <label><input type="checkbox" name="quality" value="other">其他问题</label>
      </div></fieldset>
      <label for="comment" class="comment-label">简短备注（选填）</label><textarea id="comment" name="comment" placeholder="哪些细节让你觉得有关联，或者没有关联？"></textarea>
    </fieldset>
    <div class="navigation"><button id="previous" type="button">← 上一对</button><button id="next" type="button">下一对 →</button></div>
  </form>
  <section class="panel footer-row" aria-label="导出评价记录"><div><strong>保存你的填写记录</strong><p class="status">导出文件包含所有配对；尚未填写的项目保留为空。</p></div><button type="button" id="export" class="primary">导出 CSV</button></section>
  <footer>图片和记录均在本页本地处理。浏览器保存可能受设置影响，请在结束前导出一份 CSV。数据不会通过本页发送到外部服务。</footer>
  <p id="announcement" class="visually-hidden" role="status" aria-live="polite"></p>
</main>
<script id="review-data" type="application/json">__FRAME_ECHO_REVIEW_DATA__</script>
<script>
"use strict";
(() => {
  const data = JSON.parse(document.getElementById("review-data").textContent);
  const items = data.items;
  const byId = (id) => document.getElementById(id);
  const dimensionKeys = ["colour", "composition", "content", "overall"];
  const validRatings = new Set(["", "1", "2", "3", "4", "5", "unsure"]);
  const qualityValues = new Set(["transition", "blur", "occlusion", "other"]);
  const memorySessions = new Map();
  const state = {reviewerId:"", index:0, answers:Object.create(null), storageAvailable:true};
  const reviewerInput = byId("reviewer-id");
  const fields = byId("rating-fields");
  const notices = {storage:byId("storage-notice"), action:byId("action-notice")};
  let rendering = false;

  document.querySelectorAll(".rating-select").forEach(select => {
    [["", "请选择"], ["1", "1 · 很不相似"], ["2", "2 · 较不相似"], ["3", "3 · 一般"], ["4", "4 · 较相似"], ["5", "5 · 很相似"], ["unsure", "不确定"]].forEach(([value,label]) => select.add(new Option(label,value)));
  });

  function announce(text) { byId("announcement").textContent = text; }
  function error(text) { notices.action.textContent = text; notices.action.hidden = false; announce(text); }
  function clearError() { notices.action.hidden = true; notices.action.textContent = ""; }
  function keyFor(reviewerId) { return "frame-echo-feedback:" + JSON.stringify([data.experiment_id, data.dataset_id, reviewerId]); }
  function blankAnswer() { return {colour:"", composition:"", content:"", overall:"", relevance:"", quality_flags:[], comment:""}; }
  function sanitiseAnswer(raw) {
    const safe = blankAnswer();
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return safe;
    dimensionKeys.forEach(key => { if (validRatings.has(String(raw[key] ?? ""))) safe[key] = String(raw[key] ?? ""); });
    if (["", "yes", "no", "unsure"].includes(raw.relevance)) safe.relevance = raw.relevance;
    if (Array.isArray(raw.quality_flags)) safe.quality_flags = [...new Set(raw.quality_flags.filter(value => qualityValues.has(value)))];
    if (typeof raw.comment === "string") safe.comment = raw.comment;
    return safe;
  }
  function complete(answer) { return Boolean(answer && dimensionKeys.every(key => answer[key] !== "" && validRatings.has(answer[key])) && ["yes", "no", "unsure"].includes(answer.relevance)); }
  function partial(answer) { return Boolean(answer && (dimensionKeys.some(key => answer[key] !== "") || answer.relevance || answer.quality_flags.length || answer.comment.trim())); }
  function summary() {
    const answered = items.filter(item => complete(state.answers[item.candidate_id])).length;
    const incomplete = items.filter(item => { const answer = state.answers[item.candidate_id]; return partial(answer) && !complete(answer); }).length;
    byId("completion-count").textContent = `已完整填写 ${answered} / ${items.length} 对${incomplete ? ` · 部分填写 ${incomplete} 对` : ""}`;
    byId("completion-progress").max = Math.max(items.length,1);
    byId("completion-progress").value = answered;
    return answered;
  }
  function storageFailed() {
    state.storageAvailable = false;
    notices.storage.textContent = "浏览器保存不可用：当前填写仅保存在本页内存中。切换编号仍可继续，请及时导出 CSV，关闭页面前先保存文件。";
  }
  function remember() {
    if (!state.reviewerId) return;
    const session = {index:state.index, answers:state.answers};
    memorySessions.set(state.reviewerId, session);
    if (!state.storageAvailable) return;
    try {
      localStorage.setItem(keyFor(state.reviewerId), JSON.stringify({version:1, experiment_id:data.experiment_id, dataset_id:data.dataset_id, ...session}));
      notices.storage.textContent = `当前编号 ${state.reviewerId} 的填写已保存在此浏览器；仍建议导出 CSV 留存。`;
    } catch (_) { storageFailed(); }
  }
  function saveCurrent() {
    if (rendering || !state.reviewerId || !items.length) return;
    const answer = blankAnswer();
    dimensionKeys.forEach(key => answer[key] = byId(key).value);
    answer.relevance = byId("relevance").value;
    answer.quality_flags = Array.from(document.querySelectorAll('input[name="quality"]:checked'), input => input.value);
    answer.comment = byId("comment").value;
    const id = items[state.index].candidate_id;
    if (partial(answer)) state.answers[id] = answer;
    else delete state.answers[id];
    remember();
    summary();
  }
  function renderItem(focusHeading=false) {
    rendering = true;
    byId("previous").disabled = !items.length || state.index === 0;
    byId("next").disabled = !items.length || state.index === items.length - 1;
    fields.disabled = !state.reviewerId || !items.length;
    if (!items.length) {
      byId("position").textContent = "没有配对";
      byId("pair-heading").textContent = "本页没有候选配对";
      byId("artist").textContent = "";
      byId("candidate-label").textContent = "";
      byId("reference-image").removeAttribute("src");
      byId("frame-image").removeAttribute("src");
    } else {
      const item = items[state.index];
      const answer = sanitiseAnswer(state.answers[item.candidate_id]);
      byId("position").textContent = `第 ${state.index + 1} / ${items.length} 对`;
      byId("pair-heading").textContent = item.artwork_title;
      byId("artist").textContent = item.artist;
      byId("reference-image").src = item.reference_image;
      byId("reference-image").alt = `艺术作品：${item.artwork_title}`;
      byId("frame-image").src = item.frame_image;
      byId("candidate-label").textContent = `候选编号：${item.candidate_id}`;
      dimensionKeys.forEach(key => byId(key).value = answer[key]);
      byId("relevance").value = answer.relevance;
      document.querySelectorAll('input[name="quality"]').forEach(input => input.checked = answer.quality_flags.includes(input.value));
      byId("comment").value = answer.comment;
    }
    summary();
    rendering = false;
    if (focusHeading) byId("pair-heading").focus({preventScroll:true});
  }
  function activateReviewer() {
    const nextId = reviewerInput.value.trim();
    if (!nextId || nextId.length > 64 || /[\u0000-\u001f\u007f]/.test(nextId)) {
      error("请先填写 1–64 个字符的评价者编号，例如 P01。不要使用姓名或联系方式。");
      reviewerInput.focus();
      return false;
    }
    clearError();
    if (nextId === state.reviewerId) { saveCurrent(); return true; }
    saveCurrent();
    state.reviewerId = nextId;
    state.index = 0;
    state.answers = Object.create(null);
    let session = memorySessions.get(nextId);
    if (!session && state.storageAvailable) {
      try {
        const stored = localStorage.getItem(keyFor(nextId));
        if (stored) {
          const parsed = JSON.parse(stored);
          if (parsed.dataset_id === data.dataset_id && parsed.experiment_id === data.experiment_id) session = parsed;
        }
      } catch (_) { storageFailed(); }
    }
    if (session && session.answers && typeof session.answers === "object") {
      items.forEach(item => {
        const answer = sanitiseAnswer(session.answers[item.candidate_id]);
        if (partial(answer)) state.answers[item.candidate_id] = answer;
      });
      if (Number.isInteger(session.index)) state.index = Math.max(0,Math.min(session.index,Math.max(items.length - 1,0)));
    }
    reviewerInput.value = nextId;
    byId("reviewer-active").textContent = `当前编号：${nextId}`;
    renderItem();
    remember();
    announce(`已载入编号 ${nextId}；已完整填写 ${summary()} 对。`);
    return true;
  }
  function navigate(offset) {
    saveCurrent();
    state.index = Math.max(0,Math.min(state.index + offset,Math.max(items.length - 1,0)));
    remember();
    renderItem(true);
    announce(`第 ${state.index + 1} 对，${items[state.index]?.artwork_title || "没有配对"}。`);
  }
  function neutralise(value) {
    const text = String(value ?? "");
    return (/^[\s]*[=+\-@]/.test(text) || /^[\t\r\n]/.test(text)) ? "'" + text : text;
  }
  function csvCell(value) { return '"' + neutralise(value).replaceAll('"','""') + '"'; }
  function safeFilename(value) { return String(value).replace(/[^A-Za-z0-9_-]/g,"_").slice(0,80) || "feedback"; }
  function exportCsv() {
    if (reviewerInput.value.trim() !== state.reviewerId || !state.reviewerId) {
      if (!activateReviewer()) return;
    }
    saveCurrent();
    const columns = ["experiment_id","reviewer_id","candidate_id","artwork_id","video_id","frame_sha256","presentation_order","timestamp_seconds","colour","composition","content","overall","relevance","quality_flags","comment","completed"];
    const lines = [columns.map(csvCell).join(",")];
    items.forEach(item => {
      const answer = sanitiseAnswer(state.answers[item.candidate_id]);
      const row = {experiment_id:data.experiment_id, reviewer_id:state.reviewerId, candidate_id:item.candidate_id,
        artwork_id:item.artwork_id, video_id:item.video_id, frame_sha256:item.frame_sha256, presentation_order:item.presentation_order,
        timestamp_seconds:Number(item.canonical_timestamp).toFixed(6), colour:answer.colour, composition:answer.composition,
        content:answer.content, overall:answer.overall, relevance:answer.relevance, quality_flags:answer.quality_flags.join(";"),
        comment:answer.comment, completed:complete(answer) ? "true" : "false"};
      lines.push(columns.map(column => csvCell(row[column])).join(","));
    });
    const blob = new Blob(["\ufeff" + lines.join("\r\n") + "\r\n"], {type:"text/csv;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `frame-echo_${safeFilename(data.experiment_id)}_${safeFilename(state.reviewerId)}.csv`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url),1000);
    clearError();
    const text = `已导出 ${items.length} 对记录，其中 ${summary()} 对已完整填写；其余项目保留为空。`;
    announce(text);
    byId("reviewer-active").textContent = `当前编号：${state.reviewerId} · ${text}`;
  }
  byId("reviewer-form").addEventListener("submit", event => { event.preventDefault(); activateReviewer(); });
  reviewerInput.addEventListener("change", () => { if (reviewerInput.value.trim()) activateReviewer(); });
  byId("rating-form").addEventListener("submit", event => event.preventDefault());
  byId("rating-form").addEventListener("change", saveCurrent);
  byId("comment").addEventListener("input", saveCurrent);
  byId("previous").addEventListener("click", () => navigate(-1));
  byId("next").addEventListener("click", () => navigate(1));
  byId("export").addEventListener("click", exportCsv);
  window.addEventListener("beforeunload", saveCurrent);
  renderItem();
})();
</script>
</body>
</html>
'''
