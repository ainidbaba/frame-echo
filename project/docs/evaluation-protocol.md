# Frame Echo — Evaluation Protocol

Status: proposed protocol. No participant responses, retrieval-quality findings or quantitative results have been collected in this document.

## Revision note — 18 November 2026

The current participant interface follows the [v3 design with 12 different artworks](diverse-questionnaires-2026-11-18.md). Each person sees 12 distinct artworks, with balanced video and method assignment, four crossed anchors and eight rotating works. The original fixed-task proposal below is retained for provenance; participants in the current task do not all see the same materials. Keep earlier responses labelled by version and report the changed design and actual sample. Prepared forms are not collected responses.

## Purpose

Compare the visual relationships retrieved by the colour baseline and the CLIP feature method. Investigate how viewers interpret the results, using the same artwork/video pairs and sampling settings for both methods.

Functional tests answer whether the program works as implemented. The evaluation below answers whether the retrieved relationships are useful or convincing to viewers. Keep those evidence types separately identified.

## Preparation

1. Populate `data-manifest.csv` with the actual footage and artwork queries.
2. Create a small pilot selection to check task clarity and runtime. Record all changes made after it.
3. Freeze the final evaluation pairs, method versions, frame interval, result count and minimum time gap before collecting final ratings.
4. Use the same decoded frame collection for both methods. Preserve original query images and exported rankings.
5. Record failed processing and unavailable methods. Do not substitute one method silently for another.
6. Choose a feasible participant count and record recruitment and actual attendance. A small exploratory study can describe its participants, but should not claim to represent all viewers. Follow any applicable course research procedures; discuss uncertainty with the supervisor.

## Experimental unit and comparison

The unit is a query-artwork/video pair. For each pair, each method returns the same requested number of time-separated results. Keep the returned timestamp, rank, score, sampling settings and asset IDs.

For each pair, form the union of returned candidate frames and identify duplicates by video ID and timestamp. Present each unique candidate with its query artwork using a consistent image size and crop policy. Conceal the method and original rank during individual ratings, and randomise candidate order using a recorded seed or saved presentation order. A candidate can belong to both methods.

Method-specific result sets may then be shown as anonymous A/B sets, with their order counterbalanced, for an optional preference question. Keep individual-frame ratings and set preferences separate in analysis.

Do not compare raw colour and CLIP scores as if they were a shared scale. Human ratings and rankings supply the comparison evidence.

## Participant task

Explain that there is no single correct interpretation. Ask each participant to inspect the artwork and candidate frame, then rate the following separately:

| Criterion | Prompt | Scale |
| --- | --- | --- |
| Colour | How similar are their colour relationships? | 1 = very dissimilar; 5 = very similar |
| Composition | How similar is the arrangement of shapes, subjects and visual space? | 1–5 |
| Content | How similar are the depicted objects or scene? | 1–5 |
| Overall visual relationship | How convincing is the visual relationship between these images? | 1–5 |

Allow `not sure` rather than forcing a rating where necessary. Ask for a short optional explanation: “What made this pair feel related or unrelated?”

For the optional set task, ask which set better supports exploring a connection with the artwork: A, B, neither, or no preference. Do not tell participants which answer is expected.

Use anonymous participant IDs in working records. Keep any contact or participation administration separately from material intended for submission. Record what participants actually agreed to share; do not publish identifiable responses by default.

## Museum-specific distinction

Label each query/video pair for whether the queried artwork appears in the footage: `yes`, `no` or `unknown`. Also mark individual candidates that show the same artwork when this can be established by inspection.

Report identity matches separately from visual correspondences with other works or scenes. Finding the source artwork in a museum recording and finding an analogous everyday scene are different retrieval situations. Do not allow a strong identity-match result to stand as evidence for the other situation.

## Records

`evaluation-records.csv` is an empty rating table. Use one row per participant and candidate frame; `method_membership` may contain `colour`, `clip` or `both`. Store method ranks and scores in the exported retrieval files. Record `presentation_order` so the evaluation can be reconstructed.

Save a short session note with date, actual instructions, number of tasks completed, interruptions and any departures from the planned protocol. Leave missing ratings blank and record the reason rather than assigning a zero.

## Analysis plan

- Report the actual numbers of videos, artworks, pairs, candidate frames, participants and completed ratings.
- Summarise ratings by method and criterion, showing variation as well as central tendency. State the aggregation unit and avoid treating multiple frames from the same video as unrelated independent examples.
- Compare museum and everyday cases descriptively, separating identity matches where present.
- Group recurring explanations, preserving counterexamples and disagreement. State how the categories were produced.
- Select successful and unsuccessful cases with an explicit rationale; do not show only the best-looking matches.
- If binary relevance labels are defined and collected, a metric such as Precision@K can be computed with its rule and denominator reported. A similarity score alone is not a relevance label.
- State limits arising from the selected footage, artworks, participants, parameter choices, model representations and any missing method comparison.

The evaluation may reveal that different methods capture different kinds of resemblance. Claims should follow the collected evidence, including negative or mixed findings.
