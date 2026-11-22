"""English version of Frame Echo's existing offline, blinded rating instrument.

The original Chinese generator is left unchanged. This adapter reuses its
candidate validation and interaction template, including participant-separated
browser storage and CSV export. It never supplies ratings or retrieval labels.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from scripts.review_page import _normalise_items, _TEMPLATE


_TRANSLATIONS = {
    'lang="zh-CN"': 'lang="en"',
    "综合视觉相似度反馈": "Visual similarity feedback",
    "请观察艺术作品与视频画面的颜色、构图和内容，独立判断它们的视觉关联。每一对都可以选择“不确定”；备注和画面质量问题为选填。这里收集的是开发反馈，页面不会自动判断你的答案。": "Compare the artwork and video frame, then judge their visual relationship independently. There is no correct or expected answer. You can choose Not sure for any rating. Comments, the connection question and quality flags are optional; no ratings are generated automatically.",
    "评价者设置": "Reviewer setup",
    "评价者编号": "Reviewer ID",
    "载入 / 切换编号": "Load / switch ID",
    "尚未载入编号": "No reviewer ID loaded",
    "请填写简短编号后开始记录；更换编号会载入该编号自己的记录。": "Enter an anonymous ID such as P01 to begin. Switching IDs loads that reviewer's own records.",
    "填写编号后会尝试保存到当前浏览器；你也可以随时导出 CSV。": "After you enter an ID, this page will try to save your progress in this browser. You can export a CSV at any time.",
    "已完整填写的配对数量": "Number of pairs with all four ratings completed",
    "艺术作品": "Artwork",
    "候选视频画面": "Candidate video frame",
    "待比较的艺术作品": "Artwork to compare",
    "待评价的视频画面": "Video frame to rate",
    "你的判断": "Your judgement",
    "1 = 很不相似，5 = 很相似。请分别判断各项；整体关联可以考虑你自己的综合感受。": "1 = very dissimilar; 5 = very similar. Rate the four criteria separately. For overall connection, use your own judgement of how convincing the relationship is.",
    "颜色相似度": "Colour similarity",
    "构图相似度": "Composition similarity",
    "内容相似度": "Content similarity",
    "整体视觉关联": "Overall visual connection",
    "颜色": "Colour",
    "构图": "Composition",
    "内容": "Content",
    "整体关联": "Overall connection",
    "色调、明暗和颜色之间的关系": "Palette, light and dark, and relationships between colours",
    "形状、主体位置和视觉空间的安排": "Arrangement of shapes, subjects and visual space",
    "画面中的人物、物体或场景": "People, objects or scenes shown in the images",
    "两幅画面放在一起是否有说服力": "How convincing the visual relationship feels",
    "你认为这个视频画面与作品具有视觉关联吗？": "Does the frame have a visual connection with the artwork? (optional)",
    "请选择": "Choose a response",
    "有相关性": "Yes",
    "没有相关性": "No",
    "不确定": "Not sure",
    "画面质量问题（选填，可多选）": "Frame quality issues (optional; select any that apply)",
    "转场 / 镜头叠加": "Transition / overlapping shots",
    "模糊": "Blur",
    "遮挡": "Occlusion",
    "其他问题": "Other issue",
    "简短备注（选填）": "Short comment (optional)",
    "哪些细节让你觉得有关联，或者没有关联？": "Which details made the pair feel related or unrelated?",
    "上一对": "Previous pair",
    "下一对": "Next pair",
    "导出评价记录": "Export feedback records",
    "保存你的填写记录": "Save your responses",
    "导出文件包含所有配对；尚未填写的项目保留为空。": "The export includes every pair. Unanswered items stay blank.",
    "导出 CSV": "Export CSV",
    "图片和记录均在本页本地处理。浏览器保存可能受设置影响，请在结束前导出一份 CSV。数据不会通过本页发送到外部服务。": "Images and responses are processed locally in this page. Browser storage depends on your settings, so export a CSV before finishing. This page does not send responses to an external service.",
    "很不相似": "Very dissimilar",
    "较不相似": "Dissimilar",
    "一般": "Neither similar nor dissimilar",
    "较相似": "Similar",
    "很相似": "Very similar",
    "已完整填写 ${answered} / ${items.length} 对${incomplete ? ` · 部分填写 ${incomplete} 对` : \"\"}": "Completed ${answered} / ${items.length} pairs${incomplete ? ` · ${incomplete} partly answered` : \"\"}",
    "浏览器保存不可用：当前填写仅保存在本页内存中。切换编号仍可继续，请及时导出 CSV，关闭页面前先保存文件。": "Browser storage is unavailable. Responses are held in this page's memory only. You can still switch reviewer IDs, but export a CSV before closing the page.",
    "当前编号 ${state.reviewerId} 的填写已保存在此浏览器；仍建议导出 CSV 留存。": "Responses for ${state.reviewerId} are saved in this browser. Export a CSV for a separate copy.",
    "没有配对": "No pairs",
    "本页没有候选配对": "There are no candidate pairs on this page",
    "第 ${state.index + 1} / ${items.length} 对": "Pair ${state.index + 1} / ${items.length}",
    "艺术作品：${item.artwork_title}": "Artwork: ${item.artwork_title}",
    "候选编号：${item.candidate_id}": "Candidate ID: ${item.candidate_id}",
    "请先填写 1–64 个字符的评价者编号，例如 P01。不要使用姓名或联系方式。": "Enter a reviewer ID of 1–64 characters, such as P01. Do not use a name or contact details.",
    "当前编号：${nextId}": "Reviewer ID: ${nextId}",
    "已载入编号 ${nextId}；已完整填写 ${summary()} 对。": "Loaded ${nextId}; ${summary()} pairs completed.",
    "第 ${state.index + 1} 对，${items[state.index]?.artwork_title || \"没有配对\"}。": "Pair ${state.index + 1}: ${items[state.index]?.artwork_title || \"No pairs\"}.",
    "已导出 ${items.length} 对记录，其中 ${summary()} 对已完整填写；其余项目保留为空。": "Exported ${items.length} pair records; ${summary()} have all four ratings. Unanswered items remain blank.",
    "当前编号：${state.reviewerId} · ${text}": "Reviewer ID: ${state.reviewerId} · ${text}",
}


def _english_template() -> str:
    """Translate the UI before inserting any study-specific data."""
    template = _TEMPLATE
    for original, translated in sorted(_TRANSLATIONS.items(), key=lambda pair: len(pair[0]), reverse=True):
        if original not in template:
            raise RuntimeError(f"The review template changed; review translation: {original!r}")
        template = template.replace(original, translated)
    # This question is optional; completion requires the four visual ratings.
    template = template.replace(
        'dimensionKeys.every(key => answer[key] !== "" && validRatings.has(answer[key])) && ["yes", "no", "unsure"].includes(answer.relevance)',
        'dimensionKeys.every(key => answer[key] !== "" && validRatings.has(answer[key]))',
    )
    if re.search(r"[\u3400-\u9fff]", template):
        raise RuntimeError("A review-page UI string has not been translated into English")
    return template


def write_english_review_page(output_path: Path, items: list[dict], experiment_id: str, seed: int) -> None:
    """Write a self-contained English page with no method/rank/score labels.

    Artwork/video identities and timestamps remain available for the CSV join,
    but retrieval method membership and ranks must stay in a separate key file.
    The supplied presentation order is retained and all answers start blank.
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
    destination.write_text(_english_template().replace("__FRAME_ECHO_REVIEW_DATA__", embedded), encoding="utf-8")
