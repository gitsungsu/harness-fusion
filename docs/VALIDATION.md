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
