"""Render all seven returned forms as one offline English user-testing report.

Only supplied, validated response records are displayed. All source images are
embedded without cropping. This module neither changes questionnaires nor reads
or writes browser storage.
"""
from __future__ import annotations

import base64
import html
from pathlib import Path

CRITERIA = ('colour', 'composition', 'content', 'overall')
LABELS = {'colour': 'Colour', 'composition': 'Composition', 'content': 'Content',
          'overall': 'Overall connection'}

CSS = '''
:root{color-scheme:light;--paper:#f6f3ec;--panel:#fffdfa;--ink:#252a25;--muted:#5e685f;--rule:#d7dcd1;--accent:#914a34}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.65 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1160px;margin:0 auto;padding:44px 26px 70px;min-width:0}header{margin-bottom:30px}h1{font-size:clamp(29px,4.2vw,44px);line-height:1.16;max-width:900px;margin:12px 0 20px}h2{font-size:26px;line-height:1.3;margin:38px 0 15px}h3{font-size:20px;line-height:1.35}p{max-width:950px}a{color:var(--accent);text-underline-offset:3px}a:hover{color:#652f20}a:focus-visible,input:focus-visible,select:focus-visible,button:focus-visible{outline:3px solid #8f9f7d;outline-offset:3px}
.eyebrow{font-size:12px;letter-spacing:1.5px;color:var(--accent)}.note,.caption{font-size:14px;color:var(--muted)}.callout{background:#e9eee5;border-left:4px solid #667b62;padding:15px 21px;margin:22px 0}.callout p{margin:5px 0}.links{display:flex;flex-wrap:wrap;gap:9px 24px}.summary-counts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:25px 0}.count{background:var(--panel);border:1px solid var(--rule);padding:15px 18px}.count strong{display:block;font-size:29px;line-height:1.25}.count span{font-size:14px;color:var(--muted)}
.table-wrap{overflow:auto;border:1px solid var(--rule);background:var(--panel);border-radius:4px;margin:16px 0 22px;max-width:100%}table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}th,td{padding:10px 12px;text-align:left;vertical-align:top;border-bottom:1px solid #e3e6de}th{background:#edf0e7;font-weight:650}tbody tr:last-child td{border-bottom:0}td.nowrap{white-space:nowrap}.wide{min-width:800px}.details{min-width:1060px}.details td{white-space:nowrap}.details td.title{white-space:normal;min-width:160px;max-width:250px}.item-table{min-width:1050px}.item-table td.title{min-width:190px;max-width:250px}
.details td.response-note{white-space:pre-wrap;min-width:170px;max-width:280px}.rating-bar{display:flex;width:100%;max-width:580px;height:30px;overflow:hidden;border-radius:3px;margin:12px 0}.rating-bar span{display:flex;align-items:center;justify-content:center;color:#fff;font-size:12px;font-variant-numeric:tabular-nums;min-width:0}.s1{background:#8b4b39}.s2{background:#a36845}.s3{background:#79774f}.s4{background:#52705a}.s5{background:#2c6257}.legend{display:flex;flex-wrap:wrap;gap:8px 17px;font-size:13px;color:var(--muted)}.legend i{display:inline-block;width:11px;height:11px;margin-right:5px}
.cases{display:grid;grid-template-columns:minmax(0,1fr);gap:25px}.case{background:var(--panel);border:1px solid var(--rule);border-radius:4px;padding:24px;min-width:0}.case h3{margin:0 0 10px}.case-meta{font-size:14px;color:var(--muted)}.pair{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px;margin:18px 0 22px}.pair figure{margin:0;min-width:0}.pair img{display:block;width:100%;height:340px;object-fit:contain;background:#ecece4}.pair figcaption{font-size:13px;line-height:1.5;color:var(--muted);margin-top:7px}.interpretation{border-top:1px solid #e0e4d9;padding-top:12px}.case .table-wrap{margin-bottom:15px}.filters{display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px 20px}.filters label{display:flex;flex-direction:column;gap:5px;font-size:14px}.filters select,.filters input,.filters button{font:inherit;color:var(--ink);border:1px solid #aeb8a7;border-radius:3px;background:white;padding:8px 10px;max-width:100%}.filters button{cursor:pointer}.filters input{width:260px}.row-count{font-size:14px;color:var(--muted);min-height:24px}blockquote{border-left:3px solid #c5cdbb;margin:18px 0;padding:8px 0 8px 19px;color:#3d483c}footer{border-top:1px solid var(--rule);margin-top:40px;padding-top:19px;font-size:13px;color:var(--muted)}code{overflow-wrap:anywhere;font-size:12px}li{margin:7px 0}
@media(max-width:650px){main{padding:26px 15px 45px}.summary-counts{gap:8px}.count{padding:12px 10px}.count strong{font-size:25px}.count span{font-size:12px}.case{padding:16px}.pair{grid-template-columns:minmax(0,1fr)}.pair img{height:280px}th,td{padding:8px 9px}.filters{display:grid;grid-template-columns:minmax(0,1fr);gap:12px}.filters select,.filters input{width:100%}.filters button{width:max-content}.links{gap:8px 19px}h2{font-size:23px}}
@media print{body{background:white}main{max-width:none;padding:0}.filters{display:none}.case{break-inside:avoid}.table-wrap{overflow:visible}.links{display:none}.pair img{height:270px}}
'''


def esc(value):
    return html.escape(str(value), quote=True)


def number(value, digits=3):
    if value is None:
        return 'Not available'
    return f'{value:.{digits}f}'


def score(value):
    if value is None or value == '':
        return 'Not answered'
    return 'Not sure' if value == 'unsure' else str(value)


def relevance(value):
    return {'yes': 'Yes', 'no': 'No', 'unsure': 'Not sure',
            'missing': 'Not answered', '': 'Not answered', None: 'Not answered'}.get(value, str(value))


def table(headers, records, css_class=''):
    body = ''.join('<tr>' + ''.join(f'<td>{esc(value)}</td>' for value in row) + '</tr>' for row in records)
    return (f'<div class="table-wrap"><table class="{esc(css_class)}"><thead><tr>'
            + ''.join(f'<th scope="col">{esc(value)}</th>' for value in headers)
            + '</tr></thead><tbody>' + body + '</tbody></table></div>')


def image_uri(path):
    path = Path(path)
    mime = 'image/png' if path.suffix.lower() == '.png' else 'image/jpeg'
    return f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode('ascii')


def distribution_row(stats):
    return [stats['distribution'].get(str(n), 0) for n in range(1, 6)]


def _normalise_notes(case_notes):
    if isinstance(case_notes, dict):
        case_notes = case_notes.get('cases', case_notes.get('case_notes', []))
    return {note['candidate_id']: note for note in case_notes}


def write_report(output: Path, summary: dict, rows: list[dict], project: Path, case_notes: list[dict]):
    """Write ``index.html`` from a validated summary, records and case notes.

    Required summary fields are ``totals``, ``overall``, ``per_item``
    and ``input_manifest``. ``per_item`` carries the
    root-relative source image paths and item metadata. This renderer does not
    infer missing ratings or reinterpret scores.
    """
    output, project = Path(output), Path(project)
    totals, combined = summary['totals'], summary['overall']
    items = summary['per_item']
    if isinstance(items, dict):
        items = list(items.values())
    by_candidate = {item['candidate_id']: item for item in items}
    supplemental = {item['artwork_id']: item for item in items if item['artwork_id'].startswith('S')}
    notes = _normalise_notes(case_notes)
    expected_cases = [supplemental[aid]['candidate_id'] for aid in ['S03', 'S06', 'S08']]
    expected_cases += ['Ce65160f1effc']
    expected_cases += [supplemental[aid]['candidate_id'] for aid in ['S05', 'S11']]
    missing = set(expected_cases) - set(notes)
    if missing:
        raise ValueError('Missing reviewed case notes for: ' + ', '.join(sorted(missing)))
    assert len(rows) == totals['rating_rows']
    out = ['<!doctype html><html lang="en"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width,initial-scale=1">'
           '<meta name="color-scheme" content="light">'
           '<title>Frame Echo — User testing</title>'
           '<style>' + CSS + '</style></head><body><main>']
    out.append('''<header><p class="eyebrow">FRAME ECHO / USER TESTING / 18 NOVEMBER 2026</p>
<h1>User ratings show occasional visual connections and frequent weak matches</h1>
<p>Seven returned forms provide 100 artwork–frame evaluations. Some pairs received higher composition and content ratings. Many others received low overall ratings, including examples with similar colours.</p>
<p class="note">The seven anonymous reviewer codes do not verify seven distinct people or establish who participated more than once. This report discusses all collected forms as user testing.</p></header>
<nav class="links" aria-label="Report sections"><a href="#summary">User ratings</a><a href="#cases">Six image cases</a><a href="#items">All rated pairs</a><a href="#records">All returned records</a><a href="#provenance">Data files</a></nav>''')
    out.append('<div class="summary-counts">' + ''.join(
        f'<div class="count"><strong>{esc(value)}</strong><span>{esc(label)}</span></div>'
        for value, label in [(totals['forms'], 'returned forms'), (totals['rating_rows'], 'pair evaluations'),
                             (totals['numeric_ratings'], 'numeric criterion ratings')]) + '</div>')
    out.append('''<section id="summary"><h2>User ratings</h2>
<p>Ratings run from 1 (very dissimilar) to 5 (very similar). Means describe the collected ordinal responses and are shown alongside medians and complete rating counts.</p>
<p class="note">The forms contain different materials and have different lengths. Pooled values describe the collected evaluations, with longer forms contributing more rows. They are not equally weighted participant averages or estimates of system accuracy.</p>''')
    out.append(table(['Criterion', 'Numeric ratings', 'Mean / 5', 'Median / 5', '1', '2', '3', '4', '5', 'Not sure', 'Missing'], [
        [LABELS[d], combined['ratings'][d]['numeric_n'], number(combined['ratings'][d]['mean']),
         score(combined['ratings'][d]['median']), *distribution_row(combined['ratings'][d]),
         combined['ratings'][d]['unsure_n'], combined['ratings'][d]['missing_n']] for d in CRITERIA], 'wide'))
    overall = combined['ratings']['overall']
    out.append('<p class="caption">Overall rating counts across all returned forms.</p><div class="rating-bar" role="img" aria-label="' + esc(
        '; '.join(f'Rating {n}: {overall["distribution"].get(str(n), 0)}' for n in range(1, 6))) + '">')
    for n in range(1, 6):
        count = overall['distribution'].get(str(n), 0)
        out.append(f'<span class="s{n}" style="width:{100*count/overall["numeric_n"]:.4f}%" title="Rating {n}: {count}">{count if count else ""}</span>')
    out.append('</div><div class="legend">' + ''.join(f'<span><i class="s{n}"></i>Rating {n}</span>' for n in range(1, 6)) + '</div>')
    rel = combined['relevance']
    out.append(f'<p>The optional connection question received <strong>{rel.get("yes", 0)} yes</strong>, '
               f'<strong>{rel.get("no", 0)} no</strong> and <strong>{rel.get("unsure", 0)} not sure</strong> responses. '
               'This question is separate from the four similarity ratings.</p>')
    low_overall = sum(isinstance(r['overall'], int) and r['overall'] <= 2 for r in rows)
    comment_rows = [r for r in rows if r.get('comment')]
    flag_rows = [r for r in rows if r.get('quality_flags')]
    missing_n = sum(combined['ratings'][d]['missing_n'] for d in CRITERIA)
    unsure_n = sum(combined['ratings'][d]['unsure_n'] for d in CRITERIA)
    out.append(f'<div class="callout"><p><strong>{low_overall} of {totals["rating_rows"]} overall ratings were 1 or 2.</strong> '
               'S03 provides a clearer shared connection through composition and content. Other cases show colour-only relations, differing judgments and uniformly weak matches.</p></div>')
    out.append(f'<p class="note">The forms contain {totals["numeric_ratings"]} numeric criterion responses, '
               f'{unsure_n} “not sure” criterion responses and {missing_n} missing criterion responses. '
               f'The separate connection question contains {rel.get("unsure", 0)} “not sure” answers. '
               f'There are {len(comment_rows)} written comments and {len(flag_rows)} evaluations with quality flags. '
               'Unchecked flags do not establish that frames have no quality issues.</p></section>')
    out.append('''<section id="cases"><h2>Six cases to discuss</h2>
<p>These cases were chosen after inspecting the returned ratings to show stronger, mixed and weak outcomes. They do not estimate a success rate. Visual explanations are researcher observations. Written participant comments are shown separately below.</p><div class="cases">''')
    for candidate_id in expected_cases:
        item, note = by_candidate[candidate_id], notes[candidate_id]
        aid = item['artwork_id']
        chosen = sorted([r for r in rows if r['candidate_id'] == candidate_id], key=lambda r: r['reviewer_id'])
        title = note.get('heading', note.get('title'))
        observation = note.get('observation', note.get('researcher_observation', note.get('description')))
        rule = note.get('selection_reason', note.get('selection_rule', 'Selected after inspecting the returned ratings.'))
        if not title or not observation:
            raise ValueError(f'Missing English title or observation for {aid}')
        membership = item['actual_top1_method_membership']
        if isinstance(membership, list):
            membership = ';'.join(membership)
        out.append(f'<article class="case" id="case-{esc(candidate_id)}"><h3>{esc(title)}</h3>'
                   f'<p><strong>{esc(aid)} — {esc(item["artwork_title"])}</strong></p>'
                   f'<p class="case-meta">{esc(item["video_id"])} at {item["timestamp_seconds"]:.3f} seconds. '
                   f'Assigned condition: {esc(item["assigned_method"])}. Actual Top 1 membership: {esc(membership)}.</p>')
        out.append('<div class="pair"><figure>'
                   f'<img src="{image_uri(project/item["normalized_artwork_path"])}" alt="Reference artwork {esc(aid)}">'
                   '<figcaption>Reference artwork. Full normalized source image.</figcaption></figure><figure>'
                   f'<img src="{image_uri(project/item["frame_path"])}" alt="Retrieved source video frame for {esc(aid)}">'
                   '<figcaption>Retrieved frame. Original framing and source annotations are preserved.</figcaption></figure></div>')
        out.append(table(['Reviewer', 'Colour', 'Composition', 'Content', 'Overall', 'Connection'], [
            [r['reviewer_id'], *[score(r[d]) for d in CRITERIA], relevance(r['relevance'])] for r in chosen]))
        chosen_flags = [r for r in chosen if r.get('quality_flags')]
        if chosen_flags:
            out.append('<p class="note">Submitted quality flags: ' + esc('; '.join(r['reviewer_id'] + ': ' + r['quality_flags'] for r in chosen_flags)) + '.</p>')
        out.append(f'<p class="interpretation"><strong>Researcher observation.</strong> {esc(observation)}</p>'
                   f'<p class="note">Case selection: {esc(rule)}</p></article>')
    out.append('</div></section>')
    out.append('<p class="note">For these saved CLIP conditions, the weak S11 transition has a raw score of '
               f'{supplemental["S11"]["source_score"]:.6f}, slightly above the stronger S03 pair at '
               f'{supplemental["S03"]["source_score"]:.6f}. A single minimum-score cutoff cannot exclude S11 '
               'while retaining S03 in these examples. These scores are not relevance probabilities '
               'and this observation does not calibrate a universal threshold.</p>')
    out.append('''<section id="items"><h2>All rated image pairs</h2>
<p>The table keeps every distinct artwork–frame pair, including weak results. Different pairs received different numbers of evaluations. Each mean uses the available ratings for that pair.</p>''')
    ordered = sorted(items, key=lambda x: (x['artwork_id'], x['video_id'], x['timestamp_seconds'], x['candidate_id']))
    out.append(table(['Artwork', 'Video', 'Time (s)', 'Assigned method', 'Actual Top 1', 'Evaluations',
                      'Colour mean', 'Composition mean', 'Content mean', 'Overall mean', 'Overall ratings by reviewer code', 'Connection yes / no / unsure'], [
        [item['artwork_id'] + ' — ' + item['artwork_title'], item['video_id'],
         f'{item["timestamp_seconds"]:.3f}', item['assigned_method'], item['actual_top1_method_membership'],
         item['rating_rows'], *[number(item['ratings'][d]['mean']) for d in CRITERIA],
         '; '.join(r['reviewer_id'] + ': ' + score(r['overall']) for r in sorted([r for r in rows if r['candidate_id'] == item['candidate_id']], key=lambda r: r['reviewer_id'])),
         ' / '.join(str(item['relevance'].get(k, 0)) for k in ('yes', 'no', 'unsure'))]
        for item in ordered], 'item-table'))
    out.append('''<p class="note">Assigned method identifies the saved condition used to select a pair. Actual Top 1 membership records when both methods returned the same image. Each actual response is counted once. The material selections and numbers of ratings differ, so this combined summary does not establish a method advantage.</p></section>''')
    out.append('''<section id="records"><h2>All 100 returned pair evaluations</h2>
<p class="caption">Inspect individual judgments from all collected forms. Filters change the displayed rows only. The CSV retains each form’s version and source identifiers.</p>
<div class="filters"><label>Reviewer<select id="reviewer"><option value="">All reviewer codes</option>'''
               + ''.join(f'<option value="{esc(v)}">{esc(v)}</option>' for v in totals['reviewer_codes'])
               + '</select></label><label>Artwork<select id="artwork"><option value="">All artworks</option>'
               + ''.join(f'<option value="{esc(v)}">{esc(v)}</option>' for v in sorted({i['artwork_id'] for i in items}))
               + '''</select></label><label>Search<input id="search" type="search" placeholder="Artwork, video or candidate ID"></label>
<button id="reset" type="button">Reset filters</button></div><p id="row-count" class="row-count" aria-live="polite">100 evaluations shown.</p>
<div class="table-wrap"><table class="details"><thead><tr>'''
               + ''.join(f'<th scope="col">{esc(h)}</th>' for h in ['Reviewer', 'Order', 'Artwork', 'Video', 'Time (s)', 'Assigned method',
                                                                           'Colour', 'Composition', 'Content', 'Overall', 'Connection', 'Quality flags', 'Comment'])
               + '</tr></thead><tbody>')
    for r in sorted(rows, key=lambda r: (r['reviewer_id'], r['presentation_order'])):
        item = by_candidate[r['candidate_id']]
        search = ' '.join(str(r.get(k, item.get(k, ''))) for k in ('artwork_id', 'artwork_title', 'candidate_id', 'video_id')).lower()
        values = [r['reviewer_id'], r['presentation_order'], r['artwork_id'] + ' — ' + item['artwork_title'],
                  r['video_id'], f'{r["timestamp_seconds"]:.3f}', r['assigned_method'],
                  *[score(r[d]) for d in CRITERIA], relevance(r['relevance']), r.get('quality_flags', ''), r.get('comment', '')]
        out.append(f'<tr data-reviewer="{esc(r["reviewer_id"])}" data-artwork="{esc(r["artwork_id"])}" data-search="{esc(search)}">'
                   + ''.join(f'<td class="{"title" if n == 2 else "response-note" if n >= 11 else "nowrap"}">{esc(v)}</td>' for n, v in enumerate(values)) + '</tr>')
    out.append('</tbody></table></div></section><section id="comments"><h2>Submitted comments and quality flags</h2>')
    for r in comment_rows:
        out.append(f'<blockquote style="white-space:pre-wrap">{esc(r["comment"])}<br><span class="note">Participant comment: {esc(r["reviewer_id"])}, {esc(r["artwork_id"])}, {esc(r["video_id"])} at {r["timestamp_seconds"]:.3f} seconds.</span></blockquote>')
    if flag_rows:
        out.append(table(['Reviewer', 'Artwork', 'Video', 'Time (s)', 'Submitted flag'], [
            [r['reviewer_id'], r['artwork_id'], r['video_id'], f'{r["timestamp_seconds"]:.3f}', r['quality_flags']] for r in flag_rows]))
    out.append('<p class="note">A blank comment or unchecked flag is retained as submitted. It is not an explanation of why another pair received its ratings.</p></section>')
    out.append('''<section id="interpretation"><h2>What the user testing tells us</h2>
<ul><li>S03 offers a clearer shared example of correspondence through composition and depicted content. It is a case-level observation within this selected set.</li>
<li>High colour ratings can coexist with low composition and content ratings. A ranked result can therefore be visually unconvincing overall.</li>
<li>S06 shows that reviewers may agree on some formal features while disagreeing about the overall connection.</li>
<li>The bright transition in S11 remains a failure case even though both methods rank the same frame first.</li></ul>
<p>The collected forms provide preliminary descriptive evidence. They do not establish overall system accuracy, a method advantage, a style effect or a reliable rejection threshold. The selected images and repeated evaluations should not be treated as independent random samples.</p>
<h3>Possible wording for the thesis</h3><blockquote>User testing produced seven completed forms containing 100 image-pair evaluations. Colour received higher average ratings than composition, content and overall connection. Selected cases included a relatively convincing street-scene correspondence, colour similarities with weak content relationships, and different overall judgments of the same pair. The forms used different materials and lengths, so the combined values describe the collected evaluations rather than overall system accuracy. These findings suggest that some visual relationships are meaningful to reviewers, while a high retrieval rank alone does not ensure a convincing match.</blockquote></section>''')
    out.append('''<section id="provenance"><h2>Data and provenance</h2>
<p>All seven actual CSV exports are retained unchanged. Identifiers, presentation order, timestamps and source-image identities were checked against the saved questionnaires. Form versions remain in the data for traceability while this report discusses the responses together as user testing. Original questionnaires, scores and retrieval results remain unchanged.</p>
<nav class="links"><a href="summary.json">Summary JSON</a><a href="analysis-rows.csv">All analysis rows</a><a href="item-summary.csv">Per-pair summary CSV</a><a href="provenance/input-manifest.json">Input files and hashes</a><a href="provenance/validation.json">Validation record</a></nav><ul>''')
    for source in summary['input_manifest']:
        out.append(f'<li><a href="{esc(source["file"])}">{esc(source["reviewer_id"])} raw CSV export</a> ({esc(source["rating_rows"])} pair evaluations)</li>')
    out.append('''</ul></section><footer>Prepared from seven returned forms on 18 November 2026 and discussed collectively as user testing. Original questionnaires and raw scores remain unchanged. No participant responses were generated for this analysis.</footer></main>
<script>
const reviewer=document.getElementById('reviewer');
const artwork=document.getElementById('artwork');
const search=document.getElementById('search');
function filterRows(){let count=0;const query=search.value.trim().toLowerCase();document.querySelectorAll('.details tbody tr').forEach(row=>{const visible=(!reviewer.value||row.dataset.reviewer===reviewer.value)&&(!artwork.value||row.dataset.artwork===artwork.value)&&(!query||row.dataset.search.includes(query));row.hidden=!visible;if(visible)count++;});document.getElementById('row-count').textContent=count+' evaluations shown.';}
[reviewer,artwork,search].forEach(control=>control.addEventListener('input',filterRows));
document.getElementById('reset').addEventListener('click',()=>{reviewer.value='';artwork.value='';search.value='';filterRows();});
</script></body></html>''')
    output.mkdir(parents=True, exist_ok=True)
    (output/'index.html').write_text('\n'.join(out), encoding='utf-8')

