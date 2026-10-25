# RAG 적재·검색과 오프라인 검증

2026-10-25 기준: 정책 청크와 캐시·Chroma 검색 구조를 오프라인 검증한 뒤, OpenAI 정책 벡터 11개 적재와 양성 검색 질문 14개 평가를 완료했다. 상위 4개 검색의 평균 Recall은 96.4%, 관련 조건 추가 후에는 100%였다. 답변 생성·근거 없음 거절·상담 API와 LangGraph 연결은 미검증이다. [실제 보고서](retrieval-evaluation.json)

## 데이터 흐름

사전 적재: 고정 정책 원문·검수 자료의 해시 확인 → 규칙 묶음당 청크 하나 → 제목·절 제목·공식 본문 임베딩 → 내용 기반 캐시 → Chroma 적재.

질문 처리: 질문 임베딩 → 최대 4개 검색 후보 → 관련 조건 묶음 추가 → 원문 출처 반환. 관련 조건 추가 후에는 4개를 초과할 수 있다. 검색 거리는 정답 확률이 아니며 검색 성공만으로 답변 가능한 것으로 판단하지 않는다.

- 3문서의 검수 규칙 11개를 분할 없이 보존한다. 본문 4,000자 초과 시 자동 절단 대신 오류 처리한다. 오버랩은 없다.
- 검수 의견은 임베딩·인용하지 않는다. 제목·URL·수집일·시행일 필드를 구분하며 현재 시행일은 확인되지 않아 null이다.
- 캐시 경로는 제공자·모델·차원과 입력 내용 해시로 분리한다. 인덱스 식별자에는 청크 산출물 해시와 임베딩 구성이 반영된다.
- 테스트 벡터는 문장 해시로 만든 16차원 값이다. 의미를 이해하지 않으므로 자연어 검색 정확도 평가에 사용하지 않는다.

## 테스트와 서비스의 구분

| 구분 | 오프라인 테스트 | 실제 서비스용 |
|---|---|---|
| 임베딩 | OfflineTestEmbeddings | OpenAI 임베딩 |
| 인덱스 경로 | data/runtime/chroma-offline | data/runtime/chroma |
| 코드 | 동일한 청킹·캐시·PolicyIndex | 동일한 청킹·캐시·PolicyIndex |
| 목적 | 저장·재사용·검색·출처 전달의 구조 검증 | 자연어 의미 검색 |

서비스 코드가 테스트 인덱스로 자동 대체하지 않는다. 실서비스용 임베딩을 준비할 때 코드를 다시 구현하는 것이 아니라 같은 청크에서 실제 벡터와 인덱스를 생성한다. 모델이 달라 벡터는 재사용할 수 없다.

## 고정 벡터와 복원

`artifacts/embeddings.jsonl`에는 실제 Chroma에서 내보낸 정책 벡터 11개를 저장한다. `artifacts/index_manifest.json`은 말뭉치·청킹·입력 청크 해시·제공자·모델·차원·벡터 파일 해시·거리 기준(cosine)을 연결한다. JSONL 약 350KB로 관리하며 로컬 Chroma 폴더는 Git에 넣지 않는다. 해시는 우발적 손상과 버전 불일치를 감지하며 외부 서명이나 신뢰 인증을 대신하지 않는다.

```powershell
# 준비된 실제 인덱스에서 고정 벡터 내보내기: API 호출 없음
.\.venv\Scripts\python.exe -m scripts.rag export
# 기본 서비스 경로에 복원: API 키·캐시 불필요
.\.venv\Scripts\python.exe -m scripts.rag restore
# 기존 인덱스를 보존하고 별도 빈 경로에 복원
.\.venv\Scripts\python.exe -m scripts.rag restore --index-dir data/runtime/chroma-restored
```

복원은 파일 전체의 버전·해시·ID·차원·입력 해시·유한/비영 벡터를 검증한 뒤, 없는 항목만 명시적 벡터로 추가한다. 기존 데이터와 충돌하면 덮어쓰거나 삭제하지 않고 중단한다. 같은 파일의 재복원은 신규 적재 0개다. `--index-dir`은 data/runtime 하위만 허용한다. 실제 배포 시작 시 자동 복원 연결과 컨테이너 검증은 배포 일차에서 수행한다.

정책 벡터 복원과 질문 임베딩은 별개다. 복원에는 API가 필요 없지만 새로운 자연어 질문의 벡터 생성은 OpenAI API가 필요하다. 평가 질문 캐시는 로컬 전용이며 고정 정책 산출물에 포함하지 않는다. [복원 검증 보고서](rag-restore-validation.json)

## 검색 도구 계약과 실패

LangChain `search_policy`는 query 1~1,000자(공백만 입력 금지), 선택 topic을 받는다. 잘못된 타입·초과 길이·허용하지 않은 topic/필드는 조회 전에 거부한다. 결과의 candidates는 근거 후보이며 답변 가능 판정이 아니다. 준비되지 않은 인덱스·API 비허용 캐시 미스는 not_ready, 기타 시스템 예외는 error로 반환한다. 원시 오류/키/경로는 노출하지 않고, 오류를 정책 근거 없음으로 바꾸지 않는다. 상담 응답의 최종 상태 매핑은 3일차에 연결한다.

## API 없는 실행

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.rag prepare
.\.venv\Scripts\python.exe -X utf8 -m scripts.rag offline-smoke
.\.venv\Scripts\python.exe -m pytest tests/test_rag.py -q -p no:cacheprovider --basetemp data/runtime/pytest-rag-check
```

offline-smoke는 동일 입력의 벡터 조회와 반품 관련 조건 확장을 확인하며 자연어 의미 검색 점수를 산출하지 않는다. 별도 프로세스에서 재실행해도 기존 인덱스·캐시를 재사용한다. 실행 보고서는 Git 제외 `.cache/rag-offline-report.json`에 있다.

실제 API 호출은 기본 비활성이다. 명시적 API 허용 없이 캐시에 없는 벡터를 요청하면 중단한다. 사용자 키 설정 후 이번 적재·평가에만 API를 허용했고 기본 설정은 유지했다. `scripts.rag build --allow-api`, `scripts.rag evaluate --allow-api`로 실행할 수 있다. 캐시에 없는 새 질문은 별도 허용이 필요하다. [실행 결과](devlog/day02-2026-10-25.md)
