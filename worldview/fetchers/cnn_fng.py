"""CNN Fear & Greed Index.

CNN exposes the data behind their Fear & Greed page at a stable JSON endpoint:

    https://production.dataviz.cnn.io/index/fearandgreed/graphdata

The endpoint requires a real-looking User-Agent (CNN 401s plain Python clients).
The response shape — relevant slice — is roughly:

    {
        "fear_and_greed": { "score": 35.4, "rating": "fear", ... },
        "fear_and_greed_historical": {
            "data": [
                { "x": 1704067200000, "y": 33.7, "rating": "fear" },
                ...
            ]
        }
    }

We keep `fear_and_greed_historical.data` (full back-history). `x` is epoch
milliseconds UTC.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..models import Metric
from .base import Fetcher, FetchError

ENDPOINT = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

# CNN blocks the default `python-requests/...` UA. A modern Chrome string is
# all that's required — they don't fingerprint further.
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


class CNNFearGreedFetcher(Fetcher):
    """Pulls the daily F&G score history. `source_ref` on the metric is unused."""

    source_name = "cnn_fng"

    def __init__(
        self,
        session: requests.Session | None = None,
        endpoint: str = ENDPOINT,
        timeout_s: float = 15.0,
    ) -> None:
        self._session = session or requests.Session()
        self._endpoint = endpoint
        self._timeout = timeout_s

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((requests.RequestException,)),
        reraise=True,
    )
    def _get_json(self) -> dict:
        resp = self._session.get(
            self._endpoint, headers=_DEFAULT_HEADERS, timeout=self._timeout
        )
        resp.raise_for_status()
        return resp.json()

    def fetch(self, metric: Metric, start: date) -> pd.Series:
        try:
            payload = self._get_json()
        except Exception as e:  # noqa: BLE001
            raise FetchError(f"CNN F&G fetch failed: {e}") from e

        try:
            rows = payload["fear_and_greed_historical"]["data"]
        except (KeyError, TypeError) as e:
            raise FetchError(f"CNN F&G payload missing expected keys: {e}") from e

        if not rows:
            return pd.Series(dtype=float, name=metric.id)

        idx = pd.to_datetime([r["x"] for r in rows], unit="ms", utc=True)
        idx = idx.tz_convert(None).normalize()
        values = [float(r["y"]) for r in rows]

        s = pd.Series(values, index=idx, name=metric.id, dtype=float)
        s = s[s.index.date >= start].sort_index()
        # Drop any duplicate timestamps that might sneak in around DST boundaries.
        return s[~s.index.duplicated(keep="last")]
