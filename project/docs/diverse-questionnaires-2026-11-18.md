# Diverse questionnaire revision — 18 November 2026

The student requested twelve distinct artworks within each questionnaire and different combinations for different classmates. This version implements that request using the saved Top 1 retrieval outputs, with no reranking, model change or generated participant scores.

## Prepared allocation

There are twelve prepared forms, N01–N12, each with twelve different artworks. Four anchor artworks (A80, A96, A14 and A73) recur across forms; eight other artworks rotate without repetition across forms. A seeded permutation of the 100 artwork IDs determines the anchors and rotating blocks, independently of scores or perceived visual success. Each form independently shuffles its presentation order.

Every form has six trials from each video, six assigned to each method and three in each video × method cell. Anchors keep their video while their assigned method flips in consecutive odd/even forms. Thus the shared cases can support descriptive cross-person method comparison when both parities actually have responses. This is not a within-person paired evaluation of the same artwork under both methods.

Completing all twelve forms would cover 100 artworks and 144 presentations. These are planned capacities, not collected response counts. The prepared response template is empty. Only actual completed exports determine the sample size and valid rating denominators.

## Source and integrity

All 144 allocated records and embedded pictures match recorded Top 1 source results. Four anchors appear 12 times each; the other 96 artworks appear once across the prepared set. The organizer key separately records assigned_method and actual_top1_method_membership. Seventeen planned presentations use an image returned first by both methods, including all A80 anchor presentations; those must not be treated as independent visual outcomes for two methods.

Browser verification checked every form's route,12 distinct artworks,initial blank responses,read-only assignedcode and separate dataset. It also checked N01/N02 record isolation,CSV exports with 20 columns,uncertainty,quoted comments and width on desktop/mobile viewports. QA used a temporary browser profile and simulated responses outside the study package. No real participant files were accessed.

## Earlier respondents and analysis

The user reported two respondents before these revisions; their actual CSV files remain uninspected here. Earlier 20-pair and fixed 12-pair pages and stored-file hashes are preserved. Keep their raw exports and identities with their original version. The common fixed 12 pooling plan does not automatically apply to this diverse version. Describe prior fixed-form responses as a separate pre-revision group and record workload,material and position differences.

For v3, join exported questionnaire_id and candidate_id to the organizer mapping, retaining review_version, dataset_id, reviewer_id and source_experiment_id. Compare actual anchor responses separately from rotating exploration, report the limited cross-person design, and account for repeated participants/items. Do not infer method quality from differences between people's overall averages when their images differ. Keep uncertainty separate from missing and numeric values.

The research question and existing retrieval evidence are unchanged. This revision broadens the range of material that can receive feedback; it does not establish improved matching. Thesis findings should be updated after actual files are collected and checked.

## Current entry point

Open the diverse-questionnaire chooser (local archive)

Detailed instructions and schema (local archive)

Organizer method mapping (local archive)
