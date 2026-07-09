"""Riot region model: platform routes (euw1, na1, …) → regional clusters
(europe, americas, asia, sea).

Platform routes serve Summoner-V4 / League-V4 / Champion-Mastery-V4; the regional
cluster serves Account-V1 and Match-V5. The public search lets the user pick a
platform; the backend maps it to the right cluster per call.
"""
from __future__ import annotations

# platform (lowercased) → regional cluster
PLATFORM_TO_CLUSTER = {
    "euw1": "europe", "eun1": "europe", "tr1": "europe", "ru": "europe",
    "na1": "americas", "br1": "americas", "la1": "americas", "la2": "americas",
    "kr": "asia", "jp1": "asia",
    "oc1": "sea", "ph2": "sea", "sg2": "sea", "th2": "sea", "tw2": "sea", "vn2": "sea",
}

# search-menu options, in display order: (platform code, label)
PLATFORM_CHOICES = [
    ("euw1", "EUW"), ("eun1", "EUNE"), ("na1", "NA"), ("kr", "KR"),
    ("br1", "BR"), ("jp1", "JP"), ("oc1", "OCE"), ("la1", "LAN"),
    ("la2", "LAS"), ("tr1", "TR"), ("ru", "RU"), ("vn2", "VN"),
]

DEFAULT_PLATFORM = "euw1"
DEFAULT_CLUSTER = "europe"


def is_valid(platform: str | None) -> bool:
    return bool(platform) and platform.lower() in PLATFORM_TO_CLUSTER


def normalize(platform: str | None) -> str:
    """Lowercased platform if recognised, else the default (euw1)."""
    p = (platform or "").lower()
    return p if p in PLATFORM_TO_CLUSTER else DEFAULT_PLATFORM


def cluster_for(platform: str | None) -> str:
    """Regional cluster for a platform (Account-V1 / Match-V5 routing)."""
    return PLATFORM_TO_CLUSTER.get((platform or "").lower(), DEFAULT_CLUSTER)
