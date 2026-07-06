# 📈 Snapatch

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.35+-FF4B4B?logo=streamlit&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-API-4285F4?logo=google&logoColor=white)
![License](https://img.shields.io/badge/License-TBD-lightgrey)

![Version](https://img.shields.io/badge/version-v1.00-blue)

> **AI-Powered Stock Intelligence Platform**
>
> Real-time market reports, AI news analysis, historical pattern search,
> and similar-stock discovery — all in one dashboard.

주식 **속보 · 분석 · 유사도 검색**을 하나의 Streamlit 웹앱으로 통합한 플랫폼입니다.
4개의 프로젝트(breaker · diver · dejavu · match)를 단일 앱으로 묶었습니다.

✨ **Four AI-powered investment tools in one platform**

| | | |
|---|---|---|
| 📊 **breaker** | **Breaking Market Reports** | Gemini 기반 한국어 시황 속보 |
| 🔎 **diver** | **News Intelligence** | 네이버 뉴스 + AI 키워드 심층 분석 |
| 🕰 **dejavu** | **Historical Pattern Search** | 같은 종목의 과거 유사 구간 탐색 |
| 🧬 **match** | **Similar Stock Discovery** | SAX + FastDTW 유사 종목 검색 |

---

## 💡 Why Snapatch?

개인 투자자는 시장을 보려면 보통 여러 도구를 오가야 합니다.

- 뉴스 사이트에서 헤드라인 확인
- AI 챗봇에 따로 질문
- 차트·패턴 분석은 또 다른 플랫폼
- 유사 종목 검색은 별도 스크리너

**Snapatch**는 이 흐름을 하나의 대시보드와 CLI로 묶습니다.
뉴스 읽기 → AI 분석 → 과거 패턴 → 유사 종목까지, 한 프로젝트 안에서 이어집니다.

---

## ✨ Features

4개의 프로젝트를 snapatch 하나로 통합했습니다. **개발: 조르바신부**

| snapatch | 기능 | AI / Algorithm |
|---|---|---|
| 📊 **breaker** | 한국어 시황 속보 (실측 지수 주입) | Gemini + pykrx / Yahoo Finance |
| 🔎 **diver** | 키워드 뉴스 수집·필터·심층 분석 | Gemini + Vertex AI |
| 🕰 **dejavu** | 과거 유사 구간(6트랙) + 이후 수익률 | Pearson + DTW |
| 🧬 **match** | SAX 1차 필터 → FastDTW 유사 종목 | SAX + FastDTW |

---

## 🎬 Demo

> GIF·스크린샷은 [`docs/images/`](docs/images/)에 추가 예정입니다.
> 지금은 로컬 실행 후 `outputs/` 폴더에서 생성 결과를 확인할 수 있습니다.

| Dashboard | breaker 출력 예시 |
|-----------|-------------------|
| `python run.py` → 웹 UI | `outputs/breaker/` 아래 마크다운 리포트 |

breaker는 **pykrx / Yahoo Finance로 조회한 실측 지수**를 LLM 프롬프트에 주입해
코스피·환율 등 숫자 할루시네이션을 줄입니다.

---

## ⭐ Highlights

- 4개 독립 캡스톤을 **하나의 Hub + Engines** 구조로 통합
- **웹 UI**(Streamlit)와 **터미널 CLI** 모두 지원
- breaker: 실시간 시세 주입 + Gemini 리포트 생성
- diver: 네이버 뉴스 파이프라인 + Gemini/Vertex AI 분석
- dejavu: 6트랙(주가 z / 로그 / MA z × Pearson·DTW) 유사 패턴
- match: SAX 1차 후보 축소 → FastDTW 2차 정밀 매칭
- 기능별 API 키만 설정해도 해당 모듈 단독 실행 가능

---

## 🏗 Architecture

```text
User
  │
  ├─ run.py / streamlit ──► Hub (launcher · UI · CLI · bootstrap)
  │                              │
  │                              ▼
  │                         Analysis Engines
  │                         ├── breaker  (Gemini + market data)
  │                         ├── diver    (Naver + Gemini)
  │                         ├── dejavu   (pykrx + DTW)
  │                         └── match    (pykrx + SAX + FastDTW)
  │                              │
  │                              ▼
  └──────────────────────── outputs/
```

상세 구조는 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)를 참고하세요.

---

## 🛠 Tech Stack

| Layer | Technologies |
|-------|--------------|
| UI / CLI | Python, Streamlit |
| AI | Gemini API, Vertex AI, Google Search Grounding |
| Market data | pykrx, Yahoo Finance (requests) |
| Analysis | SAX, FastDTW, Pearson, DTW (dtaidistance) |
| Data | Pandas, NumPy, SciPy |

---

## 🚀 Quick Start

### 1. 설치

```bash
git clone https://github.com/chicago007/snapatch.git
cd snapatch

python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2. 환경변수

```bash
cp .env.example .env   # Windows: copy .env.example .env
```

**기능별로 필요한 키만 채워도 해당 기능은 동작**합니다.

| 기능 | 필요 키 |
|------|---------|
| breaker | `GEMINI_API_KEY` |
| diver | `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `GOOGLE_CLOUD_PROJECT` (+ `gcloud auth application-default login`) |
| dejavu | 없음 (pykrx 공개 시세) |
| match | 없음 (선택: `KRX_ID` / `KRX_PW`) |

### 3. 실행

**시작 메뉴 (권장)**

```bash
python run.py
# 또는
python -m hub
```

**웹 UI 직접 실행**

```bash
python -m streamlit run hub/ui/maingate.py
```

브라우저: http://localhost:8501

---

## 📟 CLI

프로젝트 루트에서:

```bash
# breaker — 시황 속보
python -m hub.cli.breaker              # 1회 생성 (정확 모드)
python -m hub.cli.breaker --fast       # 빠른 모드
python -m hub.cli.breaker loop         # 평일 09~15시 KST 매시
python -m hub.cli.breaker doctor       # API 키 확인

# diver — 키워드 뉴스 분석
python -m hub.cli.diver --query 삼성전자

# dejavu — 과거 유사 패턴
python -m hub.cli.dejavu

# match — 유사 종목 검색
python -m hub.cli.match
```

---

## 📂 Project Structure

```text
snapatch/
├── run.py              # 시작 메뉴 (웹 UI / CLI)
├── hub/                # launcher · UI · CLI · bootstrap
├── engines/            # breaker · diver · dejavu · match
├── outputs/            # 생성 결과 (gitignore)
├── docs/               # 상세 문서
├── requirements.txt
└── .env.example
```

각 `hub/features/*.py`는 `engines/` 원본을 import하는 얇은 어댑터입니다.

---

## 📦 Outputs

| Engine | 경로 |
|--------|------|
| breaker | `outputs/breaker/` |
| diver | `outputs/diver/` |
| dejavu | `outputs/dejavu/` |
| match | `outputs/match/` |

---

## 🗺 Roadmap

- [x] 4개 캡스톤 통합 (Hub + Engines)
- [x] Streamlit 대시보드 + CLI
- [x] breaker 실측 시세 주입 (pykrx / Yahoo Finance)
- [x] v1.00 릴리스 · CHANGELOG 도입
- [ ] Demo GIF · 스크린샷
- [ ] Portfolio analysis
- [ ] ETF similarity
- [ ] RAG knowledge base
- [ ] Multi-language support

전체 로드맵: [docs/ROADMAP.md](docs/ROADMAP.md)

---

## 📚 Documentation

| 문서 | 설명 |
|------|------|
| [CHANGELOG.md](CHANGELOG.md) | 변경 이력 (Keep a Changelog) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 아키텍처 상세 |
| [docs/RELEASE_NOTES.md](docs/RELEASE_NOTES.md) | → CHANGELOG 안내 |
| [docs/DEVELOPMENT_NOTES.md](docs/DEVELOPMENT_NOTES.md) | 개발 과정·버전 메모 |

---

## 🧪 Tests

```bash
pytest tests/ -q
```

---

## Author

**조르바신부**

- GitHub: [@chicago007](https://github.com/chicago007)
- Repository: [github.com/chicago007/snapatch](https://github.com/chicago007/snapatch)
- Email: [chicago007@hotmail.com](mailto:chicago007@hotmail.com)

4개 캡스톤(capstone01 · capstone02 · capstone001 · capstone002)을 snapatch로 통합한 개인 프로젝트입니다.  
매핑은 위 [Features](#-features) 표를 참고하세요.

---

## License

License is not specified yet.

---

Built with **Python · Streamlit · Gemini · Vertex AI · pykrx · SAX · FastDTW** · **조르바신부**
