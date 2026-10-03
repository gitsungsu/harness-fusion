# 하네스 에이전트 목록

Harness Fusion에 있는 에이전트 4개를 정리한 **읽기용** 문서입니다.
이 파일을 고쳐도 하네스 동작은 바뀌지 않습니다. 실제 동작은 아래 소스 파일이 정합니다.

| 에이전트 | 하는 일 | 파일 수정 | 문서 |
|---|---|---|---|
| Bootstrap | 대화로 PRD 작성 (`harness-fusion prd`) | `docs/PRD.md`만 | [bootstrap.md](bootstrap.md) |
| Planner | PRD를 작업(T1, T2…)으로 나눔 | 불가 (읽기 전용) | [planner.md](planner.md) |
| Generator | 작업 하나를 구현하고 테스트 작성 | 작업의 touch 경로만 | [generator.md](generator.md) |
| Evaluator | 작업별 검토 + 마지막 전체 검토(FINAL) | 불가 (읽기 전용) | [evaluator.md](evaluator.md) |

## 흐름

```
harness-fusion prd   →  Bootstrap  → docs/PRD.md
harness-fusion run   →  Planner → [작업마다: Generator → 검사(checks) → Evaluator] → Evaluator(FINAL) → DONE
```

## 모델을 바꾸려면 (설정은 한 곳)

- **새 프로젝트의 기본 모델**: [`src/harness_fusion/default_agents.toml`](../src/harness_fusion/default_agents.toml) 하나만 고칩니다. `init`이 이 값으로 `agents.toml`을 만듭니다.
- **이미 만든 프로젝트**: 그 프로젝트 폴더의 `agents.toml`을 고칩니다. 실행 중에 바꾸면 `--resume`이 거부되고 새 실행으로 시작해야 합니다.

이 폴더의 문서에는 모델 이름을 적지 않습니다.

## 원본 위치

- 역할별 지시문과 출력 형식: `src/harness_fusion/context.py`
- CLI 명령과 권한(sandbox, 허용 도구): `src/harness_fusion/providers.py`
- Bootstrap 지시문과 권한: `src/harness_fusion/bootstrap.py`
- 보호 파일 목록: `src/harness_fusion/filesystem.py` (`protected`)
- 기본 모델: `src/harness_fusion/default_agents.toml` (`config.py`의 `default_agents`가 읽음)
