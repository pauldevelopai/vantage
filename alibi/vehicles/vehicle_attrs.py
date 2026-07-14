"""
Vehicle Attribute Extraction

Extracts vehicle attributes: color (HSV-based), make/model (placeholder).
"""

import cv2
import numpy as np
from typing import Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class VehicleColor(str, Enum):
    """Vehicle color categories"""
    RED = "red"
    ORANGE = "orange"
    YELLOW = "yellow"
    GREEN = "green"
    BLUE = "blue"
    PURPLE = "purple"
    PINK = "pink"
    BROWN = "brown"
    BLACK = "black"
    GRAY = "gray"
    WHITE = "white"
    SILVER = "silver"
    UNKNOWN = "unknown"


@dataclass
class VehicleAttributes:
    """Extracted vehicle attributes"""
    color: str
    color_confidence: float
    make: str  # "unknown" until model is added
    model: str  # "unknown" until model is added
    make_model_confidence: float  # 0.0 until model is added


class VehicleAttributeExtractor:
    """
    Extracts vehicle attributes from crops.
    
    Color: HSV-based dominant color classification (functional)
    Make/Model: Placeholder interface (returns "unknown")
    """
    
    def __init__(self):
        """Initialize attribute extractor"""
        # HSV ranges for color detection
        self.color_ranges = {
            VehicleColor.RED: [
                # Red wraps around in HSV
                ([0, 50, 50], [10, 255, 255]),
                ([170, 50, 50], [180, 255, 255])
            ],
            VehicleColor.ORANGE: [
                ([11, 50, 50], [25, 255, 255])
            ],
            VehicleColor.YELLOW: [
                ([26, 50, 50], [35, 255, 255])
            ],
            VehicleColor.GREEN: [
                ([36, 50, 50], [85, 255, 255])
            ],
            VehicleColor.BLUE: [
                ([86, 50, 50], [125, 255, 255])
            ],
            VehicleColor.PURPLE: [
                ([126, 50, 50], [150, 255, 255])
            ],
            VehicleColor.PINK: [
                ([151, 50, 50], [169, 255, 255])
            ],
            # Neutral colors (low saturation)
            VehicleColor.BLACK: [
                ([0, 0, 0], [180, 255, 50])  # Low value
            ],
            VehicleColor.GRAY: [
                ([0, 0, 51], [180, 25, 200])  # Low saturation, mid value
            ],
            VehicleColor.WHITE: [
                ([0, 0, 201], [180, 25, 255])  # Low saturation, high value
            ],
            VehicleColor.SILVER: [
                ([0, 0, 150], [180, 25, 200])  # Similar to gray but brighter
            ],
        }
    
    def extract_attributes(self, vehicle_crop: np.ndarray) -> VehicleAttributes:
        """
        Extract attributes from vehicle crop.
        
        Args:
            vehicle_crop: Cropped vehicle image (BGR)
            
        Returns:
            VehicleAttributes with color and placeholders
        """
        # Extract color (functional)
        color, color_confidence = self._classify_color(vehicle_crop)
        
        # Placeholder make/model (to be implemented with model)
        make, model, make_model_confidence = self._classify_make_model(vehicle_crop)
        
        return VehicleAttributes(
            color=color,
            color_confidence=color_confidence,
            make=make,
            model=model,
            make_model_confidence=make_model_confidence
        )
    
    def _classify_color(self, vehicle_crop: np.ndarray) -> Tuple[str, float]:
        """
        Classify vehicle color using HSV dominant color.
        
        Args:
            vehicle_crop: Vehicle image (BGR)
            
        Returns:
            Tuple of (color_name, confidence)
        """
        if vehicle_crop.size == 0:
            return VehicleColor.UNKNOWN.value, 0.0

        # Sample the central body region only — the crop edges are mostly
        # background/road/sky, which would pollute the colour histogram. The
        # centre 60% is dominated by the vehicle body.
        h, w = vehicle_crop.shape[:2]
        y0, y1 = int(h * 0.25), int(h * 0.85)
        x0, x1 = int(w * 0.20), int(w * 0.80)
        body = vehicle_crop[y0:y1, x0:x1]
        if body.size == 0:
            body = vehicle_crop

        # Convert to HSV
        hsv = cv2.cvtColor(body, cv2.COLOR_BGR2HSV)
        
        # Calculate percentage of pixels matching each color
        color_scores = {}
        total_pixels = hsv.shape[0] * hsv.shape[1]
        
        for color, ranges in self.color_ranges.items():
            mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
            
            for (lower, upper) in ranges:
                lower_bound = np.array(lower)
                upper_bound = np.array(upper)
                color_mask = cv2.inRange(hsv, lower_bound, upper_bound)
                mask = cv2.bitwise_or(mask, color_mask)
            
            # Count matching pixels
            matching_pixels = np.count_nonzero(mask)
            score = matching_pixels / total_pixels if total_pixels > 0 else 0
            color_scores[color] = score
        
        # Get color with highest score
        if not color_scores:
            return VehicleColor.UNKNOWN.value, 0.0
        
        best_color = max(color_scores, key=color_scores.get)
        confidence = color_scores[best_color]
        
        # If confidence too low, return unknown
        if confidence < 0.1:
            return VehicleColor.UNKNOWN.value, 0.0
        
        return best_color.value, confidence
    
    def _classify_make_model(self, vehicle_crop: np.ndarray) -> Tuple[str, str, float]:
        """
        Classify vehicle make and model.
        
        PLACEHOLDER: Returns "unknown" until model is implemented.
        
        Args:
            vehicle_crop: Vehicle image (BGR)
            
        Returns:
            Tuple of (make, model, confidence)
        """
        # TODO: Implement with pretrained model
        # For now, return placeholder values
        return "unknown", "unknown", 0.0


def classify_color_simple(vehicle_crop: np.ndarray) -> str:
    """
    Simple convenience function for color classification.
    
    Args:
        vehicle_crop: Vehicle image
        
    Returns:
        Color name as string
    """
    extractor = VehicleAttributeExtractor()
    attrs = extractor.extract_attributes(vehicle_crop)
    return attrs.color
