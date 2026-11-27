from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from gleanly.__about__ import __version__

PROJECT_URL = "https://github.com/JordanManoj/gleanly"
ROBOTS_TOKEN = "gleanly"
# Honest identification: library name, version and a contact URL. Never a browser UA.
DEFAULT_USER_AGENT = f"{ROBOTS_TOKEN}/{__version__} (+{PROJECT_URL})"


class LoadOptions(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_agent: str = DEFAULT_USER_AGENT
    robots_token: str = Field(
        default=ROBOTS_TOKEN,
        description="Product token matched against robots.txt User-agent lines.",
    )
    timeout: float = Field(default=20.0, gt=0, description="Per-request timeout in seconds.")
    respect_robots: bool = True
    check_tdmrep: bool = True
    check_ai_txt: bool = Field(default=True, description="Fetch and apply the site's /ai.txt.")
    browser: Literal["auto", "never", "always"] = Field(
        default="auto",
        description="auto: render with Playwright only when the page looks JS-rendered and "
        "cheaper rungs failed. Requires the [browser] extra.",
    )
    min_delay: float = Field(
        default=1.0, ge=0, description="Minimum seconds between page requests to the same host."
    )
    max_bytes: int = Field(default=15_000_000, gt=0, description="Response size cap.")
    max_redirects: int = Field(default=10, ge=0)
    include_comments: bool = Field(
        default=False,
        description="Append reader comments after the main content (blocks get "
        "role='comment'). Off by default: for most AI uses comments are noise.",
    )
    ocr: Literal["auto", "never"] = Field(
        default="auto",
        description="auto: OCR images and PDF pages without a text layer when an OCR engine "
        "is available (glyphly, or the [ocr] extra with the Tesseract program). never: skip "
        "OCR.",
    )
    ocr_engine: Literal["auto", "glyphly", "tesseract"] = Field(
        default="auto",
        description="auto: glyphly when it is installed (no other program needed), else "
        "Tesseract. glyphly or tesseract: use only that engine.",
    )
    ocr_lang: str = Field(
        default="eng",
        description="OCR language(s), e.g. 'eng', 'mal' or 'eng+ben' (Tesseract codes; "
        "two-letter codes such as 'ml' work with glyphly). glyphly detects most scripts by "
        "itself but must be told about Malayalam, Bengali, Assamese, Kannada, Gujarati, "
        "Punjabi and Odia. Tesseract needs the language data installed.",
    )
    pdf_check_pages: int = Field(
        default=2,
        ge=0,
        description="With OCR available, how many PDF pages with a text layer to check "
        "against OCR as a sample (pages whose text looks broken are always checked). The "
        "agreement becomes the document's extraction_confidence. 0 = only suspicious pages.",
    )
    tesseract_cmd: str | None = Field(
        default=None,
        description="Path to the tesseract executable if it is not on PATH or in the "
        "usual install folder.",
    )
