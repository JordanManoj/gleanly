"""Compliance metadata: robots, TDMRep, ai.txt, noai, license detection, PII flags."""

from gleanly.compliance.assess import assess, detect_noai, license_conditions
from gleanly.compliance.license import detect_license, is_permissive, license_from_url
from gleanly.compliance.pii import detect_pii

__all__ = [
    "assess",
    "detect_license",
    "detect_noai",
    "detect_pii",
    "is_permissive",
    "license_conditions",
    "license_from_url",
]
