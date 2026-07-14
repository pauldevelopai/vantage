"""
Plate-Vehicle Mismatch Detection

Joins plate readings with vehicle attributes and compares against registry.
"""

from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass


@dataclass
class MismatchResult:
    """Result of mismatch check"""
    is_mismatch: bool
    mismatch_score: float  # 0.0-1.0
    expected_make: str
    expected_model: str
    observed_make: str
    observed_model: str
    plate_text: str
    explanation: str
    expected_color: str = ""
    observed_color: str = ""


def compute_color_mismatch(
    expected_color: str,
    observed_color: str,
    observed_color_confidence: float,
) -> Tuple[float, str]:
    """
    Compare the registered colour against the observed colour.

    Colour is the most reliably classified vehicle attribute, and a colour
    change is exactly the SMARTGUARD example (plate registered to a black car,
    camera sees a white one). Returns (score, explanation).
    """
    exp = (expected_color or "").lower().strip()
    obs = (observed_color or "").lower().strip()
    if not exp or exp == "unknown" or not obs or obs == "unknown":
        return 0.0, "Cannot determine colour mismatch: colour unknown"
    if exp == obs:
        return 0.0, "No colour mismatch"
    # Treat near-neutral pairs as weak signals (silver/gray/white are easily
    # confused under different lighting); distinct hues are a strong signal.
    neutrals = {"gray", "silver", "white", "black"}
    weak = exp in neutrals and obs in neutrals
    base = 0.5 if weak else 0.85
    score = base * float(observed_color_confidence)
    return score, f"Colour mismatch: registered {exp}, observed {obs}"


def normalize_make_model(make: str, model: str) -> Tuple[str, str]:
    """
    Normalize make/model for comparison.
    
    Args:
        make: Make string
        model: Model string
        
    Returns:
        Tuple of (normalized_make, normalized_model)
    """
    # Convert to lowercase and strip whitespace
    make_norm = make.lower().strip()
    model_norm = model.lower().strip()
    
    # Handle common variations
    make_aliases = {
        "vw": "volkswagen",
        "bmw": "bmw",
        "benz": "mercedes-benz",
        "mercedes": "mercedes-benz",
    }
    
    if make_norm in make_aliases:
        make_norm = make_aliases[make_norm]
    
    return make_norm, model_norm


def compute_mismatch_score(
    expected_make: str,
    expected_model: str,
    observed_make: str,
    observed_model: str,
    observed_make_confidence: float,
    observed_model_confidence: float
) -> Tuple[float, str]:
    """
    Compute mismatch score and explanation.
    
    Args:
        expected_make: Expected make from registry
        expected_model: Expected model from registry
        observed_make: Observed make from video
        observed_model: Observed model from video
        observed_make_confidence: Confidence of make classification
        observed_model_confidence: Confidence of model classification
        
    Returns:
        Tuple of (mismatch_score, explanation)
    """
    # Normalize for comparison
    exp_make, exp_model = normalize_make_model(expected_make, expected_model)
    obs_make, obs_model = normalize_make_model(observed_make, observed_model)
    
    # Check if either observed is unknown
    if obs_make == "unknown" or obs_model == "unknown":
        return 0.0, "Cannot determine mismatch: observed make/model unknown"
    
    # Check if either expected is unknown
    if exp_make == "unknown" or exp_model == "unknown":
        return 0.0, "Cannot determine mismatch: expected make/model unknown"
    
    # Check for exact match
    if exp_make == obs_make and exp_model == obs_model:
        return 0.0, "No mismatch: exact match"
    
    # Check for partial match (make matches, model differs)
    if exp_make == obs_make and exp_model != obs_model:
        # Partial mismatch - model only
        score = 0.6 * min(observed_make_confidence, observed_model_confidence)
        return score, f"Partial mismatch: expected {exp_model}, observed {obs_model}"
    
    # Full mismatch - both make and model differ
    if exp_make != obs_make:
        # Full mismatch
        score = 0.9 * min(observed_make_confidence, observed_model_confidence)
        return score, f"Full mismatch: expected {exp_make} {exp_model}, observed {obs_make} {obs_model}"
    
    # Shouldn't reach here
    return 0.0, "Unknown"


def check_mismatch(
    plate_text: str,
    expected_make: str,
    expected_model: str,
    observed_make: str,
    observed_model: str,
    observed_make_confidence: float,
    observed_model_confidence: float,
    min_confidence: float = 0.5,
    min_score: float = 0.3,
    expected_color: str = "",
    observed_color: str = "",
    observed_color_confidence: float = 0.0,
    color_min_confidence: float = 0.35,
) -> Optional[MismatchResult]:
    """
    Check for plate-vehicle mismatch.
    
    Args:
        plate_text: License plate number
        expected_make: Expected make from registry
        expected_model: Expected model from registry
        observed_make: Observed make from video
        observed_model: Observed model from video
        observed_make_confidence: Confidence of make classification
        observed_model_confidence: Confidence of model classification
        min_confidence: Minimum confidence threshold
        min_score: Minimum mismatch score threshold
        
    Returns:
        MismatchResult if mismatch detected, None otherwise
    """
    # Make/model mismatch — only when the observed make/model is confident
    # enough (the classifier is optional, so this may be skipped).
    mm_score, mm_expl = 0.0, ""
    if (observed_make_confidence >= min_confidence
            and observed_model_confidence >= min_confidence):
        mm_score, mm_expl = compute_mismatch_score(
            expected_make=expected_make,
            expected_model=expected_model,
            observed_make=observed_make,
            observed_model=observed_model,
            observed_make_confidence=observed_make_confidence,
            observed_model_confidence=observed_model_confidence,
        )

    # Colour mismatch — reliable and independent of make/model.
    col_score, col_expl = 0.0, ""
    if observed_color_confidence >= color_min_confidence:
        col_score, col_expl = compute_color_mismatch(
            expected_color, observed_color, observed_color_confidence)

    # Combine — strongest signal wins; explanation names whatever fired.
    mismatch_score = max(mm_score, col_score)
    if mismatch_score < min_score:
        return None

    parts = [p for p in (mm_expl, col_expl) if p and "No " not in p and "Cannot" not in p]
    explanation = "; ".join(parts) if parts else mm_expl or col_expl

    return MismatchResult(
        is_mismatch=True,
        mismatch_score=mismatch_score,
        expected_make=expected_make,
        expected_model=expected_model,
        observed_make=observed_make,
        observed_model=observed_model,
        plate_text=plate_text,
        explanation=explanation,
        expected_color=expected_color,
        observed_color=observed_color,
    )
