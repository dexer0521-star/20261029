<h1 align="center">cron-trend-agent</h1>
<p align="center">
  <b>서버 없는 AI 트렌드 브리핑 에이전트.</b><br/>
  Fork → Secrets에 API 키 1개 → 매일 아침 Slack / Notion / 이메일로 Diff 기반 LLM 브리핑 수신.<br/>
  GitHub Actions 무료 스케줄러만으로 동작. VPS·Zapier·DB 없음.
</p>
<p align="center"><a href="README.md">English</a></p>

---

## 단순 RSS 요약 스크립트와 무엇이 다른가

| | cron-trend-agent | 일반 요약 스크립트 |
|---|---|---|
| **어제 대비 Diff** | 항목별 🆕 신규 / 🔥 급상승 / 🔻 하락, 점수·순위 변동, 급상승 키워드 | 같은 목록 재발송 |
| **키 없이 동작** | `--dry-run`이 샘플 데이터로 실제 브리핑 파일 생성 | 키 없으면 크래시 |
| **환각 차단** | 브리핑의 모든 링크는 수집된 입력에 존재해야 통과(Pydantic 검증) | 모델을 그대로 신뢰 |
| **죽지 않음** | 소스·채널별 격리, LLM primary → fallback → LLM 없는 추출 모드 | 429 하나에 전체 중단 |
| **DB 없는 상태 저장** | JSON 1개를 Actions cache로 유지 | Redis / S3 필요 |
| **확장** | 파일 1개 + `@register("type")` | 메인 루프 수정 |

```
수집(HN · RSS · Reddit · Apify) → 필터 → 이전 실행과 Diff → LLM(Gemini → Claude → OpenAI → 추출)
      → Slack Block Kit · Notion 페이지 · Markdown · Email → 상태 저장(.state/last_run.json)
```

## ⚡ 5분 퀵스타트

**0. 키 없이 로컬에서 확인**
```bash
git clone https://github.com/<you>/cron-trend-agent && cd cron-trend-agent
uv venv && uv pip install -e .            # 또는 pip install -e .
python -m src.main --dry-run              # → output/latest_brief.md 생성
```
**1. Fork** (또는 *Use this template*).

**2. 클라우드 dry-run**: *Actions* → **Daily Trend Brief** → *Run workflow* → `dry_run` 체크.
Secrets 없이도 초록불. `trend-brief-*` 아티팩트에서 샘플 브리핑 확인.

**3. LLM 키 1개 등록** (*Settings → Secrets and variables → Actions*):
`GEMINI_API_KEY`(무료 티어) 또는 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`. 있는 키를 자동 사용.

**4. 채널 등록**: `SLACK_WEBHOOK_URL`(Incoming Webhook). 선택: `NOTION_TOKEN` + `NOTION_DATABASE_ID`, SMTP 변수(이메일).

**5. Run workflow 재실행**(dry_run 해제) → 첫 실제 브리핑이 Slack에 도착. 이후 매일 07:30 KST(`30 22 * * *` UTC) 자동 실행.
시간은 `.github/workflows/daily-brief.yml`의 cron에서 변경.

## 🎛 프리셋

| 프리셋 | 소스 | 대상 |
|---|---|---|
| `ai-tech-news` | Hacker News, TechCrunch AI, The Verge AI | AI 툴링을 추적하는 엔지니어 |
| `kbeauty-commerce` | r/AsianBeauty, Google News(K-뷰티·아마존 뷰티), Apify(옵션) | K-뷰티 셀러·마케터 (한국어 출력) |
| `quant-macro` | 연준 보도자료, CNBC Economy, Google News(CPI/FOMC/금리) | 시스템 트레이더 |

```bash
python -m src.main --preset kbeauty-commerce             # 실제 실행
python -m src.main --preset quant-macro --no-notify      # LLM은 돌리되 발송 없이 markdown만
```

## ⚙️ 설정
`config/config.yaml`(`config.example.yaml` 복사). 시크릿은 YAML에 절대 넣지 않고 **환경변수 이름**만 적는다:
```yaml
llm:
  primary:   { provider: gemini, model: gemini-2.5-flash, api_key_env: GEMINI_API_KEY }
  fallbacks: [{ provider: claude, model: claude-haiku-5-5, api_key_env: ANTHROPIC_API_KEY }]
  language: ko
  audience: "K-beauty 수출 셀러"
notifiers:
  - { type: slack, webhook_env: SLACK_WEBHOOK_URL }
```
알 수 없는 키는 즉시 명확한 에러로 실패. 전체 스키마: [`docs/TECH_SPEC.md`](docs/TECH_SPEC.md).

### CLI
| 옵션 | 효과 |
|---|---|
| `--config PATH` / `--preset NAME` | 로드할 YAML |
| `--dry-run` | 오프라인: 샘플 데이터·Mock LLM·markdown만, 항상 exit 0 |
| `--no-llm` · `--no-notify` · `--no-state` | 해당 단계 생략 |
종료 코드: `0` 브리핑 생성(저하 모드 포함) · `2` 모든 소스 실패 · `3` 설정 오류.

## 🛡 장애 시 동작
| 상황 | 동작 |
|---|---|
| 피드 하나가 429/타임아웃 | 나머지 소스로 진행, 브리핑 하단에 `⚠️ sources failed` 표기 |
| 주력 LLM 장애·키 없음 | 다음 프로바이더 → 전부 실패 시 순위 기반 추출 브리핑(`degraded`) |
| 모델이 없는 URL 생성 | 검증기가 해당 항목 제거, 로그 기록 |
| JSON 깨짐 | repair 프롬프트 1회 후 다음 프로바이더 |
| 모든 소스 실패 | 상태 파일 보존, exit 2 → GitHub가 실패 메일 발송 |

## 🧩 파일 1개로 확장
`src/collectors/<name>.py`에 `BaseCollector`를 상속하고 `@register("<type>")`을 붙인 뒤 `collectors/__init__.py`에서 import.
`fetch()`(네트워크)와 `sample()`(dry-run 픽스처) 두 메서드만 구현하면 끝. 알림 채널도 동일(`notifiers/base.py`).

## 🧪 개발
```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest -q && uv run ruff check .
```
Claude Code로 개발한다면 `CLAUDE.md`의 아키텍처 규칙을 따른다.

## 라이선스
MIT — [LICENSE](LICENSE).
