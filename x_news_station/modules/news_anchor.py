"""Tweet rewriting utilities for broadcast-ready output."""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

import config
from modules.news_fetcher import TweetData

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r"https?://\S+|www\.\S+")
HASHTAG_PATTERN = re.compile(r"#(\w+)")
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

HEADLINE_OPENERS = [
    "This just in.",
    "A fresh item from the feed.",
    "New this hour.",
    "Here is a developing signal from the timeline.",
    "Another move we are watching tonight.",
]
HEADLINE_CONNECTORS = [
    "From",
    "On X,",
    "Posting moments ago,",
    "In a new update,",
    "On the latest post,",
]
RECAP_INTROS = [
    "Before we move on, here is a quick reset on the stories still leading our watchlist.",
    "Let us reset the board with the headlines still driving the conversation.",
    "Here is a fast recap of the updates still shaping tonight's feed.",
]
RECAP_OUTROS = [
    "That is the latest reset from the desk. We are still watching for the next move.",
    "Those are the stories still carrying weight right now. We will jump back in when the feed changes.",
    "That is where the board stands for the moment. More live posts as they land.",
]

STYLE_GUIDANCE = {
    "hybrid": (
        "Sound sharp and engaging, like a smart live tech-news show. Vary the openings and transitions, "
        "but stay factual and concise."
    ),
    "talk_radio": (
        "Sound lively and personality-forward, but still factual. Use brisk rhythm and varied intros without drifting "
        "into opinion or jokes."
    ),
    "straight_news": (
        "Sound polished and newsroom-direct. Keep the language restrained, serious, and efficient."
    ),
}


@dataclass(slots=True, frozen=True)
class ScriptLine:
    """Single spoken line in a scripted segment."""

    speaker: str
    text: str


class Rewriter(Protocol):
    """Interface for tweet rewriter implementations."""

    def rewrite(self, tweet: TweetData) -> str:
        """Rewrite a tweet to a broadcast script."""
        ...

    def build_filler_segment(
        self,
        topic: str,
        recent_stories: list[str] | None = None,
        idle_format: str | None = None,
    ) -> list[ScriptLine]:
        """Build a filler segment for quiet periods."""
        ...

    def build_rundown_segment(
        self,
        segment_type: str,
        primary_story: TweetData | None,
        supporting_stories: list[TweetData] | None = None,
        recent_stories: list[str] | None = None,
    ) -> list[ScriptLine]:
        """Build a planned editorial segment."""
        ...


def _deterministic_choice(options: list[str], seed: str) -> str:
    if not options:
        return ""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % len(options)
    return options[index]


def _strip_urls(text: str) -> str:
    return URL_PATTERN.sub("", text).strip()


def _strip_hashtags(text: str) -> str:
    return HASHTAG_PATTERN.sub(r"\1", text).strip()


def normalize_script_text(text: str) -> str:
    """Normalize raw text into compact spoken copy."""
    text = _strip_urls(text)
    text = _strip_hashtags(text)
    text = text.replace("\r", " ").replace("\n", " ")
    text = text.replace('"', "").replace("“", "").replace("”", "")
    text = re.sub(r"\b(anchor|analyst)\s*:\s*", "", text, flags=re.IGNORECASE)
    text = " ".join(text.split())
    return text.strip()


def _ensure_sentence_punctuation(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped
    if stripped.endswith((".", "!", "?")):
        return stripped
    return f"{stripped}."


def _trim_sentences(text: str, max_sentences: int = 2) -> str:
    sentences = [item.strip() for item in SENTENCE_SPLIT_PATTERN.split(text.strip()) if item.strip()]
    if not sentences:
        return text.strip()
    return " ".join(sentences[:max_sentences]).strip()


def _headline_style_prompt() -> str:
    return STYLE_GUIDANCE.get(config.SHOW_STYLE, STYLE_GUIDANCE["hybrid"])


def _headline_system_prompt() -> str:
    return (
        "You are writing copy for a local-first live radio news show. Rewrite raw social posts into a short "
        "broadcast-ready headline. Remove URLs and hashtags. Keep it factual. Mention the account naturally. "
        "Do not start every item the same way. Avoid the phrase 'Breaking news from'. "
        f"{_headline_style_prompt()} Return only the final script, in 1-2 sentences."
    )


def _editorial_system_prompt(segment_type: str) -> str:
    return (
        "You are writing a short factual segment for a local-first live radio news station. "
        "Use only the supplied social-post details and direct comparisons that can be inferred from them. "
        "Do not invent facts, timelines, reactions, or outside context. "
        "Return strict JSON with this shape: {\"lines\": [{\"speaker\": \"anchor\", \"text\": \"...\"}, "
        "{\"speaker\": \"analyst\", \"text\": \"...\"}]}. Use only speakers 'anchor' or 'analyst'. "
        "No markdown, no code fences, no bullet points, no URLs. Keep it broadcast-ready and concise. "
        f"Segment type: {segment_type}. {_headline_style_prompt()}"
    )


def _filler_system_prompt() -> str:
    return (
        "You are writing a short filler segment for a live radio station between headline checks. "
        "Return strict JSON with this shape: {\"lines\": [{\"speaker\": \"anchor\", \"text\": \"...\"}, "
        "{\"speaker\": \"analyst\", \"text\": \"...\"}]}. Use speaker values only 'anchor' or 'analyst'. "
        "No markdown, no code fences, no bullet points, no URLs, and no repeated 'breaking news' language. "
        f"{_headline_style_prompt()}"
    )


def _extract_json_payload(content: str) -> dict[str, Any]:
    stripped = FENCE_PATTERN.sub("", content.strip())
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in filler response")
    return json.loads(stripped[start : end + 1])


def _story_brief(tweet: TweetData) -> str:
    source_bits: list[str] = []
    if tweet.is_quote:
        source_bits.append("quote post")
    elif tweet.is_repost:
        source_bits.append("repost")
    elif tweet.is_reply:
        source_bits.append("reply")
    else:
        source_bits.append("original post")

    source_bits.append(f"likes={tweet.like_count}")
    source_bits.append(f"reposts={tweet.retweet_count}")
    source_bits.append(f"quotes={tweet.quote_count}")
    source_bits.append(f"replies={tweet.reply_count}")
    if tweet.quoted_username:
        source_bits.append(f"quotes=@{tweet.quoted_username}")
    if tweet.article_title:
        source_bits.append(f"article={tweet.article_title}")
    metadata = ", ".join(source_bits)
    extras: list[str] = []
    if tweet.quoted_text:
        extras.append(f"quoted post: {normalize_script_text(tweet.quoted_text)}")
    if tweet.article_title or tweet.article_description:
        article_bits = [bit for bit in [tweet.article_title, tweet.article_description] if bit]
        extras.append(f"linked article: {normalize_script_text(' '.join(article_bits))}")
    if tweet.link_urls():
        extras.append(f"links: {', '.join(tweet.link_urls()[:3])}")
    extra_text = f" | {' | '.join(extras)}" if extras else ""
    return f"@{tweet.username} ({metadata}): {normalize_script_text(tweet.text)}{extra_text}"


def _tweet_prompt_context(tweet: TweetData) -> str:
    lines = [
        f"Account: @{tweet.username}",
        f"Post type: {tweet.source_type}",
        f"Raw post: {tweet.text}",
    ]
    if tweet.quoted_text:
        quoted_source = f"@{tweet.quoted_username}" if tweet.quoted_username else "quoted account"
        lines.append(f"Quoted post from {quoted_source}: {tweet.quoted_text}")
    if tweet.article_title or tweet.article_description:
        article_summary = " | ".join(bit for bit in [tweet.article_title, tweet.article_description] if bit)
        lines.append(f"Attached article/card: {article_summary}")
    if tweet.article_url:
        lines.append(f"Attached article URL: {tweet.article_url}")
    elif tweet.link_urls():
        lines.append(f"Expanded links: {', '.join(tweet.link_urls()[:3])}")
    return "\n".join(lines)


class SimpleRewriter:
    """Regex-based fallback rewriter used when external providers are unavailable."""

    def __init__(self) -> None:
        """Initialize fallback instance."""
        logger.info("SimpleRewriter initialized in fallback mode")

    def rewrite(self, tweet: TweetData) -> str:
        """Generate a varied, deterministic headline rewrite."""
        text = normalize_script_text(tweet.text)
        context_bits: list[str] = []
        if tweet.quoted_text:
            quoted_name = f"@{tweet.quoted_username}" if tweet.quoted_username else "another account"
            context_bits.append(f"The post also quotes {quoted_name} saying {normalize_script_text(tweet.quoted_text)}")
        elif tweet.article_title:
            context_bits.append(f"The linked article points to {normalize_script_text(tweet.article_title)}")
        elif tweet.article_url:
            context_bits.append("The post links out to an attached article")

        if context_bits:
            text = f"{text}. {' '.join(context_bits)}".strip()
        if not text:
            text = "shared a brief update with little additional context"
        opener = _deterministic_choice(HEADLINE_OPENERS, f"{tweet.id}:headline:opener")
        connector = _deterministic_choice(HEADLINE_CONNECTORS, f"{tweet.id}:headline:connector")
        username = f"@{tweet.username}"

        templates = [
            f"{opener} {connector} {username}, {text}",
            f"{opener} {username} says {text}",
            f"{connector} {username}, {text}",
        ]
        result = _ensure_sentence_punctuation(
            _deterministic_choice(templates, f"{tweet.id}:headline:template")
        )
        logger.debug("SimpleRewriter output: %s", result[:160])
        return result

    @staticmethod
    def _recent_reference(recent_stories: list[str] | None) -> str:
        if not recent_stories:
            return "We have been tracking a steady mix of signals across the accounts on our board."
        snippet = _trim_sentences(normalize_script_text(recent_stories[0]), max_sentences=1)
        if not snippet:
            return "We have been tracking a steady mix of signals across the accounts on our board."
        return f"That follows another headline we have been watching: {snippet}"

    def build_filler_segment(
        self,
        topic: str,
        recent_stories: list[str] | None = None,
        idle_format: str | None = None,
    ) -> list[ScriptLine]:
        """Build fallback filler copy for quiet periods."""
        topic_text = normalize_script_text(topic) or "the next shift in the tech world"
        recent_reference = self._recent_reference(recent_stories)
        mode = idle_format or config.IDLE_FORMAT

        if mode == "music_first":
            return [
                ScriptLine(
                    "anchor",
                    _ensure_sentence_punctuation(
                        f"While the music carries us for a minute, one theme still worth tracking is {topic_text}"
                    ),
                )
            ]

        if mode == "solo_host":
            return [
                ScriptLine(
                    "anchor",
                    _ensure_sentence_punctuation(
                        f"While we wait for the next post, one thread worth watching is {topic_text}"
                    ),
                ),
                ScriptLine(
                    "anchor",
                    _ensure_sentence_punctuation(
                        f"{recent_reference} We will bring you the next account update the moment it lands"
                    ),
                ),
            ]

        return [
            ScriptLine(
                "anchor",
                _ensure_sentence_punctuation(
                    f"While the feeds reset, one thread worth tracking is {topic_text}"
                ),
            ),
            ScriptLine(
                "analyst",
                _ensure_sentence_punctuation(
                    f"It matters because {topic_text} keeps spilling into launches, competition, and the way these accounts frame the future"
                ),
            ),
            ScriptLine("anchor", _ensure_sentence_punctuation(recent_reference)),
            ScriptLine(
                "analyst",
                "The moment a fresh post lands, we will bring it straight back on air.",
            ),
        ]

    def build_rundown_segment(
        self,
        segment_type: str,
        primary_story: TweetData | None,
        supporting_stories: list[TweetData] | None = None,
        recent_stories: list[str] | None = None,
    ) -> list[ScriptLine]:
        """Build fallback editorial segments for the rundown planner."""
        supporting_stories = supporting_stories or []

        if segment_type == "music_break":
            return []

        if primary_story is None and supporting_stories:
            primary_story = supporting_stories[0]
        if primary_story is None:
            return self.build_filler_segment(
                "the next shift in the tech world",
                recent_stories=recent_stories,
                idle_format="two_host",
            )

        primary_headline = self.rewrite(primary_story)

        if segment_type == "fresh_headline":
            return [ScriptLine("anchor", primary_headline)]

        if segment_type == "quick_reset":
            stories = [primary_story, *supporting_stories][:3]
            lines = [
                ScriptLine(
                    "anchor",
                    "Let us reset the board with the items still carrying the most weight right now.",
                )
            ]
            for story in stories:
                lines.append(ScriptLine("anchor", self.rewrite(story)))
            lines.append(
                ScriptLine(
                    "analyst",
                    "That gives us the current shape of the feed while we wait for the next clear move.",
                )
            )
            return lines

        if segment_type == "compare_updates":
            secondary = supporting_stories[0] if supporting_stories else primary_story
            secondary_headline = self.rewrite(secondary)
            return [
                ScriptLine("anchor", primary_headline),
                ScriptLine(
                    "analyst",
                    _ensure_sentence_punctuation(
                        f"Set against that, another line on the board is {normalize_script_text(secondary_headline)}"
                    ),
                ),
                ScriptLine(
                    "anchor",
                    "Together they show where the pressure and momentum are building across the feed.",
                ),
            ]

        if segment_type == "why_it_matters":
            return [
                ScriptLine("anchor", primary_headline),
                ScriptLine(
                    "analyst",
                    _ensure_sentence_punctuation(
                        f"It matters because @{primary_story.username} is framing the story as {primary_story.source_type}, "
                        "and the engagement around it suggests the topic is still carrying attention"
                    ),
                ),
                ScriptLine(
                    "anchor",
                    "That is the angle we will keep on watch as the board updates.",
                ),
            ]

        return [
            ScriptLine(
                "anchor",
                _ensure_sentence_punctuation(
                    f"One thread still worth tracking on our watchlist is {normalize_script_text(primary_story.text)}"
                ),
            ),
            ScriptLine(
                "analyst",
                _ensure_sentence_punctuation(
                    "The value there is not just the post itself, but how it reframes the broader conversation we are following."
                ),
            ),
            ScriptLine(
                "anchor",
                _ensure_sentence_punctuation(self._recent_reference(recent_stories)),
            ),
        ]


class NewsRewriter:
    """Primary LLM-powered rewriter with retry and fallback handling."""

    def __init__(self, max_retries: int | None = None, backoff_factor: float | None = None) -> None:
        """Initialize a rewriter instance."""
        self.max_retries = max_retries if max_retries is not None else config.OLLAMA_MAX_RETRIES
        self.backoff_factor = (
            backoff_factor if backoff_factor is not None else config.OLLAMA_BACKOFF_FACTOR
        )
        self._cache: dict[str, str] = {}
        self._filler_cache: dict[str, list[ScriptLine]] = {}
        self._segment_cache: dict[str, list[ScriptLine]] = {}
        self._fallback: SimpleRewriter | None = None
        self._ollama_client: Any | None = None
        self._llm_provider = config.LLM_PROVIDER.strip().lower()

        if self._llm_provider == "simple":
            logger.info("NewsRewriter configured for SimpleRewriter provider")
            self._fallback = SimpleRewriter()
            self._use_llm = False
        elif self._llm_provider == "openai_compatible":
            if self._check_openai_compatible_available():
                logger.info(
                    "NewsRewriter initialized with openai_compatible model %s",
                    config.LLM_API_MODEL,
                )
                self._use_llm = True
            else:
                logger.warning(
                    "OpenAI-compatible provider unavailable at %s; using SimpleRewriter fallback",
                    config.LLM_API_BASE_URL,
                )
                self._fallback = SimpleRewriter()
                self._use_llm = False
        else:
            self._llm_provider = "ollama"
            if self._check_ollama_available():
                logger.info("NewsRewriter initialized with Ollama model %s", config.OLLAMA_MODEL)
                self._use_llm = True
            else:
                logger.warning("Ollama unavailable, using SimpleRewriter fallback")
                self._fallback = SimpleRewriter()
                self._use_llm = False

    def _get_fallback(self) -> SimpleRewriter:
        if self._fallback is None:
            self._fallback = SimpleRewriter()
        return self._fallback

    def _get_ollama_client(self) -> Any:
        """Return an Ollama client bound to configured host when supported."""
        if self._ollama_client is not None:
            return self._ollama_client

        ollama_module = importlib.import_module("ollama")
        module_dict = getattr(ollama_module, "__dict__", {})
        has_explicit_client = isinstance(module_dict, dict) and "Client" in module_dict
        if has_explicit_client:
            self._ollama_client = ollama_module.Client(host=config.OLLAMA_BASE_URL)
        else:
            self._ollama_client = ollama_module
        return self._ollama_client

    def _check_ollama_available(self) -> bool:
        """Probe Ollama reachability."""
        try:
            client = self._get_ollama_client()
            client.list()
            return True
        except Exception as exc:
            logger.debug("Ollama availability check failed: %s", exc)
            return False

    def _resolve_api_key(self) -> str:
        """Return API key from config or configured environment variable."""
        if config.LLM_API_KEY.strip():
            return config.LLM_API_KEY.strip()
        env_var = config.LLM_API_KEY_ENV_VAR.strip()
        if not env_var:
            return ""
        return os.environ.get(env_var, "").strip()

    def _check_openai_compatible_available(self) -> bool:
        """Probe OpenAI-compatible API reachability."""
        api_base = config.LLM_API_BASE_URL.rstrip("/")
        if not api_base:
            logger.debug("OpenAI-compatible API base URL is empty")
            return False

        models_url = f"{api_base}/models"
        headers = {"Content-Type": "application/json"}
        api_key = self._resolve_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        request = urllib_request.Request(models_url, headers=headers, method="GET")
        try:
            with urllib_request.urlopen(request, timeout=10) as response:
                return 200 <= getattr(response, "status", 200) < 300
        except Exception as exc:
            logger.debug("OpenAI-compatible availability check failed: %s", exc)
            return False

    def _call_ollama_with_retry(self, system_prompt: str, prompt: str) -> str:
        """Call Ollama with bounded retries and exponential backoff."""
        last_exception: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                client = self._get_ollama_client()
                response = client.chat(
                    model=config.OLLAMA_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                )
                content = response.get("message", {}).get("content", "")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("Ollama returned empty response content")
                return content.strip()
            except Exception as exc:
                last_exception = exc
                wait_time = self.backoff_factor * (2**attempt)
                logger.warning(
                    "Ollama call failed (%s/%s): %s",
                    attempt + 1,
                    self.max_retries,
                    exc,
                )
                if attempt < self.max_retries - 1:
                    time.sleep(wait_time)

        if last_exception is None:
            raise RuntimeError("Ollama call failed for unknown reason")
        raise last_exception

    def _call_openai_compatible_with_retry(self, system_prompt: str, prompt: str) -> str:
        """Call an OpenAI-compatible chat API with retry behavior."""
        last_exception: Exception | None = None
        api_base = config.LLM_API_BASE_URL.rstrip("/")
        api_key = self._resolve_api_key()
        endpoint = f"{api_base}/chat/completions"

        for attempt in range(self.max_retries):
            try:
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                payload = json.dumps(
                    {
                        "model": config.LLM_API_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt},
                        ],
                    }
                ).encode("utf-8")

                request = urllib_request.Request(endpoint, data=payload, headers=headers, method="POST")
                with urllib_request.urlopen(request, timeout=20) as response:
                    raw = response.read().decode("utf-8")
                decoded = json.loads(raw)
                choices = decoded.get("choices", [])
                if not choices:
                    raise ValueError("OpenAI-compatible API returned no choices")

                message = choices[0].get("message", {})
                content = message.get("content", "")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("OpenAI-compatible API returned empty content")
                return content.strip()

            except (urllib_error.URLError, urllib_error.HTTPError, json.JSONDecodeError, ValueError) as exc:
                last_exception = exc
                wait_time = self.backoff_factor * (2**attempt)
                logger.warning(
                    "OpenAI-compatible call failed (%s/%s): %s",
                    attempt + 1,
                    self.max_retries,
                    exc,
                )
                if attempt < self.max_retries - 1:
                    time.sleep(wait_time)
            except Exception as exc:
                last_exception = exc
                wait_time = self.backoff_factor * (2**attempt)
                logger.warning(
                    "OpenAI-compatible call failed (%s/%s): %s",
                    attempt + 1,
                    self.max_retries,
                    exc,
                )
                if attempt < self.max_retries - 1:
                    time.sleep(wait_time)

        if last_exception is None:
            raise RuntimeError("OpenAI-compatible call failed for unknown reason")
        raise last_exception

    def _call_llm(self, system_prompt: str, prompt: str) -> str:
        if self._llm_provider == "openai_compatible":
            return self._call_openai_compatible_with_retry(system_prompt, prompt)
        return self._call_ollama_with_retry(system_prompt, prompt)

    def _rewrite_with_fallback(self, tweet: TweetData) -> str:
        """Rewrite using local fallback and cache the result."""
        rewritten = self._get_fallback().rewrite(tweet)
        self._cache[tweet.id] = rewritten
        return rewritten

    def _post_process_headline(self, tweet: TweetData, content: str) -> str:
        normalized = _trim_sentences(normalize_script_text(content), max_sentences=2)
        if not normalized:
            return self._rewrite_with_fallback(tweet)
        if normalized.lower().startswith("breaking news"):
            return self._rewrite_with_fallback(tweet)
        normalized = _ensure_sentence_punctuation(normalized)
        return normalized

    def rewrite(self, tweet: TweetData) -> str:
        """Rewrite tweet to a concise radio bulletin."""
        cached = self._cache.get(tweet.id)
        if cached is not None:
            logger.debug("Rewriter cache hit for tweet %s", tweet.id)
            return cached

        if not self._use_llm:
            return self._rewrite_with_fallback(tweet)

        prompt = (
            "Rewrite this social post into a radio headline using only the supplied context.\n\n"
            f"{_tweet_prompt_context(tweet)}"
        )
        try:
            rewritten = self._call_llm(_headline_system_prompt(), prompt)
            rewritten = self._post_process_headline(tweet, rewritten)
            self._cache[tweet.id] = rewritten
            logger.debug("NewsRewriter output: %s", rewritten[:160])
            return rewritten
        except Exception as exc:
            provider_name = "OpenAI-compatible API" if self._llm_provider == "openai_compatible" else "Ollama"
            logger.error("%s failed after %s retries: %s", provider_name, self.max_retries, exc)
            logger.warning("Switching to SimpleRewriter for this tweet")
            return self._rewrite_with_fallback(tweet)

    def _parse_filler_lines(self, content: str) -> list[ScriptLine]:
        decoded = _extract_json_payload(content)
        raw_lines = decoded.get("lines", [])
        if not isinstance(raw_lines, list):
            raise ValueError("Filler payload missing lines list")

        lines: list[ScriptLine] = []
        for item in raw_lines:
            if not isinstance(item, dict):
                continue
            speaker = str(item.get("speaker", "")).strip().lower()
            text = _ensure_sentence_punctuation(normalize_script_text(str(item.get("text", ""))))
            if speaker not in {"anchor", "analyst"} or not text:
                continue
            lines.append(ScriptLine(speaker=speaker, text=text))

        if len(lines) < 2:
            raise ValueError("Filler response did not include enough usable lines")
        return lines[:4]

    def build_filler_segment(
        self,
        topic: str,
        recent_stories: list[str] | None = None,
        idle_format: str | None = None,
    ) -> list[ScriptLine]:
        """Build a filler segment for quiet periods."""
        mode = idle_format or config.IDLE_FORMAT
        cache_seed = json.dumps(
            {
                "topic": topic,
                "stories": recent_stories or [],
                "mode": mode,
                "style": config.SHOW_STYLE,
            },
            sort_keys=True,
        )
        cache_key = hashlib.sha256(cache_seed.encode("utf-8")).hexdigest()
        cached = self._filler_cache.get(cache_key)
        if cached is not None:
            return cached

        if not self._use_llm:
            lines = self._get_fallback().build_filler_segment(topic, recent_stories, mode)
            self._filler_cache[cache_key] = lines
            return lines

        recent_block = "\n".join(f"- {item}" for item in (recent_stories or [])[:2]) or "- No recent stories yet"
        prompt = (
            f"Topic: {topic}\n"
            f"Idle format: {mode}\n"
            "Recent stories we have already covered:\n"
            f"{recent_block}\n\n"
            "Write a short between-headlines segment."
        )
        try:
            content = self._call_llm(_filler_system_prompt(), prompt)
            lines = self._parse_filler_lines(content)
        except Exception as exc:
            logger.warning("Filler generation failed, using fallback copy: %s", exc)
            lines = self._get_fallback().build_filler_segment(topic, recent_stories, mode)

        self._filler_cache[cache_key] = lines
        return lines

    def build_rundown_segment(
        self,
        segment_type: str,
        primary_story: TweetData | None,
        supporting_stories: list[TweetData] | None = None,
        recent_stories: list[str] | None = None,
    ) -> list[ScriptLine]:
        """Build a short editorial segment for the rundown planner."""
        supporting_stories = supporting_stories or []
        if segment_type == "music_break":
            return []

        cache_seed = json.dumps(
            {
                "segment_type": segment_type,
                "primary_story": primary_story.id if primary_story else "",
                "supporting_stories": [story.id for story in supporting_stories],
                "recent_stories": recent_stories or [],
                "style": config.SHOW_STYLE,
            },
            sort_keys=True,
        )
        cache_key = hashlib.sha256(cache_seed.encode("utf-8")).hexdigest()
        cached = self._segment_cache.get(cache_key)
        if cached is not None:
            return cached

        if not self._use_llm:
            lines = self._get_fallback().build_rundown_segment(
                segment_type,
                primary_story,
                supporting_stories,
                recent_stories,
            )
            self._segment_cache[cache_key] = lines
            return lines

        story_lines = []
        if primary_story is not None:
            story_lines.append(f"Primary story: {_story_brief(primary_story)}")
        if supporting_stories:
            story_lines.extend(
                f"Supporting story {index}: {_story_brief(story)}"
                for index, story in enumerate(supporting_stories, start=1)
            )
        if recent_stories:
            story_lines.append("Recent items already aired:")
            story_lines.extend(f"- {normalize_script_text(item)}" for item in recent_stories[:3])

        prompt = "\n".join(
            [
                f"Segment type: {segment_type}",
                *story_lines,
                "",
                "Write the on-air script now.",
            ]
        )

        try:
            content = self._call_llm(_editorial_system_prompt(segment_type), prompt)
            lines = self._parse_filler_lines(content)
        except Exception as exc:
            logger.warning("Editorial segment generation failed, using fallback copy: %s", exc)
            lines = self._get_fallback().build_rundown_segment(
                segment_type,
                primary_story,
                supporting_stories,
                recent_stories,
            )

        self._segment_cache[cache_key] = lines
        return lines

    def get_cache_stats(self) -> dict[str, int]:
        """Return cache metadata."""
        return {
            "cached_items": len(self._cache),
            "cached_filler_segments": len(self._filler_cache),
            "cached_rundown_segments": len(self._segment_cache),
        }


def get_rewriter() -> NewsRewriter:
    """Return default rewriter instance."""
    return NewsRewriter()
