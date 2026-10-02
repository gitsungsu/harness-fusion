# Codex 작업 인계

## 사용자 목표

`gitsungsu/harness-v2`, `ai-boost/awesome-harness-engineering`,
`walkinglabs/awesome-harness-engineering`의 장점을 결합한 새 하네스를 요청했다.
이후 Codex 데스크톱 앱/CLI에서 이어서 개발할 수 있는지 물었다.
사용자는 비개발자이며 한국어로 명확한 실행 순서와 검증 결과를 원한다.

## 현재 결과

프로젝트명 `harness-fusion`, 버전 0.1.0. Python 3.11+ 표준 라이브러리 기반 로컬 MVP.
계획→구현→검사→평가→최종 검증, 내용 기반 수정 감시, JSON 계약,
시간·시도 제한, 상태 재개, 최근 기억, CLI 연결 및 계정 없는 데모가 구현되어 있다.
원본 harness-v2는 수정하지 않았다. 외부 GitHub 저장소를 생성하거나 push하지 않았다.

## 먼저 실행

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\harness-fusion.exe demo ..\fusion-demo-codex
```

Python 설치 버전에 맞게 `-3.11`을 변경한다. 데모 대상은 새 폴더를 사용한다.
Linux/macOS는 `.venv/bin/python`, `.venv/bin/harness-fusion`을 사용한다.

## 검증 범위

작성 환경: Linux, Python 3.12.14.
자체 회귀 테스트 42개 통과. SQLite 스크립트 데모에서 실제 테스트 실패→수정→통과→최종 평가 확인.
최종 패키지 검증 상세는 `docs/VALIDATION.md`에 기록한다.

**2026-10-02 Windows 11 검증: 자체 테스트 49개·데모·재개 통과. 설치된 Codex CLI 0.159.3은 플래그 호환·로그인 확인, 실제 `run`은 ChatGPT 사용량 한도로 계획 단계에서 중단(미완료). 한도 해제 후 `fusion-codex-real` 예제를 다시 실행해야 한다. 자세한 내용은 docs/VALIDATION.md.**
이전 작성 환경(Linux)에서는 CLI가 없어 유료 모델 연결을 실행하지 않았다.
Windows/macOS에서 직접 실행하지 않았고 GitHub Actions도 아직 실행하지 않았다.
CLI 인자 구성은 공식 문서와 코드 검사로 확인했지만 실제 계정·버전별 호환성을 보장하지 않는다.

## 다음 작업 우선순위

1. 사용자의 Codex/Claude CLI 설치·로그인 상태를 확인하고 별도 작은 프로젝트에서 실제 전체 루프 실행.
2. 설치된 버전의 `--help`로 플래그 호환성 검증. CLI별 출력·권한·타임아웃 동작을 회귀 테스트로 남기기.
3. Windows PowerShell과 WSL 실행 검증. `codex.cmd`/`npm.cmd`, 프로세스 트리 종료, 파일 잠금 확인.
4. FastAPI·SQLite API 및 기존 코드 수정 시나리오로 실전 평가 확대. Node 프로필은 테스트 명령을 해당 도구에 맞추기.
5. 생성자가 수정할 수 없는 별도 수용 테스트와 격리된 검사 실행 환경을 설계·추가.
6. 장기 작업에 필요한 재계획·의존성 설치 정책·Git 복원 지점은 별도 기능으로 설계. 현재 자동 구현됐다고 주장하지 않기.

## 유지할 핵심 원칙

- 외부 검사가 실패했는데 AI가 PASS라고 해도 실패.
- 검사 미설정·테스트 0개·형식 오류·오래된 평가를 성공으로 취급하지 않기.
- Git dirty 파일 목록만 비교하지 말고 파일 내용 전후를 비교하기.
- 상태·평가 원문·실행 근거를 남기고 무한 재시도 금지.
- 실제로 테스트한 환경과 아직 확인하지 못한 환경을 구분하기.
- 사용자 기존 파일을 임의로 덮어쓰거나 자동 롤백하지 않기.

## Codex에 붙여넣을 요청

> 이 폴더의 AGENTS.md와 HANDOFF.md를 먼저 읽어줘. Harness Fusion의 현재 구현과 검증 결과를 확인하고,
> 자체 테스트와 데모를 실행해줘. 이후 사용 가능한 Codex CLI로 작은 예제를 실제 실행하여 연결·평가·재개
> 동작을 검증하고 발견한 오류를 수정해줘. 실제로 확인한 결과와 아직 남은 한계를 한국어로 설명해줘.
> 원본 harness-v2 수정이나 GitHub push는 별도 요청 전에는 하지 마.
