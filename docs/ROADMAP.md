# Roadmap

## Done

- [x] Integrate 4 capstone projects into snapatch
- [x] Streamlit dashboard + terminal CLI
- [x] Modular `hub/` + `engines/` architecture
- [x] breaker verified market data (pykrx / Yahoo Finance)
- [x] breaker default model → gemini-2.5-flash

## In progress / Next

- [ ] README demo GIF and screenshots (`docs/images/`)
- [ ] breaker: optional Naver Finance as 3rd fallback
- [ ] breaker: post-generation numeric validation

## Planned

- [ ] Portfolio analysis module
- [ ] ETF similarity search
- [ ] RAG knowledge base over historical reports
- [ ] AI investment assistant (multi-turn)
- [ ] Multi-language reports (EN/KR toggle)
- [ ] Web deployment auth (Streamlit Authenticator or OIDC)

## Ideas

- Scheduled breaker loop as a cloud job
- diver → breaker pipeline (news → market report)
- match candidate universe auto-update from KRX
