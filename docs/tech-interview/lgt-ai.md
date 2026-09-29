# AI 연동 담당 예상 문답

[문답집 목차](README.md)

기준: `refactor/bsg-back/app-refactoring`, 커밋 `fcbb7e5c82c59996d92fd77c258b8e02fbfd2da3`. 문서상 AI 역할은 김도희이며, 아래 설명은 현재 통합 코드의 동작을 기준으로 합니다. 개별 함수의 작성자를 판정한 자료는 아닙니다. 설정값은 코드의 기본값이고, 배포 환경의 실제 값과 모델 사용 가능 여부는 별도 확인이 필요합니다.

## A01. 이 프로젝트에서 AI 담당은 모델을 직접 학습시켰나요?

**답변:** 현재 구현은 학습된 외부 AI 모델의 API를 호출해서 답변을 받는 방식입니다. AI 연동 모듈은 현재 질문과 이전 대화를 요청 형식으로 만들고, 모델 호출·응답 해석·오류 분류·재시도와 대체 모델 호출을 담당합니다. 사용자 인증, DB 저장, HTTP 응답 변환은 다른 계층이 맡습니다. 현재 경로에는 모델 학습, 외부 문서 검색을 붙이는 RAG, 답변을 조각별로 보내는 스트리밍 구현이 없습니다.

**꼬리질문:** 대화 기록을 보내는 것도 모델 학습 아닌가요?  
**짧은 답변:** 여기서는 요청할 때 참고할 문맥으로 전달하며, 모델의 가중치를 변경하는 학습 코드는 없습니다.

**코드 근거:** [AI_connect.py](../../app/services/AI_connect.py)의 `build_contents()`, `_call_once()`, `generate_answer()`; [chat_main.py](../../app/services/chat_main.py)의 `chat()`.

## A02. AI API 키와 사용할 모델은 어디서 설정하나요?

**답변:** 서버의 `config.py`가 환경 변수에서 `AI_API_KEY`, `AI_MODEL`, `AI_FALLBACK_MODEL`을 읽고, 서버 내부에서 Google GenAI 클라이언트를 만듭니다. 코드 기본 모델명은 `gemini-3.8-flash`, 대체 모델명은 `gemini-3.1-flash-lite`이지만, 이것만으로 배포 서버의 실제 설정이나 호출 성공을 증명할 수는 없습니다. 키가 없거나 공백이면 SDK 호출 전에 `AI_CONFIG_ERROR`로 끝내며, 브라우저가 AI 키를 들고 공급자 API를 직접 호출하는 구조가 아닙니다.

**꼬리질문:** 키가 잘못됐을 때 대체 모델로 해결하나요?  
**짧은 답변:** 아니요. 401·403이나 확인 가능한 키 오류는 설정 오류로 분류하고, 같은 키로 재시도하거나 대체 모델을 호출하지 않습니다.

**코드 근거:** [config.py](../../app/core/config.py)의 AI 설정; [AI_connect.py](../../app/services/AI_connect.py)의 `_client()`, `_classify()`, `_call_once()`.

**검증 코드:** [test_ai_connect.py](../../tests/test_ai_connect.py)의 `test_missing_key_stops_before_sdk_without_fallback`, `test_invalid_key_stops_after_one_sdk_call`.

## A03. 챗봇은 이전 대화를 어떻게 기억하나요?

**답변:** `chat_main.chat()`이 인증된 사용자 ID와 요청의 `room_id`를 기준으로 DB에서 성공한 대화만 조회합니다. 기본적으로 최근 5개의 질문·답변 쌍을 가져온 뒤, 오래된 것부터 순서대로 AI에 전달하고 마지막에 현재 질문을 붙입니다. 같은 사용자의 다른 방이나 다른 사용자의 대화는 이 조회 조건에서 제외합니다. DB 조회가 실패하면 빈 문맥으로 진행하므로, 그 요청에서는 이전 대화를 이어서 답하지 못할 수 있습니다.

**꼬리질문:** `generate_answer()`에 `user_id`를 넘기기만 하면 사용자별 분리가 되나요?  
**짧은 답변:** 아니요. 실제 분리는 `chat_db.get_history()`의 사용자·방·성공 상태 필터가 수행합니다.

**코드 근거:** [chat_main.py](../../app/services/chat_main.py)의 `chat()`; [chat_db.py](../../app/services/chat_db.py)의 `get_history()`; [AI_connect.py](../../app/services/AI_connect.py)의 `build_contents()`.

**검증 코드:** [test_chat_api.py](../../tests/test_chat_api.py)의 `test_context_contains_only_own_room_successful_turns_in_chronological_order`.

## A04. 문맥 5턴, 6,000자, 출력 800토큰은 각각 무엇을 제한하나요?

**답변:** 기본 5턴은 이전 질문·답변 쌍의 개수이고, 6,000자는 이전 질문·답변과 현재 질문의 문자 수를 합산할 때 사용하는 기준입니다. `build_contents()`는 그 기준을 넘으면 오래된 대화 쌍부터 통째로 빼고, 현재 질문은 잘라내지 않습니다. 800토큰은 모델에 전달하는 출력 토큰 한도이며 문자 수와 같은 단위가 아닙니다. 6,000자 계산에는 시스템 프롬프트가 포함되지 않으며, 설정을 현재 질문보다 작게 바꾸면 현재 질문만으로도 그 기준을 넘을 수 있습니다.

**꼬리질문:** 대화가 생략됐다는 사실을 AI에 알려주나요?  
**짧은 답변:** 문자 수 제한 때문에 이전 턴을 제거했다면 안내 문구를 시스템 지시에 붙입니다. 최근 N턴 선택으로 제외된 모든 기록에 대해 표시하는 것은 아닙니다.

**코드 근거:** [config.py](../../app/core/config.py)의 `AI_CONTEXT_TURNS`, `MAX_CONTEXT_CHARS`, `AI_MAX_TOKENS`; [AI_connect.py](../../app/services/AI_connect.py)의 `build_contents()`; [prompt.py](../../app/services/prompt.py)의 `CONTEXT_TRUNCATED_NOTICE`.

**검증 코드:** [test_ai_connect.py](../../tests/test_ai_connect.py)의 `test_context_uses_recent_complete_turns_and_preserves_order`, `test_context_limit_discards_oldest_turn_without_truncating_question`.

## A05. 시스템 프롬프트와 사용자 메시지를 왜 구분하나요?

**답변:** 시스템 지시는 한국어 사용, 간결한 답변, 모르면 모른다고 말하기 같은 공통 동작을 지정합니다. 대화 내용은 이전 질문을 `user`, 이전 답변을 `model` 역할로 구분하고, 현재 질문을 마지막 `user` 메시지로 붙입니다. 프롬프트는 별도 파일에 두어 호출 로직과 분리해 수정할 수 있습니다. 다만 이런 지시만으로 환각이나 프롬프트 인젝션, 내부 지시 노출을 완전히 방지했다고 말할 수는 없습니다.

**꼬리질문:** 사용자가 “이전 규칙을 무시해”라고 하면 안전하게 차단되나요?  
**짧은 답변:** 현재 코드에는 그 문장을 확실히 차단하는 별도 판별 로직이 없고, 모델의 지시 준수에 의존하는 부분이 있습니다.

**코드 근거:** [prompt.py](../../app/services/prompt.py)의 `SYSTEM_PROMPT`; [AI_connect.py](../../app/services/AI_connect.py)의 `build_contents()`, `_build_config()`.

## A06. `AIResult`는 왜 만들었고, 웹 응답과는 어떻게 다른가요?

**답변:** `AIResult`는 AI 모듈과 채팅 서비스 사이에서 공통으로 사용하는 내부 결과 형식입니다. 성공 여부, 답변, 오류 코드, 사용자 안내, 요청 ID, 모델, 지연 시간과 사용량 등을 같은 구조로 전달합니다. `chat_main`은 이 결과를 검증하고 DB에 저장한 뒤, 성공이면 방 ID·방 이름·답변·요청 ID·생성 시각을 웹 응답으로 만듭니다. 따라서 `AIResult`의 모든 필드가 브라우저에 그대로 노출되는 것은 아닙니다.

**꼬리질문:** `AIResult`가 Pydantic 요청 모델인가요?  
**짧은 답변:** 아니요. `AIResult`는 dataclass이고, 클라이언트 요청을 받는 `ChatRequest`가 Pydantic 모델입니다. 결과의 내용 검사는 `validate_result()`가 추가로 수행합니다.

**코드 근거:** [schemas/chat.py](../../app/schemas/chat.py)의 `ChatRequest`, `AIResult`; [chat_main.py](../../app/services/chat_main.py)의 `chat()`, `validate_result()`.

## A07. AI 생성 옵션은 무엇을 설정하며 답변 품질을 보장하나요?

**답변:** 기본값으로 `temperature=0.7`, 출력 한도 800토큰, thinking level `low`를 설정하며, 시스템 지시도 생성 설정에 함께 넣습니다. 자동 함수 호출은 사용하지 않도록 설정합니다. 부가 옵션을 SDK에서 구성하지 못하면 일부 옵션을 생략하거나 기본 설정으로 돌아가도록 방어 코드가 있습니다. 이 설정만으로 항상 같은 답변, 정답, 특정 비용이나 응답 시간을 보장할 수는 없습니다.

**꼬리질문:** 800토큰으로 제한했으니 DB의 5,000자 제한도 자동으로 지켜지나요?  
**짧은 답변:** 토큰과 문자는 다른 단위이므로 별개입니다. 서비스에서 답변 문자 수를 다시 검사합니다.

**코드 근거:** [config.py](../../app/core/config.py)의 AI 생성 설정; [AI_connect.py](../../app/services/AI_connect.py)의 `_build_config()`; [chat_main.py](../../app/services/chat_main.py)의 `validate_result()`.

## A08. AI 호출을 비동기로 처리하는 이유와 취소 처리는 무엇인가요?

**답변:** 외부 AI의 응답을 기다리는 동안 다른 요청이 진행될 수 있도록 SDK의 비동기 `generate_content()`를 `await`합니다. DB 문맥 조회도 트랜잭션을 종료한 다음 AI를 기다리므로, 조회 트랜잭션을 그 시간 내내 붙잡지 않도록 구성되어 있습니다. 작업 취소는 일반 AI 실패로 바꾸거나 재시도하지 않고 호출자에게 전달합니다. 모든 실제 브라우저 연결 종료가 자동으로 이 취소 경로를 탄다고까지는 이 코드와 테스트만으로 단정할 수 없습니다.

**꼬리질문:** 취소된 요청도 AI 실패 기록으로 저장하나요?  
**짧은 답변:** 명시적으로 작업이 취소되는 테스트에서는 세션을 정리하고, 채팅 실패 행을 저장하지 않습니다.

**코드 근거:** [AI_connect.py](../../app/services/AI_connect.py)의 `_call_once()`, `generate_answer()`; [chat_db.py](../../app/services/chat_db.py)의 `get_history()`.

**검증 코드:** [test_ai_connect.py](../../tests/test_ai_connect.py)의 `test_cancellation_propagates_without_retry`; [test_async_chat.py](../../tests/test_async_chat.py)의 `test_chat_releases_db_while_waiting_and_returns_saved_timestamp`, `test_cancelled_request_releases_session_without_saving_failure`.

## A09. 타임아웃은 어디에 걸려 있고, 요청 전체가 정확히 24초 안에 끝나나요?

**답변:** 기본 단일 호출 한도는 10초이며 SDK HTTP 옵션과 `_call_once()`의 `asyncio.wait_for()`에 적용합니다. `chat_main.chat()`은 재시도와 대체 모델 호출을 포함하는 `generate_answer()` 전체에 기본 24초의 바깥 타임아웃을 둡니다. AI 모듈 내부의 남은 예산 계산은 모델별 루프 진입 때 이루어지고 같은 모델 재시도에는 그 값을 재사용하므로, 내부 계산만으로 총 한도를 엄격히 보장하지는 않습니다. 또한 문맥 DB 조회는 그 전에, 결과 저장은 그 뒤에 있고 취소 정리 시간도 들 수 있어 HTTP 요청 전체가 정확히 24초 이내라고 말하면 안 됩니다.

**꼬리질문:** 바깥 타임아웃이 발생하면 서버가 종료되나요?  
**짧은 답변:** 서비스가 `AI_TIMEOUT` 결과로 변환하고 저장을 시도한 뒤 504 오류를 반환합니다. 저장 자체가 실패하면 DB 오류 응답이 우선될 수 있습니다.

**코드 근거:** [config.py](../../app/core/config.py)의 타임아웃 설정; [AI_connect.py](../../app/services/AI_connect.py)의 `_build_config()`, `_call_once()`, `generate_answer()`; [chat_main.py](../../app/services/chat_main.py)의 `chat()`.

**검증 코드:** [test_ai_connect.py](../../tests/test_ai_connect.py)의 `test_call_once_enforces_timeout`, `test_call_once_passes_context_config_and_usage`.

## A10. 재시도와 대체 모델 호출은 어떤 오류에서 실행하나요?

**답변:** 같은 모델 재시도는 요청 제한과 연결 오류에만 적용하며, 기본 추가 재시도 횟수는 1회이고 남은 시간도 확인합니다. 대체 모델로 넘어갈 수 있는 오류는 타임아웃, 요청 제한, 상위 서비스 오류, 연결 오류, 잘못된 요청, 빈 응답, 알 수 없는 오류입니다. 설정 오류, 안전 차단, 출력 토큰 한도 초과는 재시도나 대체 모델 전환 대상이 아닙니다. 대체 모델이 주 모델과 같거나, 대체 호출에 남은 예산이 0.5초 이하이면 추가 호출을 하지 않습니다.

**꼬리질문:** 주 모델이 타임아웃이면 같은 모델부터 다시 호출하나요?  
**짧은 답변:** 현재 정책에서는 같은 모델 재시도 대상이 아니므로, 남은 예산이 허용하면 대체 모델로 이동합니다.

**코드 근거:** [errors.py](../../app/core/errors.py)의 `RETRY_SAME_MODEL`, `FALLBACK_TRIGGERS`; [AI_connect.py](../../app/services/AI_connect.py)의 `generate_answer()`; [config.py](../../app/core/config.py)의 `AI_MAX_RETRIES`, `MIN_FALLBACK_BUDGET_SECONDS`.

**검증 코드:** [test_ai_connect.py](../../tests/test_ai_connect.py)의 `test_fallback_policy`, `test_fallback_equal_to_primary_is_not_called_again`, `test_fallback_failure_preserves_error_and_last_model`.

## A11. AI 공급자의 오류를 사용자에게 어떻게 전달하나요?

**답변:** `_classify()`는 공급자 예외를 `AI_TIMEOUT`, `AI_RATE_LIMIT`, `AI_CONFIG_ERROR` 같은 우리 서비스 오류 코드로 바꿉니다. AI 모듈은 오류 코드와 사용자 안내를 `AIResult`로 반환하고, 채팅 서비스가 검증·저장 후 HTTP 오류로 변환합니다. 대표적으로 타임아웃은 504, 요청 제한은 429, 설정 오류는 503, 안전 차단은 422이며, 별도 매핑이 없으면 502를 사용합니다. DB 저장까지 실패했다면 사용자 응답은 `DB_UNAVAILABLE` 503이 될 수 있으므로 서버 로그도 함께 봐야 합니다.

**꼬리질문:** 왜 공급자 예외 문자열을 그대로 웹 화면에 보내지 않나요?  
**짧은 답변:** 공급자별 형식에 화면이 의존하지 않게 하고, 사용자가 이해할 수 있는 고정 안내와 요청 ID로 문제를 추적하기 위해서입니다.

**코드 근거:** [AI_connect.py](../../app/services/AI_connect.py)의 `_classify()`, `generate_answer()`; [errors.py](../../app/core/errors.py)의 `USER_MESSAGES`, `AI_ERROR_STATUS`, `api_error_handler()`; [chat_main.py](../../app/services/chat_main.py)의 `chat()`; [chat_db.py](../../app/services/chat_db.py)의 `save_result()`.

## A12. 빈 답변, 안전 차단, 답변 길이 초과를 어떻게 구분하나요?

**답변:** `_extract_answer()`는 공급자 안전 차단 정보를 `AI_BLOCKED`, `MAX_TOKENS` 종료를 `AI_TOKEN_LIMIT`, 공백뿐인 답변을 `AI_EMPTY_RESPONSE`로 구분합니다. 토큰 한도로 끝났다면 일부 텍스트가 있어도 정상 답변으로 사용하지 않습니다. 서비스 계층에서는 성공으로 받은 결과도 다시 검사하여 빈 답변을 거절하고, 5,000자를 넘으면 `AI_ANSWER_TOO_LONG`으로 바꾸며 답변을 제거합니다. 따라서 공급자의 출력 토큰 제한과 우리 DB에 맞춘 문자 수 제한은 서로 다른 검사입니다.

**꼬리질문:** 너무 긴 답변은 앞부분만 잘라서 저장하나요?  
**짧은 답변:** 현재 구현은 자른 답변을 성공으로 저장하지 않고 오류 결과로 바꾸며, `answer`는 `None`으로 처리합니다.

**코드 근거:** [AI_connect.py](../../app/services/AI_connect.py)의 `_extract_answer()`; [chat_main.py](../../app/services/chat_main.py)의 `validate_result()`; [chatlog.py](../../app/models/chatlog.py)의 `answer` 필드.

**검증 코드:** [test_ai_connect.py](../../tests/test_ai_connect.py)의 `test_extracts_answer_or_block_reason`, `test_max_tokens_discards_partial_response_without_retry`.

## A13. 어떤 정보로 AI 장애와 성능을 추적하고, 모두 DB에 저장하나요?

**답변:** `request_id`를 기준으로 AI 호출 시작·성공·실패·대체 호출·최종 포기 로그와 채팅 저장 결과를 연결할 수 있습니다. DB에는 질문·답변 외에 상태, 오류 코드, 지연 시간, 요청 ID, 모델 등을 저장합니다. `prompt_tokens`, `completion_tokens`, `fallback_used`는 내부 결과에는 있지만 현재 `save_result()`와 테이블에는 저장하지 않습니다. 지연 시간은 AI 처리 구간의 경과 시간이므로 DB 조회·저장과 브라우저 표시를 모두 포함한 사용자 체감 응답 시간은 아닙니다.

**꼬리질문:** `fallback_used=True`면 대체 모델로 성공했다는 뜻인가요?  
**짧은 답변:** 오류 결과에서는 대체 모델 호출 단계에 진입했다는 의미도 되므로 `status`와 함께 봐야 합니다. 모델 필드 하나만으로 실제 호출 이력을 확정하지 말고 호출 로그를 확인해야 합니다.

**코드 근거:** [schemas/chat.py](../../app/schemas/chat.py)의 `AIResult`; [AI_connect.py](../../app/services/AI_connect.py)의 `generate_answer()`; [chat_db.py](../../app/services/chat_db.py)의 `save_result()`; [chatlog.py](../../app/models/chatlog.py)의 `ChatLog`.

**검증 코드:** [test_ai_connect.py](../../tests/test_ai_connect.py)의 `test_primary_success_preserves_usage_metadata`, `test_fallback_failure_preserves_error_and_last_model`.

## A14. AI 기능은 어떻게 검증하며, 모의 테스트만으로 무엇까지 말할 수 있나요?

**답변:** 단위 테스트는 SDK나 `_call_once()`를 모의 객체로 바꾸어 문맥 순서, 오류 분류, 대체 모델 정책, 타임아웃과 취소를 재현합니다. API·비동기 테스트는 사용자와 방별 문맥 분리, AI 대기 중 다른 요청의 진행, 저장 시각과 취소 후 정리를 확인하도록 작성되어 있습니다. 이 테스트 코드를 읽은 것과 실제 실행해 통과한 것은 다르며, 모의 테스트 통과도 실제 API 키·모델 접근 권한·외부 네트워크·응답 품질을 보장하지는 않습니다. 실제 연동은 웹에서 로그인 후 질문과 후속 질문을 보내고, 화면·Network·같은 요청 ID의 서버 로그·DB 기록을 연결해 확인해야 합니다.

**꼬리질문:** “내가 방금 뭐 물어봤지?”에 잘 답하면 모든 문맥 기능을 검증한 건가요?  
**짧은 답변:** 정상 사례 하나를 확인한 것입니다. 다른 사용자·다른 방의 기록 제외, 실패 기록 제외, 길이 초과와 오류 상황도 따로 확인해야 합니다.

**코드 근거:** [test_ai_connect.py](../../tests/test_ai_connect.py), [test_chat_api.py](../../tests/test_chat_api.py), [test_async_chat.py](../../tests/test_async_chat.py).

이 문답집 작성 과정에서는 테스트, 실제 AI 호출, 배포 접속 검증을 실행하지 않았습니다.
