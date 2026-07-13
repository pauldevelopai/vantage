"""
Vantage Watchlist System

Face detection, embedding, and matching against City Police wanted list.
ALWAYS requires human verification. NEVER claims identity.
"""

from alibi.watchlist.watchlist_store import WatchlistStore, WatchlistEntry
from alibi.watchlist.face_detect import FaceDetector
from alibi.watchlist.face_embed import FaceEmbedder
from alibi.watchlist.face_match import FaceMatcher

__all__ = [
    'WatchlistStore',
    'WatchlistEntry',
    'FaceDetector',
    'FaceEmbedder',
    'FaceMatcher',
]
