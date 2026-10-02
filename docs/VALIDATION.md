# 검증 결과 — 2026-10-02

## 실제 실행한 항목

| 항목 | 결과 |
|---|---|
| Python 소스 문법 검사 | 통과 |
| 자체 회귀 테스트 | 42개 통과 |
| wheel 빌드 | `harness_fusion-0.1.0-py3-none-any.whl` 생성 |
| 새 가상환경에 wheel 설치 | 의존성 다운로드 없이 설치 성공 |
| 설치된 패키지로 회귀 테스트 재실행 | 42개 통과 |
| 설치된 CLI로 SQLite 데모 | 1차 테스트 실패, 2차 수정 성공, 최종 통합 평가 통과 |
| 완료한 데모의 `--resume` | 검사·최종 평가를 재실행하고 성공 |
| `status` | DONE, 2회 시도, 현재 파일과 검증 해시 일치 |
| `doctor` | 구성된 스크립트 에이전트와 검사 실행 파일 발견 |

환경은 Linux / Python 3.12.14입니다. 에이전트 시뮬레이션과 실제 Python 검사 프로세스를 함께 사용했습니다.

## 회귀 검증이 다루는 문제

- 검사 없음·실패한 검사를 PASS로 바꾸려는 평가·낮은 점수·미해결 문제.
- `PASS` 단독 응답·중복 JSON 키·이전 호출 토큰·기준 불일치.
- 작업 없음·순환 의존성·중복 작업·위험한 경로 범위.
- 기존 dirty 파일 재수정·추가·삭제·권한 변경·보호 파일 수정.
- symlink 거부·원자적 상태 저장·오류 뒤 잠금 해제.
- 제한된 재시도·프로토콜 오류 후 재개·최종 평가 실패 후 작업 재개.
- 완료 이후 코드/요구사항 변경에 대한 과거 완료 무효화.
- 실행 파일 누락·타임아웃·과도한 출력·한글 stdin·테스트 0개·모두 건너뛴 테스트.

## 아직 검증하지 않은 항목

- 실제 Claude Code / Codex CLI 로그인·모델 응답·계정별 권한.
- Windows/macOS 실기 실행과 Windows 프로세스 트리 종료.
- 원격 GitHub Actions. 워크플로 파일만 작성했습니다.
- 복잡한 FastAPI·프런트엔드·기존 대규모 저장소를 AI로 생성·수정하는 성능.
- 악의적인 에이전트에 대한 OS 격리. 현재 수정 감시는 보안 샌드박스가 아닙니다.

테스트 수는 하네스 엔진 회귀 테스트 개수이며 모델 품질 또는 복잡한 앱 완성률을 의미하지 않습니다.

## 2026-10-02 추가 검증 — Windows 11 / Python 3.12.3

| 항목 | 결과 |
|---|---|
| 새 `.venv`에 `pip install -e .` 후 자체 테스트 | 49개 통과, 2개 건너뜀(POSIX 파일 모드·심볼릭 링크 권한) |
| `harness-fusion demo` | 1차 테스트 실패 → 2차 수정 → 최종 평가 통과(DONE) |
| 완료한 데모 `status` / `run --resume` | 파일 해시 일치, 재개 성공(종료 코드 0) |
| Codex CLI 0.159.3 (`codex exec --help`) | `--skip-git-repo-check`, `--sandbox`, `--output-last-message`, `--model`, stdin(`-`) 모두 존재 |
| `codex login status` | ChatGPT 로그인 확인 |
| `doctor` (codex 프로필) | Windows `codex.cmd`를 Node 진입점으로 해석 |
| 실제 `run` (codex, PRD: slugify) | **ChatGPT 사용량 한도로 계획 단계에서 중단**, fail-closed로 종료 코드 2 |

### 발견·수정한 오류

- Codex는 stderr에 프롬프트 전체를 에코한다. 하네스는 stderr 마지막 2000자를 중단 사유로 붙여서,
  실제 원인(`ERROR: ... usage limit`)이 프롬프트 JSON 뒤에 묻혔다.
  `providers.failure_detail`이 `ERROR` 줄을 중복 없이 우선 표시하도록 수정하고
  `test_failure_message_surfaces_error_lines_not_prompt_echo` 회귀 테스트를 추가했다.

### 여전히 검증하지 못한 항목

- 사용량 한도 때문에 Codex의 계획 JSON, 구현, 독립 평가, `--output-last-message` 파싱, 실제 모델 응답을 통한 재개는 **실행하지 못했다.**
- Claude Code 백엔드의 실제 실행.
- 원격 GitHub Actions, macOS.

## 2026-10-02 추가 구현 — 사전 준비(setup)와 수용 테스트 보호

CHECK.md 3번·4번 항목을 구현했다. Windows 11 / Python 3.12.3, 자체 테스트 73개 통과(2개 건너뜀).
실제 Codex·Claude 호출은 이 구현의 검증에 쓰지 않았다(스크립트 에이전트와 실제 Python 검사 프로세스 사용).

| 항목 | 확인한 것 |
|---|---|
| `[[setup]]` | 계획 전 1회 실행, 재개 시 재실행 안 함, 실패·시간 초과 시 에이전트 호출 전 중단, 실패 setup은 재개에서 재시도, `node_modules` 채우기 허용, 설정 변경 시 재개 거부, 문자열 명령·알 수 없는 키·잘못된 timeout 거부 |
| `[acceptance]` | 경로 검증, 검사 자동 추가, 폴더 없음/README만 있음 중단, 약화·추가·삭제 시 중단(계획 `touch`에 넣어도 동일), 실행 사이 수정 시 재개 거부, 실패한 수용 테스트가 PASS 평가를 이김, 전부 건너뜀은 실패, 프롬프트에 읽기 전용 안내, `init --acceptance`는 기존 폴더를 덮어쓰지 않음 |
| 변이 확인 | 잠금 접두사 로직과 해시 가드를 각각 일부러 껐을 때 해당 테스트가 실패함을 확인한 뒤 복구 |
| CLI | `init --acceptance`, `doctor`(테스트 없음 경고), 테스트 없는 `run` 중단(종료 코드 2), `demo` 정상 |

한계: 해시 비교는 OS 격리가 아니다. setup 명령은 신뢰하는 로컬 명령이며 에이전트의 설치 권한은 계속 막혀 있다.

## 2026-10-02 실제 AI 전체 루프 검증 (CHECK.md 1번)

환경: Windows 11, Python 3.12.3, Codex CLI 0.159.3(ChatGPT 로그인), Claude Code 2.1.286(claude.ai 로그인).
모두 작은 단일 과제 1회씩의 실행이다. AI의 개발 성능을 증명하지 않으며, 하네스 동작 확인이다.

| 구성 | 과제 | 결과 |
|---|---|---|
| A. Codex 단독 (모델 미지정 → Codex 기본 `gpt-6-astra`, medium) | slugify | 1회 시도로 DONE, 4분 17초. Planner 51초 → Generator 91초 → 검사 통과 → Evaluator 52초 → 최종 검사 → 최종 Evaluator 62초. `status` DONE, 파일 해시 일치 |
| A-재개. Codex 단독, **강제 종료 후 재개** | wordcount | Planner 완료 후 Generator 실행 중 프로세스 트리를 강제 종료(상태 `IMPLEMENTING`, 계획 저장됨). `run --resume`이 **Planner를 다시 부르지 않고** Generator 2번째 시도부터 이어 DONE, 3분 0초, 해시 일치 |
| B. 혼합: Planner·Evaluator = Codex `gpt-6.1-sol`, Generator = Claude(모델 미지정, CLI 기본) | rpn (2개 작업) | T1·T2 모두 첫 시도 통과 후 최종 평가까지 DONE, 5분 3초, 해시 일치. Claude 응답의 JSON 봉투 파싱 동작, 호출 비용(약 $0.55, $0.40)이 이벤트에 기록됨 |

확인된 것
- Codex `--output-last-message` 응답과 Claude `--output-format json` 응답이 모두 실제 응답에서 파싱됐다.
- Codex에 `--model gpt-6.1-sol` 인자 전달이 CLI 0.159.3에서 동작했다.
- 강제 종료 뒤 재개: 잠금이 풀려 있었고, 저장된 계획을 재사용했다.
- 이번 실행에서 새로 발견된 하네스 오류는 없었다. (앞서 발견한 한도 오류 메시지 문제는 수정·테스트 완료)

한계·관찰
- B의 Claude Generator는 모델을 지정하지 않아 사용자 설정의 별칭(`sonnet`)이 적용됐다. 실제 해석된 버전은 기록되지 않았다. `claude-sonnet-5-5` 고정은 이후 템플릿에 반영했으나 그 설정으로 실행한 증거는 아직 없다.
- 평가 품질(Evaluator가 정확히 판정했는가)은 평가 JSON의 형식·게이트 통과만 확인했고, 테스트 충실도 자체를 독립 검증하지는 않았다.
- Windows에서 stdout을 파일로 리다이렉트하면 로케일 인코딩(cp949)으로 쓰인다. 프로젝트 파일(docs 등)은 UTF-8로 정상 저장된다.
- 한도에 다시 걸리는 경우의 동작은 이번에는 재현하지 않았다(2번 항목에서 다룸). 큰 프로젝트, macOS, 원격 CI는 검증하지 않았다.

## 2026-10-02 추가 구현 — 사용량 한도 가드 (CHECK.md 2번)

자체 테스트 88개 통과(2개 건너뜀). 실제로 한도에 다시 걸린 상태에서 실행한 것은 **아니다**(한도는 이미 풀린 상태).
한도 오류 처리는 실제 Codex 한도 메시지 문구를 쓴 가짜 호출과 mock한 Claude 응답으로 검증했다.

- 한도 감지: Codex 오류 문구(`try again at 11:33 PM`)와 Claude 문구(`resets 5pm`) 형태에서 해제 시각을 읽는다. 일반 오류는 한도로 오인하지 않는다.
- 중단 사유가 `USAGE_LIMIT:`으로 시작하고 `--resume` 안내가 출력·상태에 남는다. 종료 코드는 2 그대로다.
- 한도로 끊긴 시도는 재시도·사이클 횟수에서 차감하지 않는다(5회 반복 후에도 예산 유지, Planner·Generator·Evaluator 각 단계 재개 확인).
- `status`가 역할별 호출 수·시간·Claude 토큰·비용을 보여 준다. 실제 혼합 실행(`fusion-mixed-rpn`)에서 Claude 비용 합계 약 $0.95가 집계됨을 확인했다.
- 변이 확인: 차감 방지 로직을 끄면 관련 테스트 2개가 실패함을 확인한 뒤 복구.

한계: 한도 판별은 CLI 오류 문구에 의존한다. 호출 횟수 상한과 Claude 비용 상한(선택 항목)은 구현하지 않았다.


## 2026-10-02 추가 구현 — bench(5번)와 effort·PRD 점검(6번)

자체 테스트 116개 통과(2개 건너뜀), Windows 11 / Python 3.12.3.

### bench 실제 실행 결과 (Codex, 모델 `gpt-6.1-sol`, 각 케이스 1회)

| 케이스 | 엔진 판정 | 숨은 채점 | 사이클 | 에이전트 호출 | 소요 |
|---|---|---|---|---|---|
| rpn | DONE | 통과 | 3 | 8 | 554초 |
| slugify | DONE | 통과 | 2 | 6 | 358초 |
| wordcount | DONE | 통과 | 2 | 6 | 384초 |

- 3개 모두 엔진 DONE이고 숨은 채점도 통과했다. **거짓 통과(엔진 DONE, 숨은 채점 실패)는 이 실행에서 0건이었다.** 1회씩의 소형 과제 결과이며 일반 성능이 아니다.
- 이 실행의 effort는 하네스가 지정하지 않았고 사용자 전역 Codex 설정의 `medium`이 적용됐다(effort 지원은 이후 구현).
- PRD·채점 단언은 harness-v2 `evals/`의 것을 가져오되 실행 방식만 `uv run`→`python -m`, pytest→unittest로 바꿨다. v2 결과와 직접 비교할 수 없다.
- 파이프라인 자체는 AI 없이 검증했다: 참조 구현 3개는 숨은 테스트를 통과, 틀린·없는 구현은 실패, 약한 구현이 엔진 DONE이어도 숨은 채점에서 걸러짐, 목록 모드는 아무것도 실행하지 않음.

### effort

- 허용값 `low·medium·high·xhigh·max`. Codex 모델 카탈로그(`gpt-6.1-sol`)가 `ultra`까지 지원하지만 `ultra`는 자동 subagent 위임이라 거부한다.
- 실제 CLI 확인: Codex는 `-c model_reasoning_effort="high"`로 `model: gpt-6.1-sol / reasoning effort: high`가 적용됨을 출력으로 확인(전역 `medium`을 덮어씀).
  Claude는 `--model claude-sonnet-5-5 --effort medium` 호출이 오류 없이 응답했다(계정에서 모델 사용 가능). Claude의 effort가 실제 반영됐는지는 출력으로 확인하지 못했다.
- init 템플릿이 모든 역할에 `effort = "medium"`을 기록하고 `events.jsonl`에 호출마다 effort를 남긴다.

### PRD 템플릿·점검

- `init`(목표 없음)이 `목표/입력과 출력/완료 기준/테스트 방법` 섹션 템플릿을 만든다. `TODO:`가 남으면 실행 거부(기존 동작 유지).
- 완료 기준·테스트 방법 언급이 없거나 TODO가 남아 있으면 `doctor`와 `run`이 경고한다. 경고는 실행을 막지 않는다. 단어 검색이므로 PRD 품질 보증이 아니다.

### 이번 작업 중 발견·수정한 오류

- 한국어 Windows 콘솔(cp949)에서 인코딩할 수 없는 문자(예: em dash)를 `print`하면 예외가 났다. 모델이 쓴 작업 제목에도 발생해 실행이 HALTED될 수 있었다. `main()`이 stdout/stderr를 `errors="replace"`로 재설정하도록 수정하고 회귀 테스트 추가.
- `test_process.test_timeout_fails`가 임시 폴더 정리 중 간헐 실패(방금 종료한 프로세스가 cwd를 잠시 점유). 테스트 정리 오류만 무시하도록 수정. 수정 뒤 6회 연속 통과했으나 영구 보장은 아니다.
- 데모가 새 템플릿의 `effort`/`model` 줄 때문에 깨지는 회귀를 기존 테스트가 잡아 수정.
- `doctor`가 채우지 않은 PRD 템플릿에 `prd: ok`를 출력하던 것을 TODO 경고로 수정.

## 2026-10-02 추가 구현 — 에이전트별 설정 파일 `agents.toml`

자체 테스트 130개 통과(2개 건너뜀). 실제 AI 호출로 이 구조를 검증한 것은 **아니다**(설정 로딩·보호·재개는 스크립트 에이전트와 CLI로 확인).

- `init`이 `agents.toml`(`[planner]/[generator]/[evaluator]`, 에이전트별 backend·model·effort)을 만들고 `harness.toml`에서는 `[agents]`를 뺀다.
- 두 파일에 모두 정의하면 오류, 누락·알 수 없는 섹션/키/백엔드·`ultra` effort도 오류. `agents.toml`이 없는 기존 프로젝트의 `harness.toml [agents]`는 그대로 동작함을 실제 프로젝트(`fusion-mixed-rpn`)의 `doctor`/`status`로 확인했다.
- 에이전트별로 서로 다른 모델·effort가 적용되고 `events.jsonl`에 호출마다 기록됨을 확인했다.
- `agents.toml`은 모든 역할이 수정할 수 없는 보호 파일이고, 변경하면 재개가 거부된다. 보호·지문 로직을 일부러 끄면 각 테스트가 실패함을 확인한 뒤 복구했다.
- 데모와 `doctor`(정의 위치 표시)도 새 구조에서 동작한다.

한계: 설정 파일이 더 늘어난 만큼 `harness.toml`의 `[agents]`와 혼동할 수 있어 이전 프로젝트는 마이그레이션하지 않고 그대로 둔다.

## 2026-10-02 추가 구현 — bootstrap(PRD 인터뷰) 에이전트와 planner 기본값

자체 테스트 154개 통과(2개 건너뜀: Windows에서 실행 불가한 POSIX 파일 권한·심볼릭 링크 테스트).

### bootstrap 에이전트 (`harness-fusion prd`)

- `agents.toml`의 `[bootstrap]`(기본 `claude` / `claude-opus-5-5` / effort `high`)으로 대화형 `claude` 세션을 열어 `docs/PRD.md`를 작성한다.
  backend는 claude만 허용하고, `run`의 세 역할과는 분리돼 있다.
- 자동 허용 도구: 읽기(Read·Glob·Grep)와 `docs/PRD.md` 쓰기·편집만. 셸 도구 없음, 권한 우회 플래그 없음.
  세션 뒤 PRD 외 파일이 바뀌었거나, PRD가 안 쓰였거나, `TODO:`가 남았거나, claude가 비정상 종료하면 실패(종료 코드 2). 되돌리지는 않는다.
  이미 `run`을 시작한 프로젝트에서는 거부한다. 터미널이 아니면 실행하지 않는다.
- 실제 확인(같은 명령에 `-p`만 붙여 비대화형으로 실행):
  - 답변을 한 번에 준 호출: `claude-opus-5-5`로 응답, 바뀐 파일은 `docs/PRD.md`뿐, 템플릿 섹션(목표·입력과 출력·완료 기준·테스트 방법·범위 밖)과
    "열린 질문"을 갖춘 PRD 작성. 약 54초, $0.73.
  - PRD 외 파일 생성과 `agents.toml` 수정을 요구한 호출: 아무 파일도 바뀌지 않았다. 단, 모델이 지침에 따라 스스로 거절한 것이며
    (permission_denials 없음) 도구 차원의 차단을 따로 입증한 것은 아니다. 그 경우의 보호는 세션 후 변경 파일 검사다.
- **검증하지 못한 것:** 사람이 실제 터미널에서 질문에 하나씩 답하는 대화형 세션 자체. 이 환경에는 대화형 터미널이 없다.

### planner 기본값 변경

- `init`이 만드는 `agents.toml`의 planner 기본값: `claude` / `claude-sonnet-5-5` / effort `high`
  (처음 `xhigh`로 바꿨다가 요청에 따라 `high`로 조정). generator·evaluator는 `init --backend` 값을 따른다.
  bench는 조건 고정을 위해 세 역할을 한 backend로 통일한 템플릿을 쓴다.
- 기존 프로젝트의 설정은 바꾸지 않았다(설정이 바뀌면 이전 실행에 이어 붙일 수 없으므로).

### Claude planner 실제 실행 (fusion-bootstrap-smoke, 위 인터뷰로 만든 calculator PRD)

구성: planner = Claude `claude-sonnet-5-5` / **xhigh**(high로 바꾸기 전 설정), generator·evaluator = Codex `gpt-6.1-sol` / medium.

- planner(Claude)는 43.8초에 유효한 계획 JSON(작업 3개)을 냈다. Claude를 planner로 실제 실행한 첫 확인이다. 비용 약 $0.53.
- T1 첫 평가에서 Codex Evaluator가 **32자리 호출 토큰을 잘못 옮겨**(`…44ec846a…` → `…44ec44ec846a…`) 하네스가 `Stale or mismatched review`로 중단했다.
  평가 내용은 PASS였고 기준 8개도 정확히 옮겼다. 하네스는 설계대로 fail-closed 동작했다. 지금까지 실제 Evaluator 호출 중 처음 발생한 사례다.
- 토큰을 12자리로 줄이는 수정을 했다가 사용자 요청으로 되돌렸다. **현재 코드는 32자리 그대로이며 이 문제는 해결되지 않았다.** 다시 발생하면 `--resume`으로 이어간다.
- `--resume`으로 이어 간 실행은 되돌리기 **전** 코드(12자리 토큰)로 시작했다. 따라서 그 결과는 현재 코드의 검증이 아니다.
  이 실행에서 T1(2번째 시도)·T2·T3 평가가 모두 통과했다. 최종 결과는 아래에 덧붙인다.

### 발견한 작은 문제 (미수정)

- 중단 후 `--resume`으로 다시 실행하는 동안 `status`의 `reason`에 이전 중단 사유가 그대로 남는다(예: 실행은 `FINAL_CHECK` 진행 중인데 `reason`은 `Stale or mismatched review`).
  완료 판정에는 영향이 없지만 상태를 오해하게 만든다. 재개 시작 시 사유를 비우는 수정과 회귀 테스트가 필요하다.
- 재개 실행 최종 결과: **DONE**(종료 코드 0, 8분 27초). T1 2회·T2 1회·T3 1회 시도, 최종 통합 평가 통과, 파일 해시 일치.
  에이전트 호출: planner 1(Claude, 약 $0.53), generator 4, evaluator 5(Codex). 재개 이후 12자리 토큰 5회는 모두 정확히 복사됐다(되돌린 코드 기준, 참고용).
  위 `reason` 문제는 DONE 상태에서도 재현됐다: `status`가 `DONE`인데 `reason`이 `Stale or mismatched review`로 남아 있다.
