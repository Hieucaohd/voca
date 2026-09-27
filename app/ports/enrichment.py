"""Vocabulary enrichment port (dictionary / LLM lookup).

Words captured from external apps may arrive without a meaning; they are marked
``enrichment_status="pending"``. A future provider (e.g. an LLM) implements
:class:`EnrichmentProvider` to fill phonetic, senses and examples.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class EnrichedSense:
    part_of_speech: str | None = None
    definition: str | None = None
    translation: str | None = None
    examples: list[tuple[str, str | None]] = field(default_factory=list)


@dataclass
class Enrichment:
    phonetic: str | None = None
    senses: list[EnrichedSense] = field(default_factory=list)


class EnrichmentProvider(Protocol):
    def enrich(self, word: str, language: str, translate_to: str, context: str | None = None) -> Enrichment | None: ...


class NullEnrichmentProvider:
    def enrich(self, word: str, language: str, translate_to: str, context: str | None = None) -> Enrichment | None:
        return None
