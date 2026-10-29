# CLAUDE.md - cron-trend-agent 개발 지침

## 프로젝트 개요
GitHub Actions(무료 cron)와 LLM API만으로 동작하는 Zero-Server 트렌드 수집·Diff·분석·브리핑 오픈소스 스타터 키트.
파이프라인: `collect → filter → diff(이전 실행 대비) → analyze(LLM, 폴백 포함) → notify → save state`.

## 기술 스택 및 환경 규칙
- Python 3.11+, 의존성은 `uv` + `pyproject.toml` 기준. 로컬 셋업: `uv venv && uv pip install -e ".[dev]"`.
- 모든 입출력 데이터·설정 파싱은 Pydantic V2 + 표준 타입 힌트 필수. 설정 모델은 `extra="forbid"`.
- HTTP는 `httpx.AsyncClient`, 재시도는 `tenacity`(지수 백오프). 벤더 SDK 추가 금지(REST 직접 호출).
- 린트/포맷: `uv run ruff check --fix . && uv run ruff format .` / 테스트: `uv run pytest -q`.

## 핵심 아키텍처 원칙
1. **Graceful Degradation**: 수집기 하나가 죽어도 파이프라인은 계속된다. `CollectResult.error`로 보고하고
   브리핑 하단 `source_errors`에 첨부한다. 알림 채널도 동일(`NotifyResult`). `raise`로 전체를 죽이지 말 것.
2. **LLM Fallback 라우팅**: `LLMRouter`는 primary → fallbacks → `build_extractive_brief`(LLM 없음) 순.
   키가 없는 프로바이더는 조용히 건너뛴다. 잘못된 JSON은 1회 repair 프롬프트 후 다음 프로바이더로.
3. **Zero-Config `--dry-run`**: Secrets가 전혀 없어도 `python -m src.main --dry-run`이 성공해야 한다.
   모든 수집기는 `sample()` 픽스처를, LLM은 `MockProvider`를, 네트워크 알림기는 skip을 제공한다.
   dry-run이 깨지면 PR 머지 불가(`tests/test_cli.py`).
4. **Strict Groundedness**: `BriefItem.url`은 `model_validate(..., context={"allowed_urls"})`로 수집 URL과
   대조된다. 없는 링크는 드롭되고, 전부 틀리면 폴백으로 간다. 이 가드를 우회하는 코드 금지.
5. **상태는 파일 하나**: `.state/last_run.json`(Pydantic `RunState`). DB·외부 저장소 도입 금지.
   아이템 ID = `sha1(normalize_url(url))[:16]`. 상태는 1개 이상 소스가 성공했을 때만 덮어쓴다.

## 코딩 컨벤션
- 모듈 단일 책임, 파일당 200줄 이하. 레이어: `collectors/`, `analyzers/`, `notifiers/`, `storage/`.
- 새 소스/채널 = 파일 1개 추가 + `@register("type")` + 해당 `__init__.py`에 import. 다른 파일 수정 불필요.
- 모든 API 키는 `os.environ`(`config_loader.resolve_env`)으로만 읽는다. YAML에는 env 변수 **이름**만 적는다
  (`webhook_env: SLACK_WEBHOOK_URL`). 값·토큰을 로그에 남기지 말 것.
- 외부 호출에는 타임아웃을 반드시 지정. 로그는 `logging` 모듈, `print`는 CLI 최종 요약에만.
- 테스트는 네트워크 없이 돌아야 한다(`respx`로 mock). 프리셋을 추가하면 `tests/test_cli.py`의 목록도 갱신.

## 자주 쓰는 명령
```bash
uv run python -m src.main --dry-run                       # 오프라인 데모
uv run python -m src.main --preset ai-tech-news --no-notify  # 실제 수집 + LLM, 발송 없이 markdown만
uv run python -m src.main --config config/config.yaml -v  # 내 설정으로 전체 실행
uv run pytest -q && uv run ruff check .
```
