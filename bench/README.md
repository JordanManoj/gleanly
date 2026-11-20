# Extraction benchmark

Measures how well each extractor recovers the main article text of a web page.

```bash
uv sync --group bench                      # installs baseline extractors
uv run python -m bench.run                 # all extractors, the Scrapinghub article set
uv run python -m bench.run -d all --split test   # all 8 datasets, held-out pages
uv run python -m bench.run -e gleanly --worst 10 --save
uv run python -m bench.confidence --split test   # does extraction_confidence predict F1?
```

The dataset is downloaded on first use into `bench/data/` (git-ignored; the pages are
third-party content). `--save` writes per-page scores to `bench/results/`.

## Metric

Bag-of-words comparison between extracted text and the hand-checked article body:

- **precision**: share of extracted words that belong to the article (low = boilerplate leaked in)
- **recall**: share of the article that was extracted (low = content lost)
- **F1**: harmonic mean, averaged over pages; `F1<0.5` counts badly failed pages

## Tuning discipline

Pages are split by a hash of their id into **dev** (~2/3, used for tuning) and **test**
(~1/3, held out). Every heuristic is tuned on `--split dev` only and kept only if it raises
the dev score. Report `--split test`: those pages never influenced a decision.

## Results: Zyte article-extraction-benchmark (181 pages)

Held-out **test** split (60 pages, never used for tuning), 2026-11-19:

| Extractor | F1 | median | precision | recall | F1<0.5 | ms/page |
| --- | --- | --- | --- | --- | --- | --- |
| **gleanly** | **0.946** | **0.990** | 0.938 | 0.968 | 2 | 14 |
| trafilatura 2.3.1 | 0.943 | 0.988 | 0.923 | 0.992 | 2 | 34 |
| readability-lxml 0.9 | 0.955 | 0.984 | 0.945 | 0.972 | 1 | 36 |

All 181 pages:

| Extractor | F1 | median | precision | recall | F1<0.5 | ms/page |
| --- | --- | --- | --- | --- | --- | --- |
| gleanly, before benchmark work | 0.778 | 0.911 | 0.753 | 0.870 | 28 | 11 |
| **gleanly, now** | **0.958** | **0.987** | 0.942 | 0.982 | 2 | 15 |
| trafilatura 2.3.1 | 0.948 | 0.987 | 0.933 | 0.983 | 4 | 30 |
| readability-lxml 0.9 | 0.958 | 0.984 | 0.942 | 0.981 | 1 | 33 |

### What changed (each step kept only because the dev score rose)

| Step | dev F1 |
| --- | --- |
| Start | 0.778 (all pages) |
| Class/id names weighed against how much prose an element holds; content words win | |
| Whole-page `<form>` (ASP.NET) kept; `<div>` text counts as paragraphs | |
| Link-heavy strips (related stories, share bars) pruned unless they hold prose | 0.913 |
| Scored container choice (length, commas, tag/class priors, link density) + sibling merge | 0.929 |
| Nested image links stripped correctly in plain text | 0.934 |
| Captions, credits, bylines, datelines dropped (bylines/dates stay in `metadata`) | 0.948 |
| Look-alike cousin merge for articles split across repeated containers (NYT, Wired) | 0.963 |

Tried and **rejected** (no dev gain): widening to an ancestor with more prose; voting
between extractors; switching to trafilatura when the two disagree; trimming leading and
trailing blocks that the independent check does not support (+0.001, noise).

### Agreement as a confidence signal

When gleanly and trafilatura agree, gleanly is almost always right; when they disagree,
it is wrong more often (dev split, quartiles of gleanly-vs-trafilatura F1):

| Agreement | gleanly F1 |
| --- | --- |
| lowest quarter (0.84) | 0.925 |
| 2nd (0.98) | 0.965 |
| 3rd (0.99) | 0.982 |
| top quarter (1.00) | 0.978 |

This is the basis for gleanly's extraction-confidence signal.

## Extraction confidence (`QualityReport.extraction_confidence`, `Block.support`)

A second extractor that shares nothing with the main one (it classifies every text block
by length, link density, sentence punctuation and its neighbours, and ignores class names
and the chosen container) re-reads the page. `Block.support` is the share of a block's
words it also kept; `extraction_confidence` is the same over the whole document. Tables,
code and images are not judged. No extra dependency, ~10 ms per page.

Measured with `bench.confidence` (does confidence rank pages by their actual F1?):

| Signal | dev Spearman | dev AUROC* | test Spearman | test AUROC* |
| --- | --- | --- | --- | --- |
| old trust score (no cross-check) | -0.07 | 0.61 | -0.09 | 0.45 |
| **gleanly `extraction_confidence`** | **0.60** | **0.72** | **0.38** | **0.73** |
| agreement with trafilatura (needs a second library) | 0.50 | 0.73 | 0.38 | 0.73 |
| trust score with the cross-check folded in | 0.30 | 0.72 | 0.09 | 0.58 |

\*AUROC = how well it separates failed pages (F1 < 0.9) from good ones; 0.5 is chance.

Held-out pages by confidence quartile: 0.888 / 0.928 / 0.985 / 0.977 mean F1. Pages under
the warning threshold (0.8) averaged F1 0.805 against 0.963 for the rest. The test split
has only 5 failed pages, so treat its numbers as rough. Combining our check with
trafilatura agreement reached AUROC 0.77 on dev; not adopted, to keep the core light.
(The table above is the first, support-only version; see the next section for v2.)

### v2: coverage, checked on all eight datasets (2026-11-20)

`uv run python -m bench.confidence -d all --split test`

Run on all eight datasets, the support-only confidence was weak (pooled dev AUROC 0.60,
Spearman 0.20). The reason: across WCEB most failures are **missed prose** (648 dev pages
with recall < 0.9 against 283 with precision < 0.9), and support only sees leaked
boilerplate. v2 adds the other side:

- `extraction_support`: share of the extracted words the second extractor also kept;
- `extraction_coverage`: share of the second extractor's *prose* blocks (long, few links,
  sentence punctuation) found in the extraction. Measuring coverage against all kept
  blocks instead raised false alarms on cookie notes and footers;
- `extraction_confidence = support x sqrt(coverage)`. Coverage is the noisier side, so it
  gets less weight; on dev, exponent 0.5 had the best average AUROC across datasets
  (0.795; 0 -> 0.597, 1 -> 0.789) and kept the Scrapinghub AUROC at 0.72.

Warning threshold 0.7 (chosen on dev). Held-out test split, 1,270 pages:

| dataset | pages | Spearman | AUROC | flagged | F1 flagged | F1 rest |
| --- | --- | --- | --- | --- | --- | --- |
| scrapinghub-aeb | 52 | 0.26 | 0.78 | 13% | 0.941 | 0.966 |
| wceb-cetd | 226 | 0.68 | 0.90 | 7% | 0.645 | 0.926 |
| wceb-cleaneval | 248 | 0.59 | 0.83 | 11% | 0.604 | 0.949 |
| wceb-cleanportaleval | 16 | 0.69 | 1.00 | 0% | - | 0.949 |
| wceb-dragnet | 429 | 0.57 | 0.81 | 29% | 0.638 | 0.932 |
| wceb-google-trends-2017 | 55 | 0.42 | 0.65 | 24% | 0.721 | 0.916 |
| wceb-l3s-gn1 | 210 | 0.28 | 0.72 | 18% | 0.893 | 0.952 |
| wceb-readability | 34 | 0.50 | 0.91 | 12% | 0.756 | 0.981 |
| **all pooled** | **1,270** | **0.52** | **0.82** | **18%** | **0.692** | **0.940** |

Held-out pages by confidence quartile: 0.735 / 0.915 / 0.957 / 0.973 mean F1. The warning
also says which side is weak ("may be missing" vs "boilerplate may have leaked in").
Dragnet is flagged most because its labels include reader comments that gleanly leaves
out: the coverage check sees them as missed prose, which is correct.

## Results: eight datasets (2026-11-20)

The Scrapinghub set plus the seven other datasets of the Web Content Extraction Benchmark
(Bevendorff et al., SIGIR 2023; `-d wceb`): about 3,900 pages of news, blogs, forums,
wikis, mixed 2007-era pages, Google Trends results and tricky markup. Same metric, same
dev/test split by page id. The WCEB data carries no license of its own, so it is
downloaded into `bench/data/wceb/` for local evaluation only.

Held-out **test** pages (never used for tuning), mean F1:

| Dataset | pages | gleanly | trafilatura 2.3.1 | readability-lxml 0.9 |
| --- | --- | --- | --- | --- |
| scrapinghub-aeb | 54 | 0.947 | 0.943 | 0.955 |
| wceb-cetd | 227 | 0.905 | 0.928 | 0.909 |
| wceb-cleaneval | 261 | 0.890 | 0.900 | 0.874 |
| wceb-cleanportaleval | 16 | 0.949 | 0.948 | 0.952 |
| wceb-dragnet | 461 | 0.825 | 0.895 | 0.812 |
| wceb-google-trends-2017 | 64 | 0.834 | 0.838 | 0.789 |
| wceb-l3s-gn1 | 217 | 0.930 | 0.901 | 0.955 |
| wceb-readability | 39 | 0.936 | 0.929 | 0.956 |
| **macro average** | | **0.902** | **0.910** | **0.900** |
| macro without Dragnet | | 0.913 | 0.912 | 0.913 |

Dragnet's ground truth includes reader comments. Trafilatura extracts comments by default;
gleanly and Readability leave them out, which explains most of that gap (gleanly recall
0.81 vs 0.91 there). gleanly is the fastest of the three on every dataset (11-29 ms/page).

What changed this round (dev macro F1 over all eight datasets, 0.884 before):

| Step | dev macro F1 |
| --- | --- |
| A `<form>` is only skipped when small (search/login); whole-page ASP.NET forms are kept | 0.889 |
| A wrapper with a heading and prose is never a byline (WordPress `hentry ... author-admin`) | 0.889 (fixes a loss on the article set) |
| "promotion"/"promotional" count as boilerplate words | 0.889 |
| **Rescue:** if the main extractor finds <=150 words and the block classifier finds many times more, use the block classifier (`quality.extractor = "blocks"`, with a warning) | **0.900** |

Rejected: rescue up to 300 words (hurt the article set).

## Limits of this dataset

- Scrapinghub: 181 English-heavy news/blog pages. The WCEB sets broaden this, but there is
  still no docs, shop or recent non-English set.
- CETD and CleanPortalEval have many pages per site, so **cross-page template learning**
  can now be measured (`Page.site`).
- The ground truth excludes captions and bylines, so the benchmark rewards dropping them.

## Optional comments (`include_comments=True`, 2026-11-20)

Comment sections are found by class/id (`comments`, `disqus`, ...), excluding ones that
wrap the article (WordPress `<body class="comments-open">`) or are already extracted; inside
them only blocks the block classifier labels as prose are kept, and forms are skipped.
Datasets disagree on whether comments are content, so it is opt-in. Held-out test split
(`-e gleanly,gleanly-comments,trafilatura,readability`):

| dataset | gleanly | gleanly + comments | trafilatura | readability |
| --- | --- | --- | --- | --- |
| scrapinghub-aeb | 0.947 | 0.936 | 0.943 | 0.955 |
| wceb-cetd | 0.905 | **0.934** | 0.928 | 0.909 |
| wceb-cleaneval | 0.890 | 0.896 | 0.900 | 0.874 |
| wceb-cleanportaleval | 0.949 | 0.926 | 0.948 | 0.952 |
| wceb-dragnet | 0.825 | **0.901** | 0.895 | 0.812 |
| wceb-google-trends-2017 | 0.834 | 0.821 | 0.838 | 0.789 |
| wceb-l3s-gn1 | 0.930 | 0.924 | 0.901 | 0.955 |
| wceb-readability | 0.936 | 0.926 | 0.929 | 0.956 |
| macro | 0.902 | 0.908 | 0.910 | 0.900 |

With the setting that matches each dataset's labelling, gleanly averages 0.916.

## Cross-page template learning: tried, not adopted (2026-11-20)

Tested on CETD and CleanPortalEval, the two datasets with many pages per site (sibling
pages used for their HTML only, never their labels; dev pages scored):

| variant | CETD | CleanPortalEval |
| --- | --- | --- |
| gleanly (baseline) | 0.905 | 0.960 |
| drop extracted blocks that repeat on >= half of 3 siblings | 0.905 | 0.960 |
| only non-repeating prose blocks | 0.918 | 0.883 |
| baseline + non-repeating prose it missed | 0.849 | 0.817 |
| site-consistent container (majority vote of 5 siblings) | 0.905 (0 pages changed) | 0.960 |

Why there is no headroom: gleanly already picks the same container on nearly every page of
a site, and on these sites its precision is ~1.0 (Yahoo 1.000, BBC 0.995, Wiki 0.992).
Every remaining error is recall against liberal labels (share bars, "Related stories",
datelines, wiki navboxes), which template removal can only make worse. The +0.013 of the
"non-repeating prose" view on CETD is reader comments, which `include_comments` already
captures better (0.936). The datasets where gleanly leaks boilerplate (L3S, CleanEval) have
one page per site, so template learning cannot be measured there. Revisit with a dataset
of modern multi-page sites with precision failures.


## Real-world regression pages (2026-11-20)

`tests/test_realworld.py` runs four original pages that copy common layouts (news CMS,
docs generator, WordPress with comments, hosted shop) against stored Markdown. They exposed
three bugs the benchmarks did not, all fixed:

- the `<h1>` headline sitting just outside the article-body container was dropped;
- a lone "Edit" link at the edge of a docs page leaked in;
- WordPress `entry-meta` ("Posted on ...") was not treated as byline furniture.

Dev macro F1 stays 0.900. The headline fix moves Scrapinghub 0.963 -> 0.956 and Readability
0.937 -> 0.936 only because those two answer keys omit headlines (headline found in the key
on 0/84 and 3/31 affected pages, against 82-97% on the other six datasets, which go up).
Kept, because users expect the title in the text.

## OCR (`bench/ocr.py`, 2026-11-20)

`uv run python -m bench.ocr --split test`

Pages rendered from our own text (a fixed English word list, numbers, names,
punctuation) in 5 fonts, then degraded 8 ways: clean 300 dpi, fax 100 dpi, blur, noise,
3 degree skew, JPEG quality 10, faint print with a shadow, and a "phone photo" (tilt, blur,
shadow, JPEG). 9 texts: every third is held out (120 test images, 240 dev). Exact ground
truth, no third-party data. Metric: character / word error rate (CER / WER).

Held-out test split, plain Tesseract 5.5 vs gleanly's OCR:

| condition | plain Tesseract | gleanly |
| --- | --- | --- |
| clean 300 dpi | 2.28% | **0.00%** |
| fax 100 dpi | **0.08%** | 1.19% |
| blur | 6.29% | **4.18%** |
| noise | **0.07%** | 0.25% |
| skew 3 deg | **0.14%** | 0.17% |
| JPEG q10 | **0.02%** | 0.06% |
| faint print + shadow | 58.5% | **0.08%** |
| phone photo | 61.4% | **0.22%** |
| **mean CER** | 16.1% | **0.77%** |
| **mean WER** | 16.9% | **1.13%** |
| images under 1% CER | 71% | **96%** |
| time per image (4 in parallel) | 287 ms | 445 ms |

What changed (each step measured on dev before keeping it):

1. **Background flattening** (max filter + blur estimates the paper, which is subtracted):
   dev mean CER 16.6% -> 2.3%. Fixes shadows and faint print, Tesseract's worst cases.
2. **Text-size normalisation** to ~26 px lines, measured in narrow vertical strips:
   2.3% -> 1.4%. Wide fonts at 300 dpi no longer get split into fake columns. A first
   version measured across the full width and broke skewed pages (lines merge), hence the
   strips. Targets 18/22/32 px were worse.

Tried and dropped: a **layout self-check** (re-read as one column when lines come out
fragmented). It fixed the split-column pages but misfired on skewed pages and photos
(dev 1.4% -> 1.7%), and step 2 already fixes those pages.

Known costs: fax-quality text is upscaled about 2.4x, which costs ~1% CER there; and OCR
confidence ranks pages a little less sharply (Spearman with 1-CER 0.52 -> 0.39) because
far fewer pages fail. Blur is the largest remaining error (4.2%).
