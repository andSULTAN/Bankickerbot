"""Runtime settings (.env) and tunable scoring config (YAML)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent

Mode = Literal["observe", "enforce"]


class Settings(BaseSettings):
    """Secrets and deployment settings, read from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    bot_token: str = ""
    tg_api_id: int = 0
    tg_api_hash: str = ""
    tg_session_path: str = "tgguard.session"

    database_url: str = "postgresql+asyncpg://tgguard:tgguard@localhost:5432/tgguard"

    admin_ids: list[int] = Field(default_factory=list)
    review_channel_id: int = 0

    channel_id: int = 0
    discussion_group_id: int = 0

    mode: Mode = "observe"
    scoring_config: str = "config/scoring.yaml"
    log_level: str = "INFO"

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _split_admin_ids(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [int(part) for part in re.split(r"[,\s]+", value.strip()) if part]
        return value

    @property
    def scoring_config_path(self) -> Path:
        path = Path(self.scoring_config)
        return path if path.is_absolute() else REPO_ROOT / path

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


# ---------------------------------------------------------------------------
# scoring.yaml
# ---------------------------------------------------------------------------


class Thresholds(BaseModel):
    ban: float = 0.85
    review: float = 0.50


class PhotolessRules(BaseModel):
    drop_weak_signals: bool = True
    max_score_without_strong: float = 0.49
    strong_signals: list[str] = Field(default_factory=lambda: ["bio_links", "name_pattern"])


class NsfwConfig(BaseModel):
    unsafe_classes: dict[str, float] = Field(default_factory=dict)
    min_detection_score: float = 0.35
    max_photos: int = 3


class BioConfig(BaseModel):
    url_patterns: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    match_value: float = 0.6
    extra_match_value: float = 0.2


class NameConfig(BaseModel):
    patterns: list[str] = Field(default_factory=list)
    emojis: list[str] = Field(default_factory=list)
    match_value: float = 0.7
    extra_match_value: float = 0.15


class CommentConfig(BaseModel):
    url_patterns: list[str] = Field(default_factory=list)
    link_value: float = 0.7
    template_value: float = 0.9
    fast_reply_seconds: int = 30


class CacheConfig(BaseModel):
    recheck_days: int = 30


class ActionsConfig(BaseModel):
    bans_interval_seconds: float = 1.5
    delete_comment_on_review: bool = False


class ScoringConfig(BaseModel):
    """Everything the scoring engine can be tuned with, loaded from YAML."""

    thresholds: Thresholds = Field(default_factory=Thresholds)
    weights: dict[str, float] = Field(default_factory=dict)
    weak_signals: list[str] = Field(default_factory=list)
    photoless: PhotolessRules = Field(default_factory=PhotolessRules)
    nsfw: NsfwConfig = Field(default_factory=NsfwConfig)
    bio: BioConfig = Field(default_factory=BioConfig)
    name: NameConfig = Field(default_factory=NameConfig)
    comment: CommentConfig = Field(default_factory=CommentConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    actions: ActionsConfig = Field(default_factory=ActionsConfig)

    # Bumped whenever scoring behaviour changes, stored with every check row.
    version: str = "1.0"

    @classmethod
    def load(cls, path: str | Path) -> ScoringConfig:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=4)
def _load_scoring(path_str: str) -> ScoringConfig:
    return ScoringConfig.load(path_str)


def get_scoring_config(path: str | Path | None = None) -> ScoringConfig:
    target = Path(path) if path else get_settings().scoring_config_path
    return _load_scoring(str(target))
