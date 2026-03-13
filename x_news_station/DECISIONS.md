# Architectural Decisions Log

> This file documents all technical decisions made during the development of X-News-Station.
> Date format: ISO 8601

---

## 2026-03-03: Project Initiation

### Decision: Project Structure
**Context**: Need a clean, modular structure that separates concerns and supports testing.
**Decision**: Use a flat module structure under `modules/` with corresponding tests under `tests/`.
**Rationale**: 
- Simple to understand and navigate
- pytest can easily discover tests
- Avoids circular import issues

---

### Decision: Configuration Management
**Context**: All settings must be user-configurable without code changes.
**Decision**: Single `config.py` file with constants. Imported by modules that need them.
**Rationale**:
- Centralized configuration is easy to document
- No need for complex config file parsing
- Type hints can be used for validation

---

### Decision: Mock Mode for Testing
**Context**: Twitter API requires credentials and has rate limits. Need to test without hitting real API.
**Decision**: Implement `MockTwitterMonitor` with deterministic fake data. Controlled by `USE_MOCK_TWITTER` config.
**Rationale**:
- Tests run quickly and reliably
- No network dependencies for CI/CD
- Can demo the app without Twitter credentials

---

### Decision: Audio Caching Strategy
**Context**: TTS generation is slow and expensive. Same text will be broadcast multiple times.
**Decision**: SHA256 hash of (text + voice_id) as cache key. Store in `cache/` directory.
**Rationale**:
- Deterministic cache keys
- Simple file-based storage
- 200 file limit prevents unbounded growth

---

### Decision: Fallback Strategy for LLM
**Context**: Ollama may not be installed or running when the app starts.
**Decision**: Check Ollama reachability on init. Fall back to `SimpleRewriter` if unavailable.
**Rationale**:
- App remains functional without LLM
- Clear warning logged when using fallback
- SimpleRewriter provides acceptable quality for basic use

---

### Decision: TTS Fallback Chain
**Context**: kokoro-onnx requires model files and ONNX runtime. May not be available.
**Decision**: Primary = kokoro-onnx, Fallback = pyttsx3 (system TTS).
**Rationale**:
- kokoro provides high quality when available
- pyttsx3 works on any system with no model files
- Loud warning when using fallback to encourage proper setup

---

### Decision: State Machine for Radio Loop
**Context**: Radio station has distinct modes: idle, checking, broadcasting, recapping.
**Decision**: Explicit State enum and RadioStation class that transitions between states.
**Rationale**:
- Clear, testable behavior
- Easy to add logging/metrics per state
- Prevents race conditions in audio handling

---

### Decision: Music Ducking Implementation
**Context**: Music must fade down when speaking, fade up after.
**Decision**: Background thread with smooth volume ramp over configurable duration.
**Rationale**:
- Non-blocking allows other operations to continue
- Smooth fade sounds professional
- Configurable duration adapts to different music types

---

### Decision: Error Handling Philosophy
**Context**: This is a long-running service that must stay up through transient failures.
**Decision**: "Log and continue" for all non-fatal errors. Never crash the main loop.
**Rationale**:
- Twitter API errors are temporary
- Network issues resolve themselves
- Better to skip a broadcast than kill the station

---

## Future Decisions (To Be Documented)

- Database vs JSON for story_log
- Web interface for configuration
- Multiple voice support per account
- Tweet filtering/blacklist
