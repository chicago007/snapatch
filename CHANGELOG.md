# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
where practical.

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
