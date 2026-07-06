"""snapatch — 주식 분석 통합 플랫폼.

4개 캡스톤 기능을 하나의 Streamlit 웹앱으로 통합한다.

- breaker : 시황 속보 생성 (Gemini)
- diver   : 키워드 뉴스 수집/분석 (Naver + Gemini)
- dejavu  : 같은 종목의 과거 유사 패턴 분석
- match   : 비슷한 패턴의 다른 종목 검색 (DTW)
"""

__all__ = ["__version__"]

from hub.project_info import VERSION

__version__ = VERSION
