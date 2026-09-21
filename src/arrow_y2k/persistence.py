"""Legacy map API compatibility; all codecs and file writes live in storage."""

from .storage import load_map, save_map

__all__ = ["load_map", "save_map"]
