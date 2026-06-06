# 📈 snapatch

주식 **속보 · 분석 · 유사도 검색**을 하나의 Streamlit 웹앱으로 통합한 플랫폼입니다.
4개의 캡스톤 프로젝트를 단일 앱으로 묶었습니다.

| 기능 | 이름 | 설명 | 원본 |
|------|------|------|------|
| 📊 속보 | **breaker** | Gemini 로 한국어 시황 리포트 생성 | `capstone01` |
| 🔎 분석 | **diver** | 네이버 뉴스 + Gemini 키워드 심층 분석 | `capstone02` |
| 🕰️ 유사 패턴 | **dejavu** | 같은 종목의 과거 유사 구간 + 이후 수익률 | `capstone001` |
| 🧬 유사 종목 | **match** | 기준 종목과 닮은 다른 종목 DTW 검색 | `capstone002` |

## 프로젝트 구조

```
snapatch/
├── maingate.py             # Streamlit 진입점 (사이드바 네비게이션)
├── snapatch/
│   ├── bootstrap.py        # vendor 경로 + .env 초기화
│   └── features/
│       ├── breaker.py      # 시황 속보 페이지
│       ├── diver.py        # 키워드 뉴스 분석 페이지
│       ├── dejavu.py       # 과거 유사 패턴 페이지
│       └── match.py        # 유사 종목 검색 페이지
├── vendor/                 # 원본 캡스톤 로직 (그대로 보존)
│   ├── breaker/            # briefing.py, prompt.py
│   ├── diver/news_harness/ # 뉴스 수집/분석 패키지
│   ├── dejavu/dejavu00.py  # 유사 패턴 엔진
│   └── match/              # match_engine.py, krx_io.py, tickers.csv
├── requirements.txt
├── .env.example
└── README.md
```

각 기능 페이지(`snapatch/features/*.py`)는 `vendor/` 의 원본 코드를 **수정 없이 import** 해서
Streamlit UI 로 감싸는 얇은 어댑터입니다. 핵심 로직은 원본 그대로 유지됩니다.

## 설치

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS/Linux
# source .venv/bin/activate

python -m pip install -r requirements.txt
```

## 환경변수 설정

```bash
copy .env.example .env   # Windows
# cp .env.example .env   # macOS/Linux
```

`.env` 에 필요한 키를 채웁니다. **기능별로 필요한 키만 채워도 해당 기능은 동작**합니다.

- **breaker**: `GEMINI_API_KEY`
- **diver**: `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `GOOGLE_CLOUD_PROJECT`
  (Vertex AI 는 `gcloud auth application-default login` 인증 필요)
- **dejavu**: 키 불필요 (pykrx 공개 시세)
- **match**: 키 불필요 (필요 시 `KRX_ID`/`KRX_PW`, UI 에서도 입력 가능)

## 실행

```bash
python -m streamlit run maingate.py
```

브라우저가 열리면 왼쪽 사이드바에서 기능을 선택해 사용합니다.

## 결과물

- **dejavu** 차트/표: `outputs/dejavu/<종목>_<시각>/`
- **match** 차트: `outputs/match/`
- **breaker** 리포트: `reports/` (저장 옵션 켤 때)

`outputs/`, `reports/`, `.env` 는 `.gitignore` 에 포함되어 커밋되지 않습니다.

## 참고

- `match` 는 원본 `12_newengine.py`(종가 전용 FastDTW 엔진)를 사용합니다.
  원본의 import 시점 KRX 로그인 프롬프트는 웹앱 블로킹을 막기 위해 제거하고,
  로그인은 UI 또는 `.env`(`KRX_ID`/`KRX_PW`)로 처리합니다.
- 후보 종목 목록은 `vendor/match/tickers.csv` 를 사용합니다.
