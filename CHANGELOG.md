# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
where practical.

## [1.01] - 2026-07-07

Patch release: breaker domestic market accuracy and diver JSON reliability.

### Added

- breaker Naver Finance realtime API for KOSPI/KOSDAQ (`engines/breaker/market_data.py`)
- breaker post-processing to inject verified quotes into the index summary table
- diver JSON parse helpers and retry compaction hints (`engines/diver/gemini_analyzer.py`)
- Tests: `test_apply_verified_quotes_to_report_patches_index_table`, `tests/test_diver_gemini_analyzer.py`

### Changed

- breaker domestic index chain: Naver Finance → pykrx → Yahoo Finance
- diver LLM input preview capped at 500 chars; max output tokens raised (16k → 32k on retry)

### Fixed

- breaker Korean index values ignored or stale when LLM overrode `verified_market_data`
- diver intermittent `JSONDecodeError` from truncated Gemini structured output

[1.01]: https://github.com/chicago007/snapatch/releases/tag/v1.01

## [1.00] - 2026-07-07

First stable release of the integrated snapatch platform.

### Added

- Unified Hub + Engines architecture (breaker · diver · dejavu · match)
- Streamlit web dashboard (`hub/ui/maingate.py`) and terminal CLI (`hub/cli/*`)
- breaker verified market data (`engines/breaker/market_data.py`)
  - Domestic indices: pykrx (with KRX login) → Yahoo Finance fallback
  - Overseas indices, FX, commodities: Yahoo Finance
- README restructure for open-source presentation
- `docs/` documentation (architecture, development notes, roadmap)
- Author info and capstone mapping in README
- Web UI version badge

### Changed

- breaker default model unified to `gemini-2.5-flash` (fast and accurate modes)
- Release notes consolidated into this `CHANGELOG.md` (replacing standalone release notes)

### Fixed

- breaker index hallucination mitigated via injected market data
- breaker Streamlit output truncation and fast-mode blank screen
- breaker mode label tilde strikethrough rendering

[1.00]: https://github.com/chicago007/snapatch/releases/tag/v1.00
