"""Style profile models."""

from typing import Dict, List

from pydantic import BaseModel, Field


class BannedPhrase(BaseModel):
    phrase: str
    replacement_hint: str = ""


class BannedWord(BaseModel):
    word: str
    replacement_hint: str = ""


class BannedStructure(BaseModel):
    pattern: str
    rewrite_hint: str = ""


class IconicScene(BaseModel):
    type: str
    examples: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


class StylePositiveFeatures(BaseModel):
    sentence_patterns: List[str] = Field(default_factory=list)
    preferred_vocabulary: List[str] = Field(default_factory=list)
    frequency_ratio: float = 0.15
    rhythm: Dict[str, float] = Field(default_factory=dict)
    iconic_scenes: List[IconicScene] = Field(default_factory=list)


class StyleQualityMetrics(BaseModel):
    directness: int = 0
    rhythm: int = 0
    imagery: int = 0
    characterization: int = 0
    ai_artifact_control: int = 0


class StyleProfile(BaseModel):
    base: Dict[str, str] = Field(default_factory=dict)
    positive_features: StylePositiveFeatures = Field(
        default_factory=StylePositiveFeatures
    )
    banned_phrases: List[BannedPhrase] = Field(default_factory=list)
    banned_words: List[BannedWord] = Field(default_factory=list)
    banned_structures: List[BannedStructure] = Field(default_factory=list)
    quality_metrics: StyleQualityMetrics = Field(default_factory=StyleQualityMetrics)
