"""Env-driven configuration for GullyTrader.

Env naming mirrors the KalshiTrader engine so a single .env can power both.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _kalshi_base_url(env: str) -> str:
    """Resolve Kalshi base URL from env mode."""
    mode = (env or "demo").lower()
    if mode == "prod":
        return "https://api.elections.kalshi.com/trade-api/v2"
    return "https://demo-api.kalshi.co/trade-api/v2"


@dataclass(frozen=True)
class Settings:
    # Kalshi (Kalshi-engine compatible env naming)
    kalshi_api_env: str = os.getenv("KALSHI_API_ENV", "demo")
    kalshi_key_id: str = os.getenv("KALSHI_KEY_ID", "")
    kalshi_private_key_path: str = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")

    # LLM — accept both Kalshi-style (per-agent *_LLM_*) and our shorter aliases
    llm_provider_default: str = os.getenv("LLM_PROVIDER", "openrouter")
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_default_model: str = os.getenv("OPENROUTER_MODEL", "qwen/qwen-2.5-72b-instruct")

    scanner_provider: str = os.getenv("SCANNER_LLM_PROVIDER", os.getenv("LLM_PROVIDER", "openrouter"))
    scanner_model: str = os.getenv("SCANNER_LLM_MODEL", os.getenv("OPENROUTER_MODEL", "qwen/qwen-2.5-72b-instruct"))
    research_provider: str = os.getenv("RESEARCH_LLM_PROVIDER", os.getenv("LLM_PROVIDER", "openrouter"))
    research_model: str = os.getenv("RESEARCH_LLM_MODEL", "deepseek/deepseek-chat-v3-0324")
    decision_provider: str = os.getenv("DECISION_LLM_PROVIDER", os.getenv("LLM_PROVIDER", "openrouter"))
    decision_model: str = os.getenv("DECISION_LLM_MODEL", os.getenv("OPENROUTER_MODEL", "qwen/qwen-2.5-72b-instruct"))
    exit_provider: str = os.getenv("EXIT_LLM_PROVIDER", os.getenv("LLM_PROVIDER", "openrouter"))
    exit_model: str = os.getenv("EXIT_LLM_MODEL", os.getenv("OPENROUTER_MODEL", "qwen/qwen-2.5-72b-instruct"))

    # Cricket feed
    cricket_feed_provider: str = os.getenv("CRICKET_FEED_PROVIDER", "stub")
    cricket_feed_api_key: str = os.getenv("CRICKET_FEED_API_KEY", "")

    # Engine
    db_path: Path = Path(os.getenv("GULLYTRADER_DB_PATH", "./gullytrader.db"))
    enable_orchestrator: bool = _bool("GULLYTRADER_ENABLE_ORCHESTRATOR", False)
    exit_mode: str = os.getenv("GULLYTRADER_EXIT_MODE", "shadow")
    sync_interval_seconds: int = _int("GULLYTRADER_SYNC_INTERVAL_SECONDS", 60)
    live_poll_interval_seconds: int = _int("GULLYTRADER_LIVE_POLL_INTERVAL_SECONDS", 5)
    agent_logs_max_age_days: int = _int("GULLYTRADER_AGENT_LOGS_MAX_AGE_DAYS", 7)

    # Filtering — parlay/multi-game spam patterns from Kalshi
    parlay_market_prefixes: tuple = (
        "KXMVECROSSCATEGORY",
        "KXMVESPORTSMULTIGAME",
    )

    ipl_event_prefix: str = os.getenv("GULLYTRADER_IPL_EVENT_PREFIX", "KXIPL")

    @property
    def kalshi_api_base(self) -> str:
        return _kalshi_base_url(self.kalshi_api_env)


settings = Settings()
