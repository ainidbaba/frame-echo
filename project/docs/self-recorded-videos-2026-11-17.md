# Self-recorded video development comparison — 17 November 2026

Status: retrieval completed; participant-rating materials prepared; no participant responses collected.

## Inputs and fixed design

The two added files were confirmed by the student as self-recorded. They are distinct from the three online reference videos used in previous experiments. Their filming dates have not been supplied. V04 is dog_bar.mp4 (approximately 18.77 seconds); V05 is theweeknd.mp4 (approximately 302.97 seconds). Both source files are 320 × 568 pixels and remain unchanged.

The existing 100-artwork collection and the two original retrieval methods were used. Each condition searches one video, using the same sampled frames for colour and CLIP. Sampling remains one second, requested Top 6 with at least three seconds between returned timestamps. Minimum-score filtering and the temporal quality gate are disabled. Colour uses full-image stretching; CLIP uses its original centre crop. The local ViT-B-32 / laion2b_s34b_b79k checkpoint is unchanged. No new model training or ranking-weight tuning was performed.

The frozen plan and its SHA-256 were saved before decoding or ranking. A new run directory preserves the earlier experiments.

## Verified outputs

| Video | Sampled frames | Conditions | Ranked rows |
| --- | ---: | ---: | ---: |
| V04 | 19 | 200 | 1,118 |
| V05 | 303 | 200 | 1,200 |
| Total | 322 | 400 | 2,318 |

V04 has 82 conditions with five results and 118 with six because of greedy three-second spacing in a short clip. All V05 conditions return six. The output count is therefore lower than the upper bound of 2,400, with no missing conditions.

The saved features independently reproduce all 400 rankings, including source timestamps, cosine scores and temporal suppression. Source video, artwork, normalized query, extracted-frame and checkpoint hashes were verified. Old expanded-run metadata remains unchanged.

## Descriptive observations

These observations describe ranking behaviour, not human relevance labels. Within V04, colour ranks 00:10.000 first for 31 of 100 artwork queries; CLIP ranks 00:07.000 first for 39. The methods have the same first timestamp in 14 artwork/video pairs, and 25 pairs have no exact timestamp overlap in their returned lists. Within V05, colour ranks the bright/confetti-filled 03:39.000 scene first for 42 queries; CLIP's most repeated first timestamp, 04:17.000, occurs for 12. The methods share no first timestamp in V05, and 81 pairs have no exact overlap in their returned lists. Nearby frames can depict the same scene, so exact timestamp agreement is not an accuracy measure.

Preliminary inspection of the fixed review set shows that visual links can remain weak despite a returned Top 1. The concert's lighting and airborne material often differ greatly from the artwork's content. Some CLIP selections include closer views of people or structural lines, but whether those connections are convincing awaits participant judgement. None of these observations is a participant score or an estimated improvement over the earlier videos.

The two candidate pools differ substantially in size and scene content. Comparisons should be interpreted within each video, with the unequal duration and low source resolution reported.

## Human-rating set

A07 Chinese Literatus in an Autumn Landscape, A18 Catherine Greene, A28 Still Life, A43 Music and Dance and A54 The Cathedral were fixed before inspecting new rankings. They provide a purposive range of subjects; the selection was not random or chosen to show only successful matches.

Each query was crossed with both new videos and each method's Top 1 retained. Exact-frame deduplication was defined within each artwork/video pair; no duplicates occurred. This produces 20 unique image pairs across ten artwork/video groups. The shuffled order uses seed 20261117 and is the same for all reviewers. This is not a counterbalanced study or a full evaluation of the 400 conditions.

The English review page embeds all images, conceals method/rank/score, starts with blank responses and exports individual CSVs. The four dimensions are colour, composition, content and overall connection, with Not sure and optional comments. The response template is header-only. Browser QA uses a separate QA_ONLY identity and temporary downloads; those are not participant evidence and are excluded from the published study folder.

See the run README for collection instructions, schema mapping, uncertainty handling and the separate organizer key. Direct artwork appearances remain unknown until assessed. If the feedback informs new settings, that feedback must not also be presented as independent validation of those settings.

## Files

- Organizer comparison (local archive)
- English participant rating page (local archive)
- Rating guide (local archive)
- All rankings (local archive)
- Frozen plan (local archive)
- Organizer key (local archive)

The existing thesis and PPT have not been revised to claim new participant findings. They can be updated after actual feedback is collected and analysed.
