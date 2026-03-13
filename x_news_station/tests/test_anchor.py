"""Tests for the news_anchor module."""

from __future__ import annotations

import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from modules.news_anchor import NewsRewriter, ScriptLine, SimpleRewriter, get_rewriter
from modules.news_fetcher import TweetData


@pytest.fixture
def sample_tweet() -> TweetData:
    return TweetData(
        id="123",
        username="testuser",
        text="Test content with a link https://example.com and #hashtags",
        timestamp=datetime.now(),
    )


@pytest.fixture
def mock_ollama():
    ollama_mock = MagicMock()
    ollama_mock.list.return_value = ["llama3", "mistral"]
    with patch.dict(sys.modules, {"ollama": ollama_mock}):
        yield ollama_mock


class TestSimpleRewriter:
    def test_strips_urls_and_hashtags(self, sample_tweet: TweetData) -> None:
        result = SimpleRewriter().rewrite(sample_tweet)
        assert "https://example.com" not in result
        assert "#" not in result
        assert "hashtags" in result

    def test_does_not_use_breaking_news_prefix(self, sample_tweet: TweetData) -> None:
        result = SimpleRewriter().rewrite(sample_tweet)
        assert not result.lower().startswith("breaking news")
        assert "@testuser" in result

    def test_builds_two_host_filler_by_default(self) -> None:
        lines = SimpleRewriter().build_filler_segment(
            "AI industry rivalry",
            recent_stories=["A fresh update from @sama on deployment pace."],
        )
        assert len(lines) >= 2
        assert isinstance(lines[0], ScriptLine)
        assert lines[0].speaker == "anchor"
        assert any(line.speaker == "analyst" for line in lines)


class TestNewsRewriter:
    def test_uses_fallback_when_ollama_unavailable(self, sample_tweet: TweetData) -> None:
        with patch.object(NewsRewriter, "_check_ollama_available", return_value=False):
            result = NewsRewriter().rewrite(sample_tweet)
        assert "@testuser" in result
        assert not result.lower().startswith("breaking news")

    def test_caches_results(self, mock_ollama: MagicMock, sample_tweet: TweetData) -> None:
        mock_ollama.chat.return_value = {"message": {"content": "New this hour. @testuser says something happened."}}
        rewriter = NewsRewriter()
        result1 = rewriter.rewrite(sample_tweet)
        result2 = rewriter.rewrite(sample_tweet)
        assert mock_ollama.chat.call_count == 1
        assert result1 == result2

    def test_retries_then_falls_back(self, mock_ollama: MagicMock, sample_tweet: TweetData) -> None:
        mock_ollama.chat.side_effect = Exception("Ollama error")
        with patch("time.sleep"):
            result = NewsRewriter(max_retries=3, backoff_factor=0.1).rewrite(sample_tweet)
        assert mock_ollama.chat.call_count == 3
        assert "@testuser" in result

    def test_build_filler_segment_uses_llm_json(self, mock_ollama: MagicMock) -> None:
        mock_ollama.chat.return_value = {
            "message": {
                "content": (
                    '{"lines": ['
                    '{"speaker": "anchor", "text": "While the feeds reset, AI rivalry is still driving the pace."},'
                    '{"speaker": "analyst", "text": "It matters because the next product cycle can turn quickly."}'
                    "]}"""
                )
            }
        }
        lines = NewsRewriter().build_filler_segment("AI rivalry", ["Recent story"])
        assert [line.speaker for line in lines[:2]] == ["anchor", "analyst"]

    def test_build_filler_segment_falls_back_on_bad_payload(self, mock_ollama: MagicMock) -> None:
        mock_ollama.chat.return_value = {"message": {"content": "not json"}}
        lines = NewsRewriter().build_filler_segment("AI rivalry", ["Recent story"])
        assert len(lines) >= 2


def test_get_rewriter_returns_news_rewriter() -> None:
    with patch.object(NewsRewriter, "_check_ollama_available", return_value=False):
        assert isinstance(get_rewriter(), NewsRewriter)
