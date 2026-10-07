# Planner (계획 에이전트)

## 하는 일
`harness-fusion run`을 시작하면 맨 처음 한 번 실행됩니다. PRD 전체를 순서가 있는 작업(T1, T2…)으로 나눕니다.
작업마다 수정할 수 있는 경로(touch)와 완료 기준(acceptance)을 정합니다.

## 모델 설정
기본값은 [`src/harness_fusion/default_agents.toml`](../src/harness_fusion/default_agents.toml)의 `[planner]`, 프로젝트별 값은 그 프로젝트 `agents.toml`의 `[planner]`입니다.

## 권한: 읽기 전용
- codex: `--sandbox read-only`
- claude: `--tools Read,Glob,Grep`
- agy: `--mode plan`
- 실행 뒤 바뀐 파일이 하나라도 있으면 하네스가 중단합니다.

## 지시문 (원문)
```
Inspect the project. Cover the whole PRD with ordered tasks and concrete acceptance criteria.
No file edits. Include tests in touch paths. Dependencies refer only to earlier tasks.
touch paths are relative, explicit files or folder/**; no unrestricted **.
Do not propose edits to protected configuration or PRD. No DONE declarations.
```

## 받는 정보
`AGENTS.md`(규칙), `docs/PRD.md`(요구사항), `docs/ARCHITECTURE.md`·`DECISIONS.md`(있으면 앞 4000자), 이전 실패 기록과 메모

## 돌려줘야 하는 JSON
```json
{
  "summary": "Short architecture and delivery plan",
  "tasks": [{"id": "T1", "title": "Specific task", "depends_on": [],
             "touch": ["src/**", "tests/**", "docs/ARCHITECTURE.md"],
             "acceptance": ["A behavior verified by an executable test"]}]
}
```
형식이 틀리거나 touch가 `**`처럼 너무 넓으면 하네스가 받아들이지 않습니다.
결과는 하네스가 `docs/PLAN.md`로 정리합니다.

원본: `src/harness_fusion/context.py`, `src/harness_fusion/providers.py`
