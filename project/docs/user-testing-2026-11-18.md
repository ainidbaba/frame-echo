# User testing — 18 November 2026

The seven returned questionnaire exports are discussed together as one exploratory user-testing collection, following the student's requested presentation. Form versions and source identifiers remain in the data so individual judgments can be traced. Earlier questionnaires, reports, scores, model and retrieval outputs are unchanged.

## Observations and summary

There are seven returned forms with 100 completed artwork–frame evaluations and 400 numeric criterion ratings. The records concern 36 artworks and 54 distinct image pairs. The seven anonymous codes do not, by themselves, establish seven distinct people or identify returning participants.

| Criterion | Mean / 5 | Median / 5 | Rating counts 1 / 2 / 3 / 4 / 5 |
| --- | ---: | ---: | --- |
| Colour | 2.71 | 3 | 21 / 23 / 22 / 32 / 2 |
| Composition | 1.98 | 2 | 40 / 33 / 17 / 9 / 1 |
| Content | 1.56 | 1 | 63 / 26 / 4 / 6 / 1 |
| Overall connection | 1.86 | 2 | 32 / 53 / 12 / 3 / 0 |

All 400 criterion responses are numeric, without missing or unsure criterion ratings. The separate optional connection question received 17 yes, 53 no and 30 unsure answers. One written comment and three blur-flagged evaluations are retained exactly as submitted.

These are descriptive values for the collected rating rows. Each row has equal weight, so twenty-pair forms contribute more records than twelve-pair forms. Materials and numbers of ratings per pair differ. No equal-person mean, overall accuracy rate, improvement between batches, method advantage or independent style effect is estimated. Repeated judgments are not independent participant samples.

## Cases selected after reviewing scores

- S03 / V03 / 39.000 seconds, CLIP: overall 3, 4, 4; composition 5, 4, 4; content 4, 4, 4; three yes responses. Upright plant-like installation forms offer a plausible connection with painted roadside trees. The indoor setting differs from the artwork.
- S06 / V04 / 12 seconds, colour: overall 3, 2, 1; composition 4, 3, 3; content 2, 1, 1; yes, unsure and no. A possible arrangement-based relationship coexists with disagreement about the overall connection.
- S08 / V05 / 220 seconds, colour: colour 4, 3, 4; composition and content 1 throughout; overall 2 throughout. Palette similarity does not establish comparable subjects or composition.
- A28 / V05 / 219 seconds, colour: colour 5, 4 but content 1, 1 and overall 2, 2. This is another high-colour/low-content example. One form marked blur. These judgments are retained independently of the S08 judgments.
- S05 / V05 / 141 seconds, CLIP: all three relevant forms gave 1 to every criterion and answered no. First rank within the available frames does not ensure a suitable match.
- S11 / V01 / 78.022 seconds, assigned CLIP: overall 1, 2, 2 and three no responses. The bright overlapping transition is Top1 under both methods; each actual judgment is counted once. The transition description is a researcher observation, not an explanation written by participants.

For the saved CLIP conditions, S11's raw score is 0.356988 and S03's is 0.352215. A single minimum cutoff cannot exclude S11 while retaining S03 in these recorded examples. This supports discussing the limitation of score-only rejection, without calibrating a universal cutoff. Case explanations are researcher observations; quoted participant comments are identified separately in the report.

## Files and reproduction

The submission includes the [aggregate table for all 54 pairs](evaluation-summary/item-summary.csv). The figures and discussion of selected cases are in [the thesis](../../thesis/Frame-Echo-Thesis.pdf).

The original study archive includes an English offline report (local archive), with all six full-image cases, individual scores, all 54 pair summaries and 100 filterable evaluations. Raw exports are archived byte for byte under its `raw/` directory. `analysis-rows.csv`, `item-summary.csv`, `summary.json` and `provenance/` preserve calculations and checks.

Use the project Python environment to run `scripts/analyse_user_testing.py --project <bishe-path> --downloads <actual-export-folder> --output <new-analysis-directory> --case-notes data/evaluation/2026-11-18-user-testing-r2/provenance/case-notes.json`. The builder refuses an existing output directory and reuses the verified earlier analysis solely for source metadata, checking its values against the actual archived raw exports. New SUP12 rows are checked against their saved questionnaire and source results.

Independent calculations matched all 100 response rows, 400 scores and 54 item summaries. Browser QA used a temporary profile and checked full images, displayed case values, filters, local links and desktop/mobile layouts. No real browser-stored answers were accessed. The thesis and PPT were not edited in this analysis step.
