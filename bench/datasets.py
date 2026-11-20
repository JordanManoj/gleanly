"""Benchmark datasets, downloaded on demand into bench/data/ (git-ignored).

The pages are third-party web content, so they are never committed to this repository.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import tarfile
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from gleanly.fetch.http import decode_bytes

DATA_DIR = Path(__file__).parent / "data"


@dataclass(frozen=True)
class Page:
    id: str
    url: str | None
    html: str
    truth: str
    site: str | None = None  # groups pages from the same website (template learning)


@dataclass(frozen=True)
class Dataset:
    name: str
    description: str
    license: str
    archive_url: str
    kind: Literal["scrapinghub", "wceb"] = "scrapinghub"
    subset: str | None = None  # WCEB sub-dataset name

    @property
    def path(self) -> Path:
        return DATA_DIR / ("wceb" if self.kind == "wceb" else self.name)


# Scrapinghub / Zyte article extraction benchmark: 181 news and blog pages with
# hand-checked article bodies. Code and annotations: MIT license.
SCRAPINGHUB = Dataset(
    name="scrapinghub-aeb",
    description="Zyte article-extraction-benchmark (181 article pages)",
    license="MIT (annotations); pages are third-party content",
    archive_url=(
        "https://codeload.github.com/scrapinghub/article-extraction-benchmark/tar.gz/refs/heads/master"
    ),
)

# Web Content Extraction Benchmark (Bevendorff et al., SIGIR 2023): eight earlier datasets
# converted to one format. Code is Apache-2.0; the data carries no separate license, so it
# is only downloaded locally for evaluation, like every other page set here.
WCEB_URL = (
    "https://github.com/chatnoir-eu/web-content-extraction-benchmark/raw/main/datasets/"
    "combined.tar.xz"
)
_WCEB = {
    "cetd": "CETD: news, blogs and forums from a few sites, many pages per site",
    "cleaneval": "CleanEval: very mixed 2007 web pages (whole-page cleaning)",
    "cleanportaleval": "CleanPortalEval: news portals and blogs, several pages per site",
    "dragnet": "Dragnet: news and blog articles, 2012",
    "google-trends-2017": "Google Trends 2017: pages for trending searches (many non-articles)",
    "l3s-gn1": "L3S-GN1: Google News articles, 2008",
    "readability": "Readability test pages: tricky markup cases",
}
WCEB = {
    k: Dataset(
        name=f"wceb-{k}",
        description=desc,
        license="no data license stated (code Apache-2.0); local evaluation only",
        archive_url=WCEB_URL,
        kind="wceb",
        subset=k,
    )
    for k, desc in _WCEB.items()
}

DATASETS = {SCRAPINGHUB.name: SCRAPINGHUB, **{d.name: d for d in WCEB.values()}}
# Datasets other than the original one, for "does it generalise?" runs.
GROUPS = {
    "wceb": [d.name for d in WCEB.values()],
    "all": [SCRAPINGHUB.name, *(d.name for d in WCEB.values())],
}


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "gleanly-bench"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def _download_scrapinghub(ds: Dataset, target: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(_fetch(ds.archive_url)), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            parts = Path(member.name).parts[1:]  # drop the "<repo>-master/" prefix
            if parts == ("ground-truth.json",):
                rel = Path("ground-truth.json")
            elif len(parts) == 2 and parts[0] == "html" and parts[1].endswith(".html.gz"):
                rel = Path("html") / parts[1]
            else:
                continue
            _write(tar, member, target / rel)


def _download_wceb(ds: Dataset, target: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(_fetch(ds.archive_url)), mode="r:xz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            parts = [p for p in Path(member.name).parts if p]
            if len(parts) == 3 and parts[1] == "ground-truth" and parts[2].endswith(".jsonl"):
                rel = Path("ground-truth") / parts[2]
            elif len(parts) == 4 and parts[1] == "html" and parts[3].endswith(".html"):
                rel = Path("html") / parts[2] / parts[3]
            else:
                continue
            _write(tar, member, target / rel)


def _write(tar: tarfile.TarFile, member: tarfile.TarInfo, out: Path) -> None:
    """Write one archive member; only plain names we built ourselves are used as paths."""
    out.parent.mkdir(parents=True, exist_ok=True)
    src = tar.extractfile(member)
    if src is not None:
        out.write_bytes(src.read())


def download(ds: Dataset) -> Path:
    """Fetch and unpack the dataset once. Only data files are extracted, never code."""
    target = ds.path
    marker = target / ("ground-truth" if ds.kind == "wceb" else "ground-truth.json")
    if marker.exists():
        return target
    target.mkdir(parents=True, exist_ok=True)
    if ds.kind == "wceb":
        _download_wceb(ds, target)
    else:
        _download_scrapinghub(ds, target)
    return target


Split = Literal["all", "dev", "test"]


def split_of(page_id: str) -> Split:
    """Stable split by page id: ~2/3 "dev" for tuning, ~1/3 "test" held out.

    Tune heuristics on dev only and report test, so the numbers are not overfitted.
    """
    return "dev" if int(hashlib.sha256(page_id.encode()).hexdigest(), 16) % 3 else "test"


def site_of(source: str) -> str | None:
    """Website group from a WCEB source name: "BBC_13" -> "bbc", "blogs.wsj.com_x_01" -> ..."""
    m = re.fullmatch(r"(.+?)[_-]?\d+", source)
    return m.group(1).lower() if m and not source.isdigit() else None


def pages(ds: Dataset, limit: int | None = None, split: Split = "all") -> Iterator[Page]:
    root = download(ds)
    if ds.kind == "wceb":
        yield from _wceb_pages(ds, root, limit, split)
        return
    truth = json.loads((root / "ground-truth.json").read_text(encoding="utf-8"))
    selected = [kv for kv in sorted(truth.items()) if split == "all" or split_of(kv[0]) == split]
    for i, (page_id, item) in enumerate(selected):
        if limit is not None and i >= limit:
            break
        html_path = root / "html" / f"{page_id}.html.gz"
        if not html_path.exists():
            continue
        html = gzip.decompress(html_path.read_bytes()).decode("utf-8", errors="replace")
        yield Page(page_id, item.get("url"), html, item.get("articleBody") or "")


def _wceb_pages(ds: Dataset, root: Path, limit: int | None, split: Split) -> Iterator[Page]:
    gt = root / "ground-truth" / f"{ds.subset}.jsonl"
    # Split on "\n" only: str.splitlines() also breaks at U+2028 inside JSON strings.
    lines = gt.read_text(encoding="utf-8").split("\n")
    rows = [json.loads(line) for line in lines if line.strip()]
    rows = [r for r in rows if (r.get("plaintext") or "").strip()]  # nothing to score against
    rows.sort(key=lambda r: r["page_id"])
    count = 0
    for row in rows:
        if split != "all" and split_of(row["page_id"]) != split:
            continue
        if limit is not None and count >= limit:
            break
        html_path = root / "html" / str(ds.subset) / f"{row['page_id']}.html"
        if not html_path.exists():
            continue
        source = row.get("source") or []
        name = source[1] if isinstance(source, list) and len(source) > 1 else ""
        count += 1
        yield Page(
            row["page_id"],
            row.get("url"),
            decode_bytes(html_path.read_bytes()),
            row["plaintext"],
            site=site_of(name) if ds.subset in ("cetd", "cleanportaleval") else None,
        )
