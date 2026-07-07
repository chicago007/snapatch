# Development Notes

**Author:** 조르바신부 · [chicago007@hotmail.com](mailto:chicago007@hotmail.com) · [GitHub](https://github.com/chicago007/snapatch)

Snapatch는 4개의 독립 캡스톤 프로젝트를 하나의 플랫폼으로 합치는 과정에서 만들어졌습니다.

## Origin

| Engine | Original | Role |
|--------|----------|------|
| breaker | capstone01 | Gemini 시황 속보 |
| diver | capstone02 | 네이버 뉴스 + AI 분석 |
| dejavu | capstone001 | 과거 유사 패턴 (DTW) |
| match | capstone002 | SAX + FastDTW 유사 종목 |

핵심 로직은 `engines/`에 두고, `hub/`는 UI·CLI·환경 초기화만 담당합니다.

## v1.02 (2026-07-07)

웹 이용자·문서·Cloud UX.

- **웹/로컬 설명서 분리**: `WEB_USER_GUIDE.md`(브라우저, 키 불필요, 다운로드 저장) · `USER_GUIDE.md`(로컬/CLI)
- **웹 UI**: 사용 설명서 페이지, 사이드바 하단 배치, `local_guide` 앱 내 이동
- **Cloud**: `outputs/` 저장 UI 숨김, breaker 시세 Yahoo 우선·표 후처리 강화, 버전/Import 오류 수정

## v1.01 (2026-07-07)

breaker·diver 안정화 패치.

- **breaker 국내 시세**: 네이버 금융 실시간 API를 코스피/코스닥 1순위로 추가 (장중 현재가). LLM이 뉴스 수치로 덮어쓰는 문제는 `apply_verified_quotes_to_report()`로 지수 표를 후처리.
- **diver JSON**: Gemini 구조화 출력이 토큰 한도로 잘리면 `JSONDecodeError` 발생 → 출력 토큰 상향, 프롬프트 축소, 3회 재시도(간결화 힌트).

## v1.00 (2026-07-07)

첫 정식 통합 릴리스.

- 4개 캡스톤 → snapatch Hub + Engines 통합
- Streamlit 웹 UI + CLI
- breaker 실측 시세 주입 (pykrx / Yahoo Finance)
- README·docs 정리, 웹 UI에 `v1.00` 표시
- 릴리스 노트 → [CHANGELOG.md](../CHANGELOG.md) 로 통합 (Keep a Changelog)

## Version bump checklist

버전을 올릴 때마다 아래를 **함께** 수정합니다.

1. `hub/project_info.py` — `VERSION` (예: `"1.02"`)
2. [CHANGELOG.md](../CHANGELOG.md) — 새 `[x.xx] - YYYY-MM-DD` 섹션
3. 이 파일 — `## vx.xx` 절에 배경·의사결정 요약
4. (선택) README 버전 배지, Git tag `vx.xx`

## Key decisions

### Hub + Engines split
- Streamlit Cloud 등에서 진입점이 하위 파일일 때도 `engines` 패키지를 찾을 수 있도록 `bootstrap.py`에서 `sys.path` 등록
- 기능 페이지(`hub/features/*.py`)는 engines import + Streamlit 위젯만 추가

### breaker market data (2026-07)
- LLM만으로 지수를 생성하면 2,785 vs 8,000 같은 할루시네이션이 발생
- 해결: LLM 호출 전 실측 시세 블록 주입 + v1.01부터 리포트 지수 표 후처리
- 국내: 네이버 금융 polling API (실시간) → pykrx → Yahoo. 해외·환율·원자재: Yahoo

### Model defaults
- accurate 모드 = Google Search + thinking (모델은 flash)
- `GEMINI_MODEL` env가 CLI/UI 공통 기본값

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
pytest tests/ -q
```

## Future ideas

- Demo GIF for README
- Portfolio / ETF modules
- RAG over saved reports in `outputs/`
- User auth for web deployment
