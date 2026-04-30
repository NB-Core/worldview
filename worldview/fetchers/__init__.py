"""Source-specific fetchers. One module per data provider."""

from .base import Fetcher, FetchError
from .registry import FetcherRegistry, default_registry

__all__ = ["Fetcher", "FetchError", "FetcherRegistry", "default_registry"]
