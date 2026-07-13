"""
Vantage Configuration

Safety thresholds and system configuration.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class VantageConfig:
    """Configuration for Vantage incident management"""
    
    # Safety thresholds
    min_confidence_for_notify: float = 0.75
    min_confidence_for_action: float = 0.80
    high_severity_threshold: int = 4  # >= this requires human approval
    
    # LLM settings (optional)
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    openai_max_tokens: int = 500
    openai_temperature: float = 0.3
    
    # Logging
    log_dir: str = "alibi/data"
    
    # Validation
    require_evidence_for_notify: bool = True
    require_evidence_for_dispatch: bool = True
    
    @classmethod
    def from_env(cls) -> "VantageConfig":
        """Create config from environment variables"""
        return cls(
            min_confidence_for_notify=float(
                os.getenv("ALIBI_MIN_CONFIDENCE_NOTIFY", "0.75")
            ),
            min_confidence_for_action=float(
                os.getenv("ALIBI_MIN_CONFIDENCE_ACTION", "0.80")
            ),
            high_severity_threshold=int(
                os.getenv("ALIBI_HIGH_SEVERITY_THRESHOLD", "4")
            ),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("ALIBI_OPENAI_MODEL", "gpt-4o-mini"),
            log_dir=os.getenv("ALIBI_LOG_DIR", "alibi/data"),
        )


# Global default config
DEFAULT_CONFIG = VantageConfig.from_env()
