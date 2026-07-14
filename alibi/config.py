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
    # Cloud tier: Anthropic (Claude) is preferred; OpenAI remains an optional
    # fallback. Local Ollama is always tried first for data sovereignty.
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-opus-4-8"        # text (alerts, reports)
    anthropic_vision_model: str = "claude-opus-4-8"  # scene analysis
    anthropic_max_tokens: int = 500

    # OpenAI (optional fallback only)
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
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            anthropic_model=os.getenv("ANTHROPIC_TEXT_MODEL", "claude-opus-4-8"),
            anthropic_vision_model=os.getenv(
                "ANTHROPIC_VISION_MODEL", "claude-opus-4-8"
            ),
            anthropic_max_tokens=int(os.getenv("ANTHROPIC_MAX_TOKENS", "500")),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("ALIBI_OPENAI_MODEL", "gpt-4o-mini"),
            log_dir=os.getenv("ALIBI_LOG_DIR", "alibi/data"),
        )


# Global default config
DEFAULT_CONFIG = VantageConfig.from_env()
