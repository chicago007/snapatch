# Architecture

Snapatch는 **Hub(통합 계층)** 와 **Engines(분석 엔진)** 로 나뉩니다.

## Layer overview

```text
┌─────────────────────────────────────────┐
│  Entry points                           │
│  run.py · python -m hub · streamlit run │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  Hub                                    │
│  launcher.py   — UI/CLI 선택 메뉴       │
│  bootstrap.py  — sys.path + .env        │
│  ui/maingate.py — Streamlit 대시보드    │
│  cli/*.py      — 터미널 래퍼            │
│  features/*.py — Streamlit 어댑터       │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  Engines                                │
│  breaker/  Gemini 시황 + market_data    │
│  diver/    Naver 뉴스 + Gemini pipeline │
│  dejavu/   pykrx + DTW 유사 패턴        │
│  match/    SAX + FastDTW 유사 종목      │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  outputs/  (gitignore)                  │
└─────────────────────────────────────────┘
```

## Design principles

1. **Engines are standalone** — 각 엔진은 `python -m engines.<name>` 또는 `hub.cli.<name>`으로 단독 실행 가능
2. **Hub is thin** — UI/CLI는 engines를 import하는 어댑터만 담당
3. **Optional credentials** — 기능별로 필요한 API 키만 설정하면 해당 기능만 사용 가능
4. **Shared bootstrap** — `hub.bootstrap.init()`이 프로젝트 루트 경로와 `.env`를 한 번만 로드

## breaker data flow

```text
market_data.py (pykrx → Yahoo fallback)
        │
        ▼
verified_market_data block in prompt
        │
        ▼
Gemini API (+ optional Google Search in accurate mode)
        │
        ▼
outputs/breaker/*.md
```

## match pipeline

```text
tickers.csv / uni.csv
        │
        ▼
Stage 1: SAX + feature filter  (후보 축소)
        │
        ▼
Stage 2: FastDTW                 (정밀 유사도)
        │
        ▼
outputs/match/ charts
```
