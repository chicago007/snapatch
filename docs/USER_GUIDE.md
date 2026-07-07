# snapatch 로컬 · CLI 사용 설명서

**버전:** v1.01 · **대상:** PC에 설치해 `.env` 설정 후 웹 UI 또는 터미널로 실행하는 이용자

> **웹(배포 URL)만 쓰시나요?** API 키 없이 바로 쓸 수 있는 **웹 이용 안내**(`?page=guide`)를 보세요.

> **면책:** 본 서비스와 리포트는 정보 제공 목적이며, 특정 종목의 매수·매도 추천이 아닙니다.

---

## 1. 구성 요소

| 이름 | 기능 | 필요 API 키 |
|------|------|-------------|
| **breaker** | Gemini 한국어 시황 속보 (실측 지수) | `GEMINI_API_KEY` |
| **diver** | 네이버 뉴스 + Gemini 분석 | `NAVER_*`, Gemini/Vertex |
| **dejavu** | 과거 유사 패턴 (6트랙) | 없음 (pykrx) |
| **match** | SAX + FastDTW 유사 종목 | 없음 (선택: `KRX_ID`/`KRX_PW`) |

---

## 2. 설치

```bash
git clone https://github.com/chicago007/snapatch.git
cd snapatch

python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
```

`.env`에 사용할 기능에 맞는 키만 채웁니다. 예시는 `.env.example` 참고.

---

## 3. 실행

### 웹 UI (로컬)

```bash
python run.py          # → [1] 웹 UI
# 또는
python -m streamlit run hub/ui/maingate.py
```

http://localhost:8501 — 로컬에서는 `outputs/` 폴더에 결과 저장 가능.

### 터미널 CLI

```bash
python run.py          # → [2] 터미널 CLI

python -m hub.cli.breaker --fast --print
python -m hub.cli.diver --query 삼성전자 --fast
python -m hub.cli.dejavu
python -m hub.cli.match
```

---

## 4. 기능별 사용 (로컬)

### breaker

- 웹: **속보 생성** → **마크다운 다운로드** · (선택) `outputs/breaker/` 저장
- CLI: `python -m hub.cli.breaker` / `--fast` / `loop` / `doctor`

| 변수 | 설명 |
|------|------|
| `GEMINI_API_KEY` | 필수 |
| `GEMINI_MODEL` | 기본 `gemini-2.5-flash` |
| `KRX_ID` / `KRX_PW` | pykrx 보조 (선택) |

### diver

- 웹: 키워드 입력 → **분석** → 다운로드 · (선택) `outputs/diver/` 저장
- CLI: `python -m hub.cli.diver --query 키워드`

| 변수 | 설명 |
|------|------|
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | 필수 |
| `GOOGLE_GENAI_USE_VERTEXAI` | `false`면 API 키 방식 |
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | API 키 방식 시 |

### dejavu · match

- pykrx 시세 기반. match는 UI/`.env`에서 KRX 로그인 선택 가능.
- 결과: `outputs/dejavu/`, `outputs/match/`

---

## 5. 결과 파일 (로컬)

| 기능 | 경로 |
|------|------|
| breaker | `outputs/breaker/YYYY-MM-DD_HH-MM_KST.md` |
| diver | `outputs/diver/키워드_날짜_KST.md` |
| dejavu | `outputs/dejavu/종목_타임스탬프/` |
| match | `outputs/match/` |

---

## 6. Streamlit Cloud 배포 (운영자)

웹 **이용자**용 안내는 [WEB_USER_GUIDE.md](WEB_USER_GUIDE.md).  
배포 시:

1. 진입점: `hub/ui/maingate.py`
2. **Secrets**에 API 키 등록
3. Git push 후 자동 재배포 (필요 시 Reboot app)

---

## 7. FAQ (로컬)

**Q. breaker 지수가 이상해요**  
실측 시세 캡션 `[naver]`/`[yahoo]` 확인. v1.01부터 표 후처리 적용.

**Q. diver JSON 오류**  
`--fast`(원문 생략) 또는 기사 수 줄이기.

**Q. API 키 위치**  
프로젝트 루트 `.env`

---

## 8. 더 보기

| 문서 | 대상 |
|------|------|
| [WEB_USER_GUIDE.md](WEB_USER_GUIDE.md) | **웹 이용자** (키 불필요) |
| [README.md](../README.md) | 프로젝트 소개 |
| [CHANGELOG.md](../CHANGELOG.md) | 변경 이력 |

문의: [chicago007@hotmail.com](mailto:chicago007@hotmail.com)
