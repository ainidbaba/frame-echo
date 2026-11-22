# Supplemental 12-artwork feedback questionnaire — 18 November 2026

This is a separate, initially unscored English questionnaire made from the saved style-supplement retrieval run. It does not replace the original questionnaires or four returned CSV files.

## Materials and selection

- Each of S01–S12 appears exactly once. These are the twelve new artworks outside the earlier 100-query collection.
- Fixed slots contain six assigned colour conditions and six assigned OpenCLIP conditions. V01–V03 contribute two pairs each; the self-recorded V04/V05 contribute three each.
- Sort artwork IDs, shuffle the fixed video/method slots once with seed 2026111805, assign one slot per artwork and use that saved condition's Top1. Shuffle presentation once with seed 2026112805. No seed search or pair replacement uses scores, perceived success or existing ratings.
- Retrieval results and researcher case inspection already existed. This questionnaire selection is recorded before new ratings, not preregistered before retrieval. Weak results, including S11's bright transition, are retained.
- S11 is assigned to CLIP but the selected image is Top1 for both methods. The organizer key records both actual memberships; it is one image pair and one rating task.
- All reviewers see the same saved set and order. The order is not counterbalanced. Artwork/video confounding prevents a controlled method comparison from the two assigned six-item groups.

## Use on the student's computer

1. Open `../data/evaluation/2026-11-18-supplement-review12-v1/review.html` in a browser. It works offline and contains its images.
2. Assign one anonymous ID per person. New reviewers can use R01, R02, etc. Returning reviewers can keep their previous ID so repeat participation can be documented. Do not enter names or contact details.
3. Select **Start / resume**. New IDs begin with blank ratings and 0/12 complete. Give colour, composition, content and overall connection ratings separately, or choose **Not sure**. The connection question, quality flags and comments are optional.
4. Select **Export CSV** before changing reviewer IDs or finishing. Use the same browser, file and ID to resume when local storage is available. A response is not safely collected until its export is retained.
5. Keep each actual export unchanged. No completed questionnaire is included in this new instrument. Do not use the empty response template or automated QA answers as participant data.

The participant page hides retrieval method, rank and raw score. Do not show `organizer/index.html`, the selection contact sheet or review key while collecting responses. Any Chinese text inside a source frame is part of the original video, not questionnaire UI.

## Identities and provenance

- Experiment: `frame-echo-supplement-review12-v1-20261118`
- Questionnaire: `SUP12`
- Version: `style-supplement-12-v1`
- Source: `frame-echo-2026-11-18-style-supplement-r1`
- Each CSV includes these identities, the dataset hash, anonymous reviewer ID, candidate ID, artwork/video IDs, source-frame hash, presentation order and timestamp.
- Original source image hashes and resized display-image hashes are recorded separately. Display JPEGs preserve aspect ratio without cropping. `organizer/selection-plan.json` records the exact allocation and source-results hash.
- Existing original questionnaires, four actual exports, thesis, presentation, retrieval data, model and old script files remain unchanged. The README and process log are updated only to add this new entry and preserve earlier links.

## Validation and reproduction

Independent static audit verified all twelve distinct artworks, twelve distinct source frames, assigned saved Top1 conditions, timestamps, 24 embedded images, seeded allocation/order, hidden fields and dataset identity. Browser checks used an isolated temporary profile only, with artificial QA IDs; no real browser answers were inspected or changed. They covered blank starts, all images, rating uncertainty, optional fields, ID isolation, reload/resume, CSV download/quoting and desktop/mobile layouts. QA response CSVs are not published as research data. Validation evidence is in the new study's `provenance/` directory.

Run `scripts/build_supplement_review.py --project-root <bishe-path> --output <new-directory>` with the project Python environment to reproduce the fixed selection. The builder refuses an existing destination. It uses the new `scripts/style_review_ui.py` adapter and leaves old questionnaire generators untouched. Creation timestamps can differ between builds; the allocation and source-image identities remain deterministic.

Future analysis should report the actual number of people, completed forms and missing/uncertain ratings, retain repeat participation, and analyse this version separately from earlier materials. These twelve descriptive comparisons do not establish overall accuracy, a universal threshold, or an independent style effect.
