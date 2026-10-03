# Generator (구현 에이전트)

## 하는 일
작업 하나를 구현하고 테스트를 씁니다. 파일을 수정할 수 있는 유일한 에이전트입니다.
끝나면 하네스가 `harness.toml`의 checks(테스트)를 직접 실행하고 결과를 Evaluator에게 넘깁니다.
실패하면 실패 기록을 받아 다시 시도합니다(작업당 `max_attempts`회, 기본 3회).

## 모델 설정
기본값은 [`src/harness_fusion/default_agents.toml`](../src/harness_fusion/default_agents.toml)의 `[generator]`, 프로젝트별 값은 그 프로젝트 `agents.toml`의 `[generator]`입니다.

## 권한: 작업 범위 안에서만 쓰기
- codex: `--sandbox workspace-write`
- claude: `--tools Read,Glob,Grep,Edit,Write`. 명령 실행(Bash)은 할 수 없습니다.
- 실행 뒤 하네스가 바뀐 파일을 내용 해시로 비교합니다. 아래 파일이 바뀌어 있으면 중단합니다.
  - 작업의 touch 경로 밖에 있는 파일. 단 빌드 출력(`dist/`, `build/`, `.next/`, `coverage/`)은 예외입니다.
  - 보호 파일: `harness.toml`, `agents.toml`, `AGENTS.md`, `CLAUDE.md`, `docs/PRD.md`, `docs/PLAN.md`, `docs/TASKS.md`, `docs/MEMORY.md`, `docs/IMPLEMENT.md`, `docs/REVIEW.md`, `.fusion/`, `.git/`, `.env*`
  - `[acceptance]` 폴더(사람이 쓴 수용 테스트)

## 지시문 (원문)
```
Implement only this task in its touch paths. Add behavioral and edge-case tests.
Use prior failure evidence to repair the work. Do not weaken tests, change requirements,
or edit harness-owned files. The engine will run configured checks after you finish.
Do not install dependencies or deploy. Explain any dependency blocker in summary.
```

## 받는 정보
규칙, PRD, 현재 작업(task), 전체 계획, 끝난 작업 목록, 직전 실패 기록(last_failure), 검사 결과, 최근 메모 5개

## 돌려줘야 하는 JSON
```json
{"summary": "Implementation, decisions, test intent and remaining risks"}
```

원본: `src/harness_fusion/context.py`, `src/harness_fusion/providers.py`, `src/harness_fusion/filesystem.py`
