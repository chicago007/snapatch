"""pykrx → data.krx: 로그인·HTTP 타임아웃."""

from __future__ import annotations

import os
import sys
from getpass import getpass

import requests

REQUEST_TIMEOUT_SEC = 30.0
_patched = False
_login_ready = False


def _is_main_process() -> bool:
    try:
        import multiprocessing as mp

        return mp.current_process().name == "MainProcess"
    except Exception:  # noqa: BLE001
        return True


def patch_requests_default_timeout(
    seconds: float = REQUEST_TIMEOUT_SEC,
) -> None:
    """requests.Session.request 에 기본 timeout 을 붙입니다(1회만)."""
    global _patched
    if _patched:
        return
    _orig = requests.Session.request

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", seconds)
        return _orig(self, method, url, **kwargs)

    requests.Session.request = request  # type: ignore[method-assign]
    _patched = True


def _apply_krx_session(login_id: str, login_pw: str) -> bool:
    """pykrx 전역 KRX 세션 갱신(이미 import 된 뒤에도 호출 가능)."""
    try:
        from pykrx.website.comm.auth import build_krx_session, set_auth_session

        session = build_krx_session(login_id, login_pw)
        set_auth_session(session)
        return session is not None
    except Exception as exc:  # noqa: BLE001
        print(f"KRX 세션 적용 실패: {exc}", file=sys.stderr)
        return False


def prompt_krx_login_if_needed(*, force: bool = False) -> bool:
    """KRX_ID/KRX_PW 설정. 없으면 터미널에서 입력(1회).

    Returns:
        로그인 세션 적용 성공 여부. 스킵·실패 시 False(무인증 조회 시도).
    """
    global _login_ready
    if _login_ready and not force:
        return bool(os.getenv("KRX_ID") and os.getenv("KRX_PW"))

    # ProcessPoolExecutor 워커: 부모가 넣어 둔 환경변수만 사용
    if not _is_main_process():
        _login_ready = True
        login_id = (os.getenv("KRX_ID") or "").strip()
        login_pw = (os.getenv("KRX_PW") or "").strip()
        if login_id and login_pw:
            return _apply_krx_session(login_id, login_pw)
        return False

    login_id = (os.getenv("KRX_ID") or "").strip()
    login_pw = (os.getenv("KRX_PW") or "").strip()

    if not (login_id and login_pw):
        print(
            "\n[KRX 로그인] pykrx 1.2+ data.krx 조회용 (환경변수 미설정)",
            flush=True,
        )
        login_id = input("KRX 아이디 (엔터=로그인 없이 진행): ").strip()
        if not login_id:
            print("로그인 없이 진행합니다.", flush=True)
            _login_ready = True
            return False
        login_pw = getpass("KRX 비밀번호: ").strip()
        if not login_pw:
            print("비밀번호가 비어 있어 로그인 없이 진행합니다.", flush=True)
            _login_ready = True
            return False
        os.environ["KRX_ID"] = login_id
        os.environ["KRX_PW"] = login_pw

    ok = _apply_krx_session(login_id, login_pw)
    _login_ready = True
    return ok


def fetch_ohlcv(ticker: str, start_date: str, end_date: str):
    from pykrx import stock

    return stock.get_market_ohlcv_by_date(start_date, end_date, ticker)
