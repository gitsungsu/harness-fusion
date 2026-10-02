# Harness Fusion 0.1.0

**계획 → 구현 → 실제 검사 → 독립 평가 → 전체 프로젝트 검증**을 실행하는 Python 하네스입니다.
Claude Code·Codex CLI를 역할별로 연결합니다. Python 3.11 이상이 필요하며 런타임 외부 의존성은 없습니다.

두 Awesome 자료집의 설계 원칙과 `harness-v2`의 역할 분리 아이디어를 참고해 새로 구현했습니다.
자료집에 연결된 도구를 전부 설치하거나 세 저장소의 코드를 합친 제품은 아닙니다.

## 무엇을 통합했나요?

| 참고 프로젝트 | 채택한 장점 | 이 프로젝트의 구현 |
|---|---|---|
| ai-boost/awesome-harness-engineering | 계획·구현 기록·규칙·점검을 문서로 관리 | 프로젝트 초기화, PRD·AGENTS·PLAN·TASKS·IMPLEMENT·체크리스트 |
| walkinglabs/awesome-harness-engineering | 문맥 관리·실행 제약·평가·관측 | 문맥 크기 제한, 최근 기억, JSON 계약, 역할별 수정 감시, 실행 이력 |
| gitsungsu/harness-v2 | Planner → Generator → Evaluator 실행과 재작업 | CLI 연결, 직접 테스트, 제한된 재시도, 상태 저장·재개 |

기능·검사·파일 감시·모델 연결을 별도 모듈로 나눴습니다. `DONE`은 모델이 작성할 수 없으며 엔진이 결정합니다.

## 가장 빠르게 실행하기 — Windows PowerShell

압축을 풀고 `harness-fusion` 폴더에서 실행합니다.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\harness-fusion.exe demo ..\fusion-demo
```

Python 3.12나 3.13을 설치했다면 첫 줄의 `-3.11`을 해당 버전으로 바꾸세요.
데모는 AI 계정 없이 동작합니다. SQLite 저장 프로그램에 의도적인 오류를 넣고,
실제 테스트가 실패하면 두 번째 시도에서 고쳐 최종 완료까지 진행합니다.
**데모의 에이전트는 정해진 응답을 내는 스크립트입니다. AI의 개발 성능을 검증하는 벤치마크는 아닙니다.**

Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/harness-fusion demo ../fusion-demo
```

데모 폴더는 새 경로여야 합니다. 같은 결과를 다시 검사하려면 `run ../fusion-demo --resume`을 사용합니다.

## 실제 AI로 프로그램 만들기

1. 이 하네스와 별도로 Codex CLI 또는 Claude Code를 설치하고 로그인합니다.
2. 새 작업 폴더에 프로젝트 설정을 만듭니다.
3. `docs/PRD.md`에 만들 내용과 완료 기준을 적습니다.
4. `harness.toml`의 모델과 검사 명령을 확인하고 실행합니다.

```powershell
.\.venv\Scripts\harness-fusion.exe init ..\my-project --backend codex --profile python
notepad ..\my-project\docs\PRD.md
notepad ..\my-project\harness.toml
.\.venv\Scripts\harness-fusion.exe doctor ..\my-project
.\.venv\Scripts\harness-fusion.exe run ..\my-project
```

`doctor`는 명령의 존재와 설정을 확인합니다. 로그인·모델 접근 권한까지 확인하지는 않습니다.
이 하네스는 CLI의 기존 인증을 사용합니다. 계정의 사용 가능 모델·사용량·요금은 해당 CLI 설정과 서비스 정책을 따릅니다.
구독 사용을 보장하거나 사용량 제한을 우회하는 기능은 없습니다.

PRD 예시:

```text
할 일 제목을 SQLite에 저장하는 Python 프로그램을 만든다.
add_task(database, title)는 새 ID를 반환한다.
list_tasks(database)는 삽입 순서대로 (ID, 제목) 목록을 반환한다.
빈 제목은 ValueError로 거부하고 한글과 따옴표를 보존한다.
임시 DB를 사용하는 자동 테스트로 위 동작과 재접속 후 영속성을 확인한다.
```

역할마다 다른 CLI를 쓸 수 있습니다.

```toml
[agents.planner]
backend = "codex"
# model = "계정에서-사용-가능한-모델-ID"

[agents.generator]
backend = "claude"

[agents.evaluator]
backend = "codex"
```

모델을 지정하지 않으면 각 CLI 기본값을 사용합니다. Generator와 Evaluator에 다른 모델을 배정하면
평가 관점을 나눌 수 있지만, 그것만으로 평가 정확성을 보장하지는 않습니다.

## 검사 설정

기본 Python 프로필은 `unittest`를 실행합니다. 테스트 0개와 전체 건너뛰기를 실패로 처리합니다.
기존 pytest 프로젝트에서는 아래처럼 바꾸세요. pytest와 프로젝트 의존성은 미리 설치해야 합니다.

```toml
[[checks]]
name = "pytest"
command = ["{python}", "-m", "pytest", "-q"]

[[checks]]
name = "ruff"
command = ["{python}", "-m", "ruff", "check", "src", "tests"]
```

`{python}`은 하네스를 실행하는 Python 경로로 치환됩니다. 문자열 셸 명령 대신 인자 배열을 사용합니다.
실행 전에 검사 도구와 의존성을 같은 환경에 설치하세요. 하네스는 의존성을 자동 설치하지 않습니다.
Node 프로필은 `npm test -- --run`, `npm run build`를 초기값으로 만듭니다. Vitest 계열 기준이므로
프로젝트 테스트 도구에 맞게 시작 전에 수정하세요. 임의의 명령이 종료 코드 0을 반환하는 것만으로
테스트 내용의 충실함을 보장할 수는 없습니다.

## 상태 확인과 재개

```powershell
.\.venv\Scripts\harness-fusion.exe status ..\my-project
.\.venv\Scripts\harness-fusion.exe run ..\my-project --resume
```

- 작업 성공: 종료 코드 `0`. 실패·미완료·한도 도달: `2`. 키보드 중단: `130`.
- 사이클 제한은 한 번의 실행에 적용됩니다. 재시도 제한은 저장된 작업 전체에 적용됩니다.
- 중단 시 진행 상황을 저장하며 같은 역할 호출의 토큰 스트림을 복구하지는 않습니다.
- 최종 통합 평가 실패 후 재개하면 작업들을 다시 열고 남은 재시도 한도 안에서 수정합니다.
- PRD·AGENTS·설정이 바뀌면 이전 실행에 이어 붙이지 않습니다. 기록을 보존하고 새 작업 폴더에서 시작하세요.
- 완료 뒤 코드가 달라지면 기존 완료 상태를 유효하다고 간주하지 않습니다.

| 파일 | 목적 |
|---|---|
| `harness.toml` | 모델·검사·시간·시도 한도 |
| `docs/PRD.md` | 사람이 정의한 요구사항 |
| `AGENTS.md` | 프로젝트의 작업 규칙 |
| `docs/PLAN.md`, `docs/TASKS.md` | 계획·완료 기준·진행 상황 |
| `docs/IMPLEMENT.md`, `docs/MEMORY.md` | 전체 구현 기록·최근 5개 요약 |
| `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` | 구조와 결정 기록 |
| `docs/REVIEW.md` | 최근 구조화 평가 |
| `.fusion/state.json` | 재개 가능한 실행 상태 |
| `.fusion/events.jsonl` | 역할·모델·시간·검사·완료 판정 이벤트 |
| `.fusion/runs/` | 프롬프트, 응답, 변경 파일과 내용 해시 |
| `.fusion/checks/` | 실제 검사 출력 |

최근 기억은 5개만 전달하고 전체 기록은 남깁니다. 필수 문맥이 예산을 넘으면 조용히 자르는 대신 중단합니다.
파일 내용 자체를 자동 백업하거나 Git 커밋하지 않으므로 변경 전 복원 지점은 직접 보관하세요.

## 완료 조건

1. 모든 작업의 실제 검사 명령이 0으로 종료.
2. 현재 호출 토큰·작업 ID와 일치하는 JSON 평가.
3. 사양 충족·테스트 충실도 점수가 각각 2/3 이상.
4. 모든 완료 기준에 통과 여부와 구체적인 근거가 있음.
5. 평가가 PASS이고 미해결 문제 목록이 비어 있음.
6. 모든 작업 후 검사와 전체 PRD 통합 평가를 다시 통과.

평가가 `PASS`라는 글자만 반환하거나 형식이 맞지 않으면 중단합니다. 테스트 실패를 PASS로 덮어쓸 수 없습니다.
검사 미설정은 시작 단계에서 거부됩니다.

## 적용 범위와 현재 한계

- 0.1.0은 감독하에 쓰는 로컬 MVP입니다. 실제 Claude·Codex 계정으로 수행하는 통합 검증은 아직 완료하지 않았습니다.
- Linux/Python 3.12에서 자체 테스트와 프로세스 데모를 실행했습니다. Windows/macOS 실기 검증은 남아 있습니다.
  Windows·Linux/Python 3.11–3.13 CI 설정을 포함했지만 원격 CI가 실행된 것은 아닙니다.
- 수정 감시는 파일 내용·권한의 전후 비교입니다. OS 보안 경계가 아니며 읽기·네트워크·폴더 밖 부작용을 차단하지 않습니다.
  `.git`, 가상환경, `node_modules`, 일부 캐시는 감시에서 제외합니다. 생성 뒤 원상복구한 일시적 수정도 잡지 못합니다.
- Codex는 계획·평가에 read-only, 구현에 workspace-write를 요청합니다. 사용자 CLI 정책은 그대로 적용합니다.
  Claude는 역할별 내장 도구를 제한합니다. 이 제한을 호스트 전체 격리라고 간주하면 안 됩니다.
- 기본 Claude Generator는 읽기·쓰기·편집 도구만 사용합니다. 셸이 필요한 설치·마이그레이션은 사전 준비가 필요합니다.
- 검사 명령은 신뢰하는 로컬 명령으로 취급합니다. 소스/설정 변경을 검사 후 탐지하고 중단하며,
  `dist/`, `build/`, `.next/`, `coverage/` 산출물과 공통 캐시는 예외입니다.
- Generator가 수정 가능한 테스트의 충실도는 Evaluator가 검토합니다. 별도 불변 평가셋·컨테이너 격리는 후속 개선 항목입니다.
- 실행 로그에는 프롬프트·응답·검사 출력이 포함됩니다. 비밀정보가 섞인 작업 기록을 공개 저장소에 올리지 마세요.
- Claude가 제공하는 사용량/비용 필드는 기록하지만 Codex 사용량과 구독 잔여량은 추정하지 않습니다.

## 개발·Codex 인계

`HANDOFF.md`를 읽으면 현재 검증 범위와 다음 작업을 이어갈 수 있습니다.

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
harness-fusion demo ../fusion-demo-new
```

구조 설명은 `docs/ARCHITECTURE.md`, 원본과의 관계는 `docs/SOURCES.md`에 있습니다.
