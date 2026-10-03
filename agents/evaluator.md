# Evaluator (검토 에이전트)

## 하는 일
두 번 등장합니다.
1. **작업별 검토**: Generator가 끝나고 검사가 실행된 뒤, 그 작업이 완료 기준을 모두 채웠는지 판정합니다.
2. **최종 검토(FINAL)**: 모든 작업이 통과하면 PRD 전체와 작업 사이 연동을 한 번 더 확인합니다. 여기서 FAIL이면 DONE이 아닙니다.

## 모델 설정
기본값은 [`src/harness_fusion/default_agents.toml`](../src/harness_fusion/default_agents.toml)의 `[evaluator]`, 프로젝트별 값은 그 프로젝트 `agents.toml`의 `[evaluator]`입니다.

## 권한: 읽기 전용
- codex: `--sandbox read-only`
- claude: `--tools Read,Glob,Grep`
- 실행 뒤 바뀐 파일이 하나라도 있으면 하네스가 중단합니다.

## 지시문 (원문)
```
Read actual source and tests; do not trust implementation summaries alone. Do not edit files.
The supplied checks were executed by the engine. Evaluate every acceptance criterion in order.
Score spec and test coverage 0–3; 2 is adequate, 3 is thorough.
Weak/empty tests, unmet requirements, failed checks or unresolved blockers mean FAIL.
For FINAL, check the complete PRD including interactions across tasks.
Copy token and task_id exactly; never reuse an older review.
```

## 돌려줘야 하는 JSON
```json
{
  "token": "COPY_FROM_REQUEST", "task_id": "COPY_FROM_REQUEST",
  "verdict": "PASS or FAIL or BLOCKED", "spec_score": 0, "test_score": 0,
  "criteria": [{"criterion": "exact acceptance text in order", "passed": false,
                "evidence": "file/test name and observed evidence"}],
  "issues": ["actionable blocking issue; empty only if no blockers"]
}
```

## 하네스가 PASS로 인정하는 조건
아래를 모두 만족해야 합니다. 하나라도 어긋나면 FAIL이나 중단으로 처리합니다.
- token과 task_id가 이번 요청과 정확히 같아야 합니다. 이전 리뷰를 다시 쓰면 거부됩니다.
- criteria는 완료 기준과 같은 순서·같은 문장이어야 하고 모두 passed여야 합니다.
- verdict가 PASS이고, spec_score와 test_score가 모두 2 이상이고, issues가 비어 있어야 합니다.
- 하네스가 직접 실행한 검사(checks)가 모두 통과해야 합니다. 리뷰어가 PASS라고 해도 검사가 실패하면 FAIL입니다.

원본: `src/harness_fusion/context.py`, `src/harness_fusion/providers.py`
