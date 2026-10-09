# Harness Fusion 0.1.0

**계획 → 구현 → 실제 검사 → 독립 평가 → 전체 프로젝트 검증**을 실행하는 Python 하네스입니다.
Claude Code·Codex CLI·Google Antigravity(agy)를 역할별로 연결합니다. Python 3.11 이상이 필요하며 런타임 외부 의존성은 없습니다.

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

저장소를 받은(`git clone`) `harness-fusion` 폴더에서 실행합니다.

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

1. 이 하네스와 별도로 Codex CLI, Claude Code 또는 Antigravity(agy) CLI를 설치하고 로그인합니다.
2. 새 작업 폴더에 프로젝트 설정을 만듭니다.
3. `docs/PRD.md`에 만들 내용과 완료 기준을 적습니다. 직접 쓰기 어려우면 `prd` 명령으로 대화하며 작성하고,
   이어서 프로젝트에 필요한 스킬을 골라 설치할 수 있습니다(아래 "PRD 인터뷰" 참고).
4. `agents.toml`의 에이전트별 모델과 `harness.toml`의 검사 명령을 확인하고 실행합니다.

```powershell
.\.venv\Scripts\harness-fusion.exe init C:\claude-api\projects\my-project --backend agy --profile python
.\.venv\Scripts\harness-fusion.exe prd C:\claude-api\projects\my-project      # 대화형 인터뷰로 docs/PRD.md 작성
notepad C:\claude-api\projects\my-project\agents.toml
notepad C:\claude-api\projects\my-project\harness.toml
.\.venv\Scripts\harness-fusion.exe doctor C:\claude-api\projects\my-project
.\.venv\Scripts\harness-fusion.exe run C:\claude-api\projects\my-project
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

역할마다 다른 CLI·모델을 쓰려면 `agents.toml`을 고칩니다(아래 "에이전트와 모델 설정" 참고).

## 에이전트와 모델 설정 (agents.toml)

하네스 실행(`run`)에는 **세 에이전트**가 있고, 그 밖에 PRD를 인터뷰로 작성하는 `bootstrap` 에이전트가 있습니다.
프로젝트 루트의 `agents.toml`에서 에이전트별로 CLI·모델·effort를 따로 지정합니다.
`init`이 이 파일을 만들며, 사용자 전역 CLI 설정이 바뀌어도 같은 조건으로 실행하기 위해 모델과 effort를 명시합니다.

**모델 기본값은 [`src/harness_fusion/default_agents.toml`](src/harness_fusion/default_agents.toml) 한 곳에서만 정합니다.**
새 프로젝트의 모델을 바꾸려면 이 파일을, 이미 만든 프로젝트는 그 프로젝트의 `agents.toml`을 고칩니다.
문서에는 모델 이름을 적지 않으므로 현재 기본값은 이 파일이나 `doctor` 출력에서 확인하세요.

| 에이전트 | 하는 일 | 권한 |
|---|---|---|
| `planner` | PRD를 읽고 작업 계획(JSON)을 만든다 | 읽기 전용, 파일 수정 시 중단 |
| `generator` | 현재 작업의 `touch` 범위 안에서 구현하고 테스트를 쓴다 | 쓰기 가능(범위 밖·보호 파일 수정 시 중단) |
| `evaluator` | 소스와 실제 검사 결과를 읽고 평가(JSON)를 낸다. 마지막 전체 평가도 담당 | 읽기 전용, 파일 수정 시 중단 |
| `bootstrap` | `harness-fusion prd`에서 사용자와 대화하며 `docs/PRD.md`를 쓰고, 필요한 스킬을 골라 설치한다. `run`에는 참여하지 않음 | 프로젝트 읽기·PRD 쓰기·스킬 검색만 자동 허용, 스킬 설치는 사용자 승인. PRD·스킬 외 파일이 바뀌면 실패 처리 |

프로젝트 `agents.toml` 형식(섹션마다 같은 키):

```toml
[planner]                     # generator, evaluator, bootstrap도 같은 형식
backend = "claude"            # codex | claude | agy | command
model = "<모델 ID>"
effort = "high"               # low | medium | high | xhigh | max
```

- 역할마다 backend를 섞어 쓸 수 있습니다(예: 계획·구현은 `agy`, 평가는 `claude`). `init`이 만드는 `agents.toml` 머리말에
  backend별 CLI와 기본 모델 목록이 주석으로 들어 있으니, 프로젝트마다 그 파일의 `backend`·`model`만 고치면 됩니다.
- 세 섹션(`planner`, `generator`, `evaluator`)이 모두 있어야 하고, 알 수 없는 섹션·키는 오류입니다. `[bootstrap]`은 선택입니다.
- `default_agents.toml`에서 `backend = "init"`인 역할은 `init --backend` 값을 따르고, `model`을 생략한 역할은 `[models]`의 backend별 모델을 씁니다.
  `init --uniform`(bench가 사용)은 세 역할 모두 generator 설정을 씁니다. `[bootstrap]`은 대화형이라 claude만 가능합니다.
  `backend`는 `codex`, `claude`, `agy`, `command`(스크립트용) 중 하나입니다.
- `agents.toml`이 있으면 `harness.toml`에는 `[agents]`를 쓸 수 없습니다(둘 다 있으면 오류). 정의를 한 곳에만 두기 위해서입니다.
  `agents.toml`이 없는 기존 프로젝트는 `harness.toml`의 `[agents.*]`를 그대로 읽습니다.
- `agents.toml`은 에이전트가 수정할 수 없는 보호 파일이고, 바꾸면 이전 실행에 이어 붙일 수 없습니다(새 프로젝트 폴더에서 시작).
  `doctor`가 에이전트 정의가 어느 파일에 있는지 보여 줍니다.
- 모델을 지정하지 않으면 각 CLI 기본값을 쓰며, Generator와 Evaluator에 다른 모델을 배정하면 평가 관점을 나눌 수 있지만
  그것만으로 평가 정확성을 보장하지는 않습니다.
- Codex는 `-c model_reasoning_effort="..."`, Claude와 agy는 `--effort ...`로 전달합니다. 지정한 값은 `events.jsonl`에 기록됩니다.
- `ultra`는 Codex가 자동으로 작업을 위임(subagent)하는 수준이라 이 하네스의 "subagent 금지" 규칙과 충돌해 거부합니다.
- `backend = "command"`에는 effort를 쓸 수 없습니다. 허용 값은 CLI 버전·모델에 따라 다를 수 있으니 거부되면 CLI 안내를 확인하세요.

## PRD 인터뷰 (`prd`, bootstrap 에이전트)

PRD를 직접 쓰기 어렵다면, 하네스가 Claude 대화 세션을 열어 질문을 하나씩 하며 `docs/PRD.md`를 써 줍니다.

```powershell
.\.venv\Scripts\harness-fusion.exe init C:\claude-api\projects\my-project --backend agy
.\.venv\Scripts\harness-fusion.exe prd C:\claude-api\projects\my-project
```

- `agents.toml`의 `[bootstrap]` 설정으로 대화형 `claude` 세션을 엽니다. 실제 터미널에서만 동작합니다.
- 진행 순서: ① 질문에 하나씩 답해 `docs/PRD.md` 작성 → ② PRD에 맞는 스킬 검색·추천 → ③ 고른 스킬만 프로젝트에 설치.

### PRD 작성 뒤 스킬 설치

PRD가 저장되면 같은 세션에서 `find-skills` 스킬(없으면 같은 절차를 직접 수행)로 [skills.sh](https://skills.sh/)의 스킬을 찾습니다.

- PRD에서 언어·프레임워크·테스트 도구 같은 검색어를 골라 `npx skills find <검색어>`를 실행합니다(자동 허용).
- 설치 수가 적거나(100 미만) 출처가 불분명한 스킬은 제외하고, 후보를 최대 5개 보여 준 뒤 설치할 것을 묻습니다.
  아무것도 설치하지 않아도 됩니다.
- 설치 명령 `npx skills add <owner/repo> -s <스킬> -a claude-code -a codex --copy -y`는 **자동 허용하지 않습니다.**
  Claude가 실행 전에 권한을 물으니, 명령을 확인하고 승인하세요. 전역 설치(`-g`)는 쓰지 않습니다.
- 설치 위치: `.claude/skills/<스킬>/`(Claude용), `.agents/skills/<스킬>/`(Codex용), `skills-lock.json`.
  하네스는 심볼릭 링크 폴더를 지원하지 않으므로 `--copy`로 실제 파일을 복사합니다.
- 설치한 스킬은 `run`의 모든 에이전트 요청에 SKILL.md 경로 목록으로 전달되어, 관련 있을 때 읽고 따릅니다.
  하네스 규칙·출력 형식보다 우선하지 않습니다. 에이전트는 스킬 파일을 수정할 수 없습니다(보호 파일).
- 스킬은 제3자가 만든 지시문입니다. 설치 전에 출처를 확인하세요. 하네스는 스킬 내용을 검증하지 않습니다.

### 실패·경고

- 셸 도구는 스킬 검색·설치용으로만 쓰도록 지시하고, 권한 우회 플래그는 쓰지 않습니다. 자동 허용 범위 밖의 명령은 Claude가 권한을 묻습니다.
- 세션이 끝난 뒤 `docs/PRD.md`와 스킬 파일(위 설치 위치, Claude의 `.claude/settings.local.json`) 외에 바뀐 파일이 있으면 실패로 알립니다(되돌리지는 않음).
- PRD가 쓰이지 않았거나 `TODO:`가 남아 있으면 실패, 완료 기준·테스트 방법이 빠지면 경고합니다. 설치된 스킬 이름을 마지막에 보여 줍니다.
- 이미 `run`을 시작한 프로젝트에서는 거부합니다(PRD를 바꾸면 이전 실행에 이어 붙일 수 없으므로).

## PRD 템플릿과 점검

`init`(목표를 주지 않을 때)은 `목표 / 입력과 출력 / 완료 기준 / 테스트 방법` 섹션이 있는 PRD 템플릿을 만듭니다.
`TODO:`가 남아 있으면 실행을 시작하지 않습니다. 자유 형식 PRD도 계속 쓸 수 있지만, 완료 기준이나 테스트 방법에 대한
언급이 없으면 `doctor`와 `run` 시작 때 **경고**만 출력합니다(중단하지 않음). 경고는 단어 검색일 뿐 PRD 품질 보증이 아닙니다.

## 평가셋(bench)

AI가 볼 수 없는 숨은 채점 테스트로 하네스의 DONE 판정을 점검합니다. 과제는 harness-v2의 slugify·wordcount·rpn과
같은 요구사항·채점 단언이며, 실행 방식만 `uv run`→`python -m`, pytest→unittest로 바꿨습니다(v2 결과와 직접 비교하지 마세요).

```powershell
.\.venv\Scripts\harness-fusion.exe bench                 # 목록만 출력, 아무것도 실행하지 않음
.\.venv\Scripts\harness-fusion.exe bench --run --backend codex   # 실제 AI 실행. 사용량을 소모합니다
.\.venv\Scripts\harness-fusion.exe bench --run --only rpn         # 일부만
```

결과는 `bench-runs/results.jsonl`에 한 줄씩 추가됩니다(엔진 판정, 숨은 채점, 사이클·시간, 모델·effort, 사용량).
`verified`는 엔진이 DONE이고 숨은 테스트도 통과한 경우만 true입니다. DONE인데 숨은 테스트가 실패하면 거짓 통과로 보입니다.
세 개의 작은 과제 결과는 복잡한 프로젝트의 성능을 대표하지 않습니다.

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

## 사전 준비(setup)

AI 에이전트는 의존성을 설치하지 못합니다. 프로젝트에 필요한 설치·준비는 사람이 `harness.toml`에 선언하고,
하네스가 **새 실행의 계획 단계 전에 한 번** 실행합니다. 셸 문자열이 아니라 인자 배열만 허용합니다.

```toml
[[setup]]
name = "install"
command = ["{python}", "-m", "pip", "install", "-r", "requirements.txt"]
timeout = 600   # 선택, 초 단위. 기본 600
```

- 실패·시간 초과면 에이전트를 부르기 전에 중단합니다(종료 코드 2). 성공한 setup은 상태에 기록해 `--resume`에서 다시 실행하지 않습니다.
  실패한 setup은 완료되지 않았으므로 `--resume`에서 다시 시도합니다.
- 실행 기록은 `.fusion/setup/`과 `events.jsonl`에 남습니다. `doctor`가 실행 파일 존재를 확인합니다.
- `harness.toml`을 바꾸면 이전 실행에 이어 붙일 수 없습니다. 명령은 신뢰하는 로컬 명령으로 취급합니다.
- `run`의 에이전트가 의존성을 설치하게 하는 기능은 없습니다. `.venv`·`node_modules`는 수정 감시에서 제외되어 있어 setup이 채워도 범위 위반이 아닙니다.
- generator가 스스로 빌드해 `dist/`·`build/`·`.next/`·`coverage/`를 만들어도 범위 위반이 아닙니다(빌드 산출물).

## 단계별 보고와 커밋·푸시

작업마다 평가가 끝나면 `[T1] PASS: verdict PASS, spec 3/3, test 3/3, criteria 3/3, checks ...` 형태로 결과를 출력하고,
실패한 기준과 지적 사항을 이어서 보여 줍니다. `init`은 아래 설정을 기본으로 넣습니다.

```toml
[git]
commit = true   # 통과한 작업마다 "T1: 제목"으로 커밋, 최종 통과 후 "FINAL: ..." 커밋
push = true     # 원격(origin 우선)이 있으면 푸시. commit = true가 필요
```

- `harness.toml`, `agents.toml`, `AGENTS.md`, `.fusion/`, `.env*`, 의존성·빌드 산출물 폴더는 커밋하지 않습니다.
- git 저장소가 아니거나 원격이 없거나 푸시가 실패해도 작업 판정은 바뀌지 않고, 출력과 `events.jsonl`(`git`)에 사유를 남깁니다.
- 저장소와 원격은 사람이 먼저 준비합니다(`git init`, `git remote add origin ...`). `[git]`이 없으면 커밋하지 않습니다.

## 도구 상태 폴더 무시(watch)

하네스는 Planner·Evaluator 단계의 모든 파일 변경과, Generator의 `touch` 밖 변경을 중단 사유로 봅니다.
편집기 훅(예: oh-my-claudecode의 `.omc/`)이나 CLI 캐시·로그(예: Expo의 `.expo/`)는 에이전트와 무관하게 바뀌므로
`harness.toml`에 적어 감시와 커밋에서 뺍니다. `init`은 아래 값을 기본으로 넣습니다.

```toml
[watch]
ignore = [".omc/", ".expo/"]
```

- 점(.)으로 시작하고 `/`로 끝나는 폴더만 허용합니다. 소스·`docs/`·`.claude/`·`.agents/`(스킬)·`.git`·`.fusion`·`.env`와
  수용 테스트 폴더는 무시할 수 없습니다.
- 무시한 폴더는 완료 digest에도 포함되지 않아, 실행 뒤 도구가 그 폴더를 바꿔도 DONE이 무효가 되지 않습니다.
- 검사 명령(테스트·빌드)도 `dist/` 등 빌드 산출물과 무시한 폴더 밖의 파일을 바꾸면 중단되므로,
  캐시·로그를 프로젝트 안에 남기는 명령은 출력 위치를 바꾸거나 해당 폴더를 `ignore`에 넣으세요.

## 수용 테스트 보호 폴더(선택)

사람이 쓴 테스트를 에이전트가 고치지 못하게 하려면 `init`에 `--acceptance`를 붙입니다
(또는 `harness.toml`에 `[acceptance] path = "acceptance"` 추가).

```powershell
.\.venv\Scripts\harness-fusion.exe init C:\claude-api\projects\my-project --backend agy --acceptance
```

- 폴더 안에 `test*.py` 등 사람이 쓴 테스트를 넣으세요. README.md만 있으면 실행을 시작하지 않습니다.
- 모든 역할(Planner·Generator·Evaluator)이 이 폴더를 수정·추가·삭제할 수 없습니다. 계획의 `touch`에 넣어도 막힙니다.
- 실행 시작 시 폴더 내용의 해시를 기록하고, 에이전트 호출·검사 뒤마다, 그리고 `--resume` 때 다시 비교해 달라졌으면 중단합니다.
- 폴더의 테스트는 **필수 검사에 자동으로 추가**됩니다(이름 `acceptance`). 테스트 0개나 전부 건너뛴 경우는 실패입니다.
- 한계: 파일 내용 비교 방식입니다. OS 보안 경계나 컨테이너 격리가 아니며, 테스트가 프로젝트 코드를 실행하는 점은 그대로입니다.
  사람이 직접 수정하면 해시가 달라져 이전 실행을 이어갈 수 없으니 새 프로젝트 폴더에서 시작하세요.

## 상태 확인과 재개

```powershell
.\.venv\Scripts\harness-fusion.exe status ..\my-project
.\.venv\Scripts\harness-fusion.exe run ..\my-project --resume
```

- `status`는 역할별 호출 수·소요 시간과, Claude가 제공하는 토큰·비용(`cost_usd`)을 `usage`로 보여 줍니다.
  Codex 사용량·잔여량은 CLI가 제공하지 않아 호출 수와 시간만 나옵니다.
- AI 계정의 **사용량 한도**를 만나면 중단 사유가 `USAGE_LIMIT:`으로 시작하고, CLI가 알려 준 해제 시각(있을 때)과
  `--resume` 안내를 남깁니다(`status`의 `halt_kind`·`retry_hint`). 한도로 끊긴 시도는 재시도 횟수에서 차감하지 않습니다.
  한도 판별은 CLI 오류 문구에 의존하는 최선의 방법이라, CLI 버전이 바뀌어 문구가 달라지면 일반 실패로 보일 수 있습니다.
- 작업 성공: 종료 코드 `0`. 실패·미완료·한도 도달: `2`. 키보드 중단: `130`.
- 사이클 제한은 한 번의 실행에 적용됩니다. 재시도 제한은 저장된 작업 전체에 적용됩니다.
- 중단 시 진행 상황을 저장하며 같은 역할 호출의 토큰 스트림을 복구하지는 않습니다.
- 최종 통합 평가 실패 후 재개하면 작업들을 다시 열고 남은 재시도 한도 안에서 수정합니다.
- PRD·AGENTS·설정이 바뀌면 이전 실행에 이어 붙이지 않습니다. 기록을 보존하고 새 작업 폴더에서 시작하세요.
- 완료 뒤 코드가 달라지면 기존 완료 상태를 유효하다고 간주하지 않습니다.

| 파일 | 목적 |
|---|---|
| `agents.toml` | 에이전트별 CLI·모델·effort |
| `.claude/skills/`, `.agents/skills/`, `skills-lock.json` | `prd`에서 설치한 프로젝트 스킬(에이전트 수정 불가) |
| `harness.toml` | 검사·시간·시도 한도·setup·수용 테스트 |
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
`[git]`을 켜면 통과한 작업마다 커밋하지만, 실패한 시도의 변경은 되돌리지 않으므로 시작 전 복원 지점은 직접 보관하세요.

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

- 0.1.0은 감독하에 쓰는 로컬 MVP입니다. 작은 과제(bench 3개, Codex·Claude 혼합 루프, 강제 종료 후 재개)로
  실제 Codex·Claude 계정 실행을 확인했지만, 큰 프로젝트에서의 성능은 검증하지 않았습니다. 자세한 범위는 `docs/VALIDATION.md`.
- Linux/Python 3.12와 Windows 11/Python 3.12에서 자체 테스트·데모를 실행했고, 실제 AI 실행은 Windows에서 했습니다. macOS 실기 검증은 남아 있습니다.
  GitHub Actions(`.github/workflows/test.yml`)가 Windows·Linux/Python 3.11–3.13에서 자체 테스트를 push마다 실행합니다. 현재 통과 여부는 저장소의 Actions 탭에서 확인하세요.
  agy 실행은 자동 테스트(대체 실행기)로 명령 구성과 응답 처리를 확인합니다. 실제 계정 실행 결과는 `docs/VALIDATION.md`에 아직 기록하지 않았습니다.
- 수정 감시는 파일 내용·권한의 전후 비교입니다. OS 보안 경계가 아니며 읽기·네트워크·폴더 밖 부작용을 차단하지 않습니다.
  `.git`, 가상환경, `node_modules`, 일부 캐시는 감시에서 제외합니다. 생성 뒤 원상복구한 일시적 수정도 잡지 못합니다.
- Codex는 계획·평가에 read-only, 구현에 workspace-write를 요청합니다. 사용자 CLI 정책은 그대로 적용합니다.
  Claude는 역할별 내장 도구를 제한합니다. agy는 계획·평가에 `--mode plan`, 구현에 `--mode accept-edits`(파일 수정만 허용,
  헤드리스에서 명령 실행은 자동 거부)를 씁니다. 이 제한을 호스트 전체 격리라고 간주하면 안 됩니다.
- agy 실행 파일이 PATH에 없으면 `~/.gemini/bin`에서 찾습니다(`doctor`가 경로를 보여 줌). 모델 ID와 지원 effort는 `agy models`로 확인하세요.
- 기본 Claude Generator는 읽기·쓰기·편집 도구만 사용합니다. 셸이 필요한 설치·마이그레이션은 사전 준비가 필요합니다.
- 검사 명령은 신뢰하는 로컬 명령으로 취급합니다. 소스/설정 변경을 검사 후 탐지하고 중단하며,
  `dist/`, `build/`, `.next/`, `coverage/` 산출물과 공통 캐시는 예외입니다.
- Generator가 수정 가능한 테스트의 충실도는 Evaluator가 검토합니다. 별도 불변 평가셋·컨테이너 격리는 후속 개선 항목입니다.
- 실행 로그에는 프롬프트·응답·검사 출력이 포함됩니다. 비밀정보가 섞인 작업 기록을 공개 저장소에 올리지 마세요.
- Claude가 제공하는 사용량/비용 필드와 agy의 입력·출력 토큰 수는 기록하지만 Codex 사용량과 구독 잔여량은 추정하지 않습니다.
- `prd`의 대화형 세션과 스킬 설치 단계는 사람이 실제 터미널에서 진행합니다. 자동 테스트는 대체 실행기로 권한 설정과 사후 검사만 확인합니다.

## 개발

검증 기록은 `docs/VALIDATION.md`에 있습니다.

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
harness-fusion demo ../fusion-demo-new
```

구조 설명은 `docs/ARCHITECTURE.md`, 에이전트별 역할·권한·지시문은 `agents/`, 원본과의 관계는 `docs/SOURCES.md`에 있습니다.
