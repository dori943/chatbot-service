from sqlalchemy             import select
from sqlalchemy.exc         import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from datetime               import datetime, timezone

from app.core.config        import AI_CONTEXT_TURNS
from app.core.errors        import APIError, ErrorCode
from app.core.logging       import log_event
from app.schemas.chat       import AIResult
from app.models.chatlog     import ChatLog


# [데이터 매핑 1단계: 입력 전달]
# chat_main.py로부터 작업 데이터를 함수 파라미터로 넘겨받음 (AI 결과는 복합 객체인 result: AIResult로 묶여서 전달됨)
# 사용자 질문 및 AI 처리 결과(성공 답변 또는 에러 내역)를 DB에 저장(INSERT)
async def save_result(
    # 비동기 데이터베이스 세션 객체
    db        : AsyncSession,
    # 요청을 보낸 사용자 고유 식별자
    user_id   : str,
    # 대화방 ID
    room_id   : str,
    # 대화방 이름
    room_name : str,
    # 사용자가 입력한 질문 원문
    question  : str,
    # AI 처리 결과 객체 (성공 답변, 에러 코드, 레이턴시 등이 묶여 있는 복합 객체)
    result    : AIResult,
):
    # 현재 시각을 UTC 기준 timezone-aware 객체로 생성
    created_at = datetime.now(timezone.utc)

    try:
        # [데이터 매핑 2단계: DB 테이블 규격으로 분해 및 조립]
        # DB는 파이썬 복합 객체(result)를 직접 저장할 수 없으므로, ChatLog 테이블의 각 컬럼 칸에 1:1로 매핑하여 엔티티(Row) 생성
        # (문법 안내: 좌측 명칭은 DB 테이블의 컬럼명, 우측 값은 위쪽 파라미터 및 result 객체에서 꺼낸 실제 데이터)
        row = ChatLog(
            # 사용자 식별자 매핑 (DB 컬럼 user_id = 파라미터 user_id)
            user_id    = user_id,
            # 대화방 식별자 매핑 (DB 컬럼 room_id = 파라미터 room_id)
            room_id    = room_id,
            # 대화방 이름 매핑 (DB 컬럼 room_name = 파라미터 room_name)
            room_name  = room_name,
            # 사용자 질문 원문 매핑 (DB 컬럼 question = 파라미터 question)
            question   = question,
            # AI 답변 내용 매핑 (DB 컬럼 answer = 복합 객체 result 내부의 answer 속성값)
            answer     = result.answer,
            # 처리 상태값 매핑 (DB 컬럼 status = result 내부의 status 속성값)
            status     = result.status,
            # 실패 시 에러 코드 매핑 (DB 컬럼 error_code = result 내부의 error_code 속성값)
            error_code = result.error_code,
            # AI 호출 레이턴시(ms) 매핑 (DB 컬럼 latency_ms = result 내부의 latency_ms 속성값)
            latency_ms = result.latency_ms,
            # 요청 추적용 상관관계 식별자 매핑 (DB 컬럼 request_id = result 내부의 request_id 속성값)
            request_id = result.request_id,
            # 생성에 사용된 AI 모델명 매핑 (DB 컬럼 model = result 내부의 model 속성값)
            model      = result.model,
            # DB 저장을 위해 타임존 정보를 제거한 naive UTC datetime으로 변환
            created_at = created_at.replace(tzinfo=None),
        )

        # 현재 DB 세션의 작업 목록(트랜잭션)에 신규 엔티티 추가
        db.add(row)
        # 트랜잭션을 데이터베이스에 영구 반영(커밋)
        await db.commit()
        # 정상 저장 완료 이벤트 로그 기록
        log_event("chat_saved", status=result.status, request_id=result.request_id)

        # 프론트엔드로 전달할 표준 UTC 생성 시각 반환
        return created_at
    # 데이터베이스 통신 장애 또는 쿼리 오류 발생 시
    except SQLAlchemyError as exc:
        # DB 저장 실패 로그 및 에러 내역 기록
        log_event("chat_save_failed", exc=exc, request_id=result.request_id)
        # 롤백을 수행하여 세션 내 미완료 트랜잭션 원복
        await db.rollback()
        # 클라이언트에 503 서비스 이용 불가 예외 전파
        raise APIError(
            503, ErrorCode.DB_UNAVAILABLE,
            "대화 기록을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.", result.request_id,
        ) from None


# 특정 사용자의 전체 대화 기록 목록 조회
async def get_list_chat(user_id: str, db: AsyncSession):
    try:
        # 데이터베이스에서 해당 사용자의 채팅 로그를 조회하는 쿼리 비동기 실행
        rows = await db.execute(
            # ChatLog 테이블에서 필요한 컬럼들만 프로젝션(SELECT)
            select(
                # 고유 레코드 식별자
                ChatLog.id,
                # 대화방 ID
                ChatLog.room_id,
                # 대화방 이름
                ChatLog.room_name,
                # 사용자 질문
                ChatLog.question,
                # AI 답변
                ChatLog.answer,
                # 처리 상태
                ChatLog.status,
                # 생성 일시
                ChatLog.created_at,
            )
            # 현재 로그인한 사용자의 레코드만 필터링
            .where(ChatLog.user_id == user_id)
            # 최근 대화 순(생성일시 역순 및 ID 역순)으로 정렬
            .order_by(ChatLog.created_at.desc(), ChatLog.id.desc())
        )
        # 조회된 전체 결과를 리스트 형태로 인출(Fetch)
        chats = rows.all()
        # 조회 트랜잭션 완료 후 세션 상태 정리
        await db.commit()
        # 목록 조회 완료 로그 기록 (조회 건수 포함)
        log_event("chat_list_loaded", count=len(chats))
        # 조회된 엔티티 튜플 리스트 반환
        return chats
    # 데이터베이스 조회 중 에러 발생 시
    except SQLAlchemyError as exc:
        # 실패 이벤트 로그 기록
        log_event("chat_list_failed", exc=exc)
        # 트랜잭션 롤백
        await db.rollback()
        # 클라이언트에 503 에러 전파
        raise APIError(503, ErrorCode.DB_UNAVAILABLE, "대화 기록을 불러오지 못했습니다.") from None


# AI 프롬프트 주입용 이전 대화 문맥(Context) 조회
async def get_history(
    # 조회를 수행할 사용자 ID
    user_id : str,
    # 대상 대화방 ID
    room_id : str,
    # 비동기 DB 세션
    db      : AsyncSession,
    # 불러올 최근 턴(Turn) 개수 제한 (기본값: AI_CONTEXT_TURNS)
    limit   : int = AI_CONTEXT_TURNS,
) -> list[dict[str, str]]:
    try:
        # 문맥 조회 트랜잭션을 끝내 DB 연결을 반환한 뒤 AI를 기다린다.
        # DB에서 해당 방의 최근 질문-답변 쌍을 조회하는 쿼리 실행
        rows = await db.execute(
            # 질문과 답변 컬럼만 선택하여 메모리 및 네트워크 대역폭 최적화
            select(ChatLog.question, ChatLog.answer)
            # 특정 사용자 및 해당 대화방 조건 필터링
            .where(
                ChatLog.user_id == user_id,
                ChatLog.room_id == room_id,
                # 실패하거나 에러 난 대화는 AI 문맥 오염 방지를 위해 성공(success) 건만 필터링
                ChatLog.status == "success",
            )
            # 최신 대화 순으로 정렬하여 지정된 개수(limit)만큼 슬라이싱
            .order_by(ChatLog.id.desc())
            .limit(limit)
        )
        # 최신순으로 가져온 레코드를 시간순(과거 -> 최근)으로 반전시켜 프롬프트 규격 딕셔너리로 조립
        history = [
            {"question": row.question, "answer": row.answer}
            for row in reversed(rows.all())
        ]
        # 조회 트랜잭션을 완료하여 커넥션 풀로 DB 연결 조기 반환
        await db.commit()
        # 문맥 로드 완료 이벤트 로그 기록
        log_event("chat_context_loaded", turns=len(history))
        # 조립된 대화 문맥 리스트 반환
        return history

    # DB 장애 발생 시 AI 전체 호출이 중단되지 않도록 하는 장애 격리(Fault Tolerance)
    except SQLAlchemyError as exc:
        # 문맥 조회 실패 로그 기록
        log_event("chat_history_load_failed", exc=exc)
        # 트랜잭션 롤백
        await db.rollback()
        # 문맥 없이 현재 질문만으로라도 처리할 수 있도록 빈 리스트 반환 (Fallback)
        return []
