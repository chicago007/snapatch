from __future__ import annotations

import re
import requests
from bs4 import BeautifulSoup

DEFAULT_ARTICLE_TIMEOUT_SECONDS = 3.0


def extract_article_text(
    url: str,
    fallback: str = "",
    timeout_seconds: float = DEFAULT_ARTICLE_TIMEOUT_SECONDS,
) -> str:
    try:
        res = requests.get(
            url,
            timeout=timeout_seconds,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        candidates = []
        for selector in [
            "#dic_area",
            "#newsct_article",
            "article",
            "#articletxt",
            ".article_body",
            ".news_end",
        ]:
            node = soup.select_one(selector)
            if node:
                candidates.append(node.get_text(" ", strip=True))
        if not candidates:
            candidates.append(soup.get_text(" ", strip=True))
        text = max(candidates, key=len)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:4000] if text else fallback
    except Exception:
        return fallback
