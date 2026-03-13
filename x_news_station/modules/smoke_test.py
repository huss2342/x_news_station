"""Bounded functional smoke-test helpers for the station pipeline."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from modules.audio_studio import VoiceGenerator
from modules.healthcheck import HealthCheckResult, health_check_failed, run_health_checks
from modules.news_anchor import SimpleRewriter
from modules.news_fetcher import TweetData
from modules.runtime_settings import RuntimeSettings, apply_runtime_settings, load_runtime_settings


def _role_voice(settings: RuntimeSettings, speaker: str) -> str:
    return settings.analyst_voice_id if speaker == "analyst" else settings.anchor_voice_id


def _run_headline_pipeline(settings: RuntimeSettings) -> HealthCheckResult:
    tweet = TweetData(
        id="smoke-headline",
        username="station_smoke",
        text=(
            "We are testing whether the station can turn a raw social post into a clean live headline "
            "without repeating the same old intro every time."
        ),
        timestamp=datetime.now(),
    )

    try:
        rewriter = SimpleRewriter()
        voice_generator = VoiceGenerator()
        headline = rewriter.rewrite(tweet)
        if not headline.strip():
            raise ValueError("rewriter returned empty headline text")
        audio_path = voice_generator.generate(headline, settings.anchor_voice_id)
    except Exception as exc:
        return HealthCheckResult("Headline Pipeline", "fail", f"Headline generation failed: {exc}")

    return HealthCheckResult(
        "Headline Pipeline",
        "pass",
        f"Generated spoken headline sample at {audio_path.name}",
    )


def _run_filler_pipeline(settings: RuntimeSettings) -> HealthCheckResult:
    topic = settings.filler_topics[0] if settings.filler_topics else "market shifts in AI"
    recent_stories = [
        "A fresh update from @sama on model deployment pace.",
        "A follow-up post from @karpathy on training data quality.",
    ]

    try:
        rewriter = SimpleRewriter()
        voice_generator = VoiceGenerator()
        lines = rewriter.build_filler_segment(topic, recent_stories=recent_stories, idle_format=settings.idle_format)
        if settings.idle_format == "two_host" and len(lines) < 2:
            raise ValueError("two-host filler returned fewer than two lines")
        synthesized = 0
        for line in lines[:2]:
            voice_generator.generate(line.text, _role_voice(settings, line.speaker))
            synthesized += 1
        if synthesized == 0:
            raise ValueError("no filler lines were synthesized")
    except Exception as exc:
        return HealthCheckResult("Filler Pipeline", "fail", f"Filler generation failed: {exc}")

    return HealthCheckResult(
        "Filler Pipeline",
        "pass",
        f"Generated {min(len(lines), 2)} spoken filler line(s) for idle mode '{settings.idle_format}'",
    )


def run_smoke_test(settings: RuntimeSettings) -> list[HealthCheckResult]:
    """Run a bounded functional pass through health and content generation."""
    apply_runtime_settings(settings)
    results = list(run_health_checks(settings))
    results.append(_run_headline_pipeline(settings))
    results.append(_run_filler_pipeline(settings))
    return results


def smoke_test_failed(results: list[HealthCheckResult]) -> bool:
    """Return True when the smoke test should be considered failed."""
    return health_check_failed(results)


def run_smoke_test_from_path(settings_path: Any) -> tuple[RuntimeSettings, list[str], list[HealthCheckResult]]:
    """Load settings and run smoke test in one step."""
    settings, notes = load_runtime_settings(Path(settings_path))
    return settings, notes, run_smoke_test(settings)
