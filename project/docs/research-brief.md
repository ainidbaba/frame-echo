# Frame Echo — Research Brief

Status: working proposal, 5 November 2026. The submission date supplied by the student is 20 November 2026; the exact submission time remains unknown. No real project footage or query artworks have yet been supplied.

## Project description

Frame Echo uses an artwork as a visual query to retrieve corresponding moments from personally recorded video. Suitable footage includes museum and exhibition visits, landscapes, travel and everyday leisure. The user sees the reference artwork, ranked frames and their positions in the original video.

The proposed creative purpose is to help people explore visual relationships between art and their own recorded experiences. Whether the tool achieves that purpose is a research question to evaluate, not an established outcome.

## What the supervisor specified

The supplied direction states:

> Video -> Frames, this becomes the dataset to find similar images in (compared against a single art image)

This specifies a video-derived retrieval collection and a single artwork used for comparison in each query. It does not specify the similarity algorithm, a sampling interval, aesthetic scoring, model training, video generation or a particular interface.

The student has clarified that footage may show museum or exhibition visits, or everyday landscapes and leisure activities.

## Proposed research question

How do colour-based and CLIP-based representations differ when retrieving personally recorded video frames for an artwork query, and how do viewers judge the resulting visual correspondences?

Supporting questions:

1. Which relationships do viewers identify: colour, composition, depicted content, or another relationship?
2. How do results differ between museum/exhibition footage and everyday footage?
3. What happens when an artwork is physically present in a museum video, compared with retrieval of a different but visually related scene?

## Proposed first version

- One video and one artwork per search.
- Fixed-interval frame sampling with source timestamps.
- A spatial colour-histogram baseline.
- An optional pretrained CLIP image-feature method, compared using the same sampled frames.
- Ranked frame results, a configurable minimum time separation, source-video navigation and CSV export.
- A clearly labelled synthetic example for functional verification.

The minimum time separation makes the returned set easier to inspect. It is also an experimental parameter: keep it fixed when comparing methods, and acknowledge that it changes which ranked frames can appear.

## Current representation definitions

The implementation defines the following methods. Both methods have been checked on synthetic material (see `verification.md`); their retrieval quality on the real collection remains to be evaluated.

**Colour baseline.** Model identifier: `spatial-hsv-12x4x4-grid3-global50-v1`. Images are resized to 144 × 144 pixels by stretching, then represented using 12 × 4 × 4 joint HSV histograms. A global histogram receives half the representation weight and a 3 × 3 grid shares the other half. Each histogram is L1-normalised and square-root transformed; the concatenated 1,920-dimensional representation is L2-normalised for cosine comparison. This captures colour distribution and coarse spatial colour layout. It is not a dedicated object recogniser or a full composition-analysis method. Resizing, grid boundaries and weighting are design choices to discuss.

**CLIP feature method.** The selected configuration is OpenCLIP `ViT-B-32` with the LAION `laion2b_s34b_b79k` pretrained weights. Record it exactly in experiments; this is not the original OpenAI checkpoint. The application loads the local `data/models/open_clip_model.safetensors` file only. Optional dependencies and the downloaded model are both required; there is no automatic download or method substitution during retrieval.

**Ranking and temporal selection.** Rank candidate frames by descending cosine similarity, with earlier timestamps first for equal scores. Greedily accept ranked results that meet the configured minimum temporal separation from already accepted results. The final set can contain fewer than the requested K results. This selection policy must be held constant during a method comparison.

## Proposed boundaries

The first version focuses on retrieval from the supplied footage. Training a new foundation model, generating video, identifying art-historical influence and assigning objective artistic value are outside this initial scope. Aesthetic re-ranking may be considered after the core retrieval and evaluation work, if time and evidence justify it.

## Preparing real material

The following is a proposed pilot, not a completed dataset or a fixed course requirement:

- Select two or three short, varied videos that can be processed comfortably on the project computer.
- Include both museum/exhibition and everyday footage if available; record the actual categories collected.
- Choose approximately eight to twelve artworks with varied colour, composition and depicted content, then reduce or expand the set after the pilot.
- Preserve source filenames, duration, capture context and the exact query image used.
- Record sources in `data-manifest.csv`. Use stable IDs such as `V01` and `A01`.
- For museum footage, record whether each query artwork appears in the source video: `yes`, `no` or `unknown`.
- Keep pilot queries separate from the final evaluation selection when adjusting parameters. Record any overlap and its implications.

The student must supply and inspect the real material. Test assets and example identifiers must never be reported as a collected dataset.

## Role of the supplied resources

[Art Datasets](https://github.com/georgeblck/art-datasets) is a directory of art datasets and museum collections. It can help locate artwork queries and reference material; its listed collections are not automatically the collection being searched by Frame Echo.

[LAION-Aesthetics](https://laion.ai/blog/laion-aesthetics/) describes predicting human aesthetic preference ratings from CLIP image features and using the predictions to select image subsets. A preference score and similarity to a specified artwork answer different questions. The resource motivates an optional future investigation; it does not establish an aesthetic-scoring requirement for this project.

[CLIP](https://github.com/openai/CLIP) provides the underlying image-feature approach. Frame Echo selects the separate [OpenCLIP implementation](https://github.com/mlfoundations/open_clip) and LAION-trained weights described above. Using these features for frame retrieval is an implementation choice. Their usefulness for the selected artworks and footage must be evaluated.

## Evidence needed before conclusions

Preserve the actual dataset manifest, retrieval settings, exported rankings, software version, selected examples, participant records where applicable, analysis decisions and limitations. A working prototype alone does not show that viewers find its matches meaningful.
