# 📈 snapatch

주식 **속보 · 분석 · 유사도 검색**을 하나의 Streamlit 웹앱으로 통합한 플랫폼입니다.
4개의 캡스톤 프로젝트를 단일 앱으로 묶었습니다.

| 기능 | 이름 | 설명 | 원본 |
|------|------|------|------|
| 📊 속보 | **breaker** | Gemini 로 한국어 시황 리포트 생성 | `capstone01` |
| 🔎 분석 | **diver** | 네이버 뉴스 + Gemini 키워드 심층 분석 | `capstone02` |
| 🕰️ 유사 패턴 | **dejavu** | 같은 종목의 과거 유사 구간 + 이후 수익률 | `capstone001` |
| 🧬 유사 종목 | **match** | 1차 SAX 필터 + 2차 FastDTW 유사 종목 검색 | `capstone002` |

## 프로젝트 구조

```
snapatch/
├── run.py                  # 시작 메뉴 (UI / 터미널 선택)
├── hub/                    # 통합·실행 계층 (엔진을 UI/CLI 로 묶음)
│   ├── launcher.py         # UI·CLI 선택 메뉴
│   ├── ui/
│   │   └── maingate.py     # Streamlit 웹 대시보드
│   ├── bootstrap.py        # engines 경로 + .env 초기화
│   ├── paths.py            # outputs/ 경로 헬퍼
│   ├── cli/
│   │   ├── breaker.py      # breaker 터미널 CLI
│   │   ├── diver.py        # diver 터미널 CLI
│   │   ├── dejavu.py      # dejavu 터미널 CLI
│   │   └── match.py       # match 터미널 CLI
│   └── features/
│       ├── breaker.py      # 시황 속보 페이지
│       ├── diver.py        # 키워드 뉴스 분석 페이지
│       ├── dejavu.py       # 과거 유사 패턴 페이지
│       └── match.py        # 유사 종목 검색 페이지
├── engines/                # 캡스톤 분석 엔진 (breaker, diver, dejavu, match)
│   ├── breaker/            # breaker.py, prompt.py
│   ├── diver/              # diver.py, config.py, pipeline.py, prompt.md
│   ├── dejavu/             # dejavu.py, dejavu.yml
│   └── match/              # match.py, match/ 패키지, tickers.csv, uni.csv
├── requirements.txt
├── .env.example
└── README.md
```

각 기능 페이지(`hub/features/*.py`)는 `engines/` 의 원본 코드를 import 해서
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

### 시작 메뉴 (권장)

프로젝트 루트에서 실행하면 **웹 UI / 터미널 CLI** 를 고르고,
터미널 선택 시 **breaker · diver · dejavu · match** 중 하나를 골라 실행합니다.

```bash
python run.py
# 또는
python -m hub
```

### 웹 UI (직접 실행)

```bash
python -m streamlit run hub/ui/maingate.py
```

브라우저가 열리면 왼쪽 사이드바에서 기능을 선택해 사용합니다.
`.streamlit/config.toml` 에 `headless = true` 이면 브라우저가 자동으로 열리지 않으므로
http://localhost:8501 을 직접 여세요.

### breaker 터미널 CLI (capstone01)

프로젝트 루트에서:

```bash
python -m hub.cli.breaker              # 즉시 1회 생성 (기본, once 생략 가능)
python -m hub.cli.breaker --print      # 콘솔만 출력
python -m hub.cli.breaker once --print   # 위와 동일
python -m hub.cli.breaker loop           # 평일 09~15시 KST 매시 정각
python -m hub.cli.breaker doctor         # GEMINI_API_KEY 확인
python -m hub.cli.breaker --model gemini-2.5-flash once
```

### diver 터미널 CLI (capstone02)

프로젝트 루트에서:

```bash
python -m hub.cli.diver --query 삼성전자
python -m hub.cli.diver --query 삼성전자 --format text
python -m hub.cli.diver --query 삼성전자 --fast --format text
python -m hub.cli.diver --query 삼성전자 --target-count 5 --max-days 30 --debug
```

환경변수 `DEFAULT_TARGET_COUNT`, `SKIP_CONTENT`, `DEFAULT_OUTPUT_FORMAT` 등은
`.env`에서 기본값으로 적용됩니다.

### dejavu 터미널 CLI (capstone001)

프로젝트 루트에서:

```bash
python -m hub.cli.dejavu
python -m hub.cli.dejavu engines/dejavu/dejavu.yml
```

설정은 `engines/dejavu/dejavu.yml` 을 수정하거나 YAML 경로를 인자로 넘깁니다.
6트랙(주가 z / 로그 / MA z × Pearson·DTW) 결과는 `outputs/dejavu/` 또는
설정의 `output_dir` 에 저장됩니다 (차트·CSV·TXT·MD).

### match 터미널 CLI (capstone002)

프로젝트 루트에서:

```bash
python -m hub.cli.match
python engines/match/match.py
```

설정은 `engines/match/match/config.py` 의 `FormaConfig` 기본값을 수정합니다.
1차 SAX·특징 필터 → 2차 FastDTW 후 TOP N 종목과 차트가 `outputs/match/` 에 저장됩니다.
후보 종목은 `engines/match/uni.csv`(기본) 또는 `engines/match/tickers.csv` 를 사용합니다.

### diver 테스트 (capstone02 하네스)

```bash
pytest tests/ -q
```

## 결과물

모든 생성물은 `outputs/` 아래에 모입니다.

- **breaker** 시황 리포트: `outputs/breaker/` (저장 옵션 켤 때)
- **diver** 분석 결과: `outputs/diver/` (JSON + TXT, CLI 기본 저장 / 웹 UI 옵션)
- **dejavu** 차트·표·결과문서: `outputs/dejavu/` (CLI는 평면, 웹 UI는 `<종목>_<시각>/` 하위)
- **match** 차트: `outputs/match/`

`outputs/`, `.env` 는 `.gitignore` 에 포함되어 커밋되지 않습니다.

## 참고

- **match** 는 capstone002 `match` 패키지(1차 SAX + 2차 FastDTW)를 사용합니다.
  웹 UI에서는 KRX 로그인 프롬프트를 생략하고 `.env`(`KRX_ID`/`KRX_PW`) 또는 UI 입력으로 처리합니다.
- 후보 종목: `engines/match/uni.csv`(기본), `engines/match/tickers.csv`(대안)
