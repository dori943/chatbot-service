-- ============================================================================
--  대화 로그 확인 쿼리 (평가용)
--  미션 요구사항 "DB 확인 가이드" 대응
--
--  실행 방법
--    docker compose exec -T db mysql -u chatbot -p chatbot < scripts/check_logs.sql
--
--  또는 컨테이너에 붙어서 직접 실행
--    docker compose exec db mysql -u chatbot -p chatbot
--    mysql> source /scripts/check_logs.sql;
-- ============================================================================


-- ────────────────────────────────────────────────────────────────────────────
-- 0. 테이블 구조 확인
-- ────────────────────────────────────────────────────────────────────────────
SELECT '=== 0. 테이블 목록 ===' AS section;
SHOW TABLES;

SELECT '=== 0-1. chatlog 테이블 구조 ===' AS section;
DESCRIBE chatlog;

SELECT '=== 0-2. 문자셋 확인 (한글 저장용 utf8mb4 여야 함) ===' AS section;
SELECT TABLE_NAME, TABLE_COLLATION
FROM   information_schema.TABLES
WHERE  TABLE_SCHEMA = DATABASE();


-- ────────────────────────────────────────────────────────────────────────────
-- 1. 전체 현황 요약
-- ────────────────────────────────────────────────────────────────────────────
SELECT '=== 1. 전체 요약 ===' AS section;
SELECT
    (SELECT COUNT(*) FROM login)   AS 가입자수,
    (SELECT COUNT(*) FROM chatlog) AS 전체대화수,
    (SELECT COUNT(*) FROM chatlog WHERE status = 'success') AS 성공,
    (SELECT COUNT(*) FROM chatlog WHERE status <> 'success') AS 실패,
    (SELECT MIN(created_at) FROM chatlog) AS 최초기록,
    (SELECT MAX(created_at) FROM chatlog) AS 최근기록;


-- ────────────────────────────────────────────────────────────────────────────
-- 2. 최근 대화 로그 20건  ← 평가자가 제일 먼저 볼 부분
--    요구사항 "사용자 식별, 생성 시각, 질문, 응답" 을 모두 포함
-- ────────────────────────────────────────────────────────────────────────────
SELECT '=== 2. 최근 대화 로그 20건 ===' AS section;
SELECT
    id                        AS 번호,
    user_id                   AS 사용자,
    DATE_FORMAT(
        CONVERT_TZ(created_at, '+00:00', '+09:00'),
        '%Y-%m-%d %H:%i:%s'
    )                         AS 시각_KST,
    LEFT(question, 40)        AS 질문,
    LEFT(COALESCE(answer, '(응답 없음)'), 60) AS 응답,
    status                    AS 상태,
    error_code                AS 에러코드,
    latency_ms                AS 응답시간ms,
    model                     AS 사용모델
FROM   chatlog
ORDER  BY id DESC
LIMIT  20;

-- CONVERT_TZ 가 NULL 을 반환하면 MySQL 타임존 테이블이 비어 있는 것입니다.
-- 그럴 땐 아래처럼 9시간을 더하면 됩니다.
--   DATE_ADD(created_at, INTERVAL 9 HOUR) AS 시각_KST


-- ────────────────────────────────────────────────────────────────────────────
-- 3. 사용자별 이용 현황  (요구사항: 사용자 기준 조회/추적)
-- ────────────────────────────────────────────────────────────────────────────
SELECT '=== 3. 사용자별 이용 현황 ===' AS section;
SELECT
    l.id                                                   AS 사용자,
    COUNT(c.id)                                            AS 총질문수,
    SUM(c.status = 'success')                              AS 성공,
    SUM(c.status <> 'success')                             AS 실패,
    ROUND(AVG(CASE WHEN c.status = 'success'
                   THEN c.latency_ms END))                 AS 평균응답ms,
    MAX(c.created_at)                                      AS 마지막대화
FROM   login l
LEFT   JOIN chatlog c ON c.user_id = l.id
GROUP  BY l.id
ORDER  BY 총질문수 DESC;


-- ────────────────────────────────────────────────────────────────────────────
-- 4. 특정 사용자의 대화 전체 보기
--    아래 'testuser' 를 확인하고 싶은 아이디로 바꿔서 실행하세요.
-- ────────────────────────────────────────────────────────────────────────────
SELECT '=== 4. 특정 사용자 대화 (user_id 를 바꿔서 실행) ===' AS section;
SELECT
    id            AS 번호,
    created_at    AS 시각_UTC,
    question      AS 질문,
    answer        AS 응답,
    status        AS 상태
FROM   chatlog
WHERE  user_id = 'testuser'      -- ← 여기를 바꾸세요
ORDER  BY id ASC;                -- 대화 흐름을 보려면 오름차순


-- ────────────────────────────────────────────────────────────────────────────
-- 5. 실패 이력  (요구사항 5번: AI 실패를 로그로 추적)
-- ────────────────────────────────────────────────────────────────────────────
SELECT '=== 5. 실패한 요청 목록 ===' AS section;
SELECT
    id            AS 번호,
    user_id       AS 사용자,
    created_at    AS 시각_UTC,
    status        AS 상태,
    error_code    AS 에러코드,
    latency_ms    AS 소요ms,
    model         AS 마지막시도모델,
    request_id    AS 추적ID,
    LEFT(question, 40) AS 질문
FROM   chatlog
WHERE  status <> 'success'
ORDER  BY id DESC
LIMIT  20;

SELECT '=== 5-1. 에러 코드별 집계 ===' AS section;
SELECT
    COALESCE(error_code, '(없음)') AS 에러코드,
    COUNT(*)                       AS 발생횟수,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM chatlog), 1) AS 비율_퍼센트
FROM   chatlog
GROUP  BY error_code
ORDER  BY 발생횟수 DESC;


-- ────────────────────────────────────────────────────────────────────────────
-- 6. 폴백 모델 동작 현황
--    주 모델이 실패해서 폴백이 답한 비율을 본다.
-- ────────────────────────────────────────────────────────────────────────────
SELECT '=== 6. 모델별 응답 건수 (폴백 발생률) ===' AS section;
SELECT
    COALESCE(model, '(없음)') AS 모델,
    COUNT(*)                  AS 응답건수,
    ROUND(AVG(latency_ms))    AS 평균응답ms,
    ROUND(100.0 * COUNT(*) /
          (SELECT COUNT(*) FROM chatlog WHERE status = 'success'), 1) AS 비율_퍼센트
FROM   chatlog
WHERE  status = 'success'
GROUP  BY model
ORDER  BY 응답건수 DESC;


-- ────────────────────────────────────────────────────────────────────────────
-- 7. 응답 속도 분포
-- ────────────────────────────────────────────────────────────────────────────
SELECT '=== 7. 응답 속도 분포 ===' AS section;
SELECT
    CASE
        WHEN latency_ms <  1000 THEN '1초 미만'
        WHEN latency_ms <  3000 THEN '1~3초'
        WHEN latency_ms <  5000 THEN '3~5초'
        WHEN latency_ms < 10000 THEN '5~10초'
        ELSE                         '10초 이상'
    END       AS 구간,
    COUNT(*)  AS 건수
FROM   chatlog
WHERE  status = 'success' AND latency_ms IS NOT NULL
GROUP  BY 구간
ORDER  BY MIN(latency_ms);


-- ────────────────────────────────────────────────────────────────────────────
-- 8. request_id 로 한 요청 추적
--    서버 로그에서 본 request_id 를 넣으면 DB 기록을 찾을 수 있습니다.
--    (서버 로그의 ai_call_start / ai_call_success 와 같은 값)
-- ────────────────────────────────────────────────────────────────────────────
SELECT '=== 8. request_id 추적 (값을 바꿔서 실행) ===' AS section;
SELECT *
FROM   chatlog
WHERE  request_id = 'a1b2c3d4e5f6';   -- ← 서버 로그에서 복사한 값으로 바꾸세요


-- ────────────────────────────────────────────────────────────────────────────
-- 9. 문맥 유지 확인용
--    AI 에게 실제로 전달되는 대화(성공 건, 오래된 순)가 무엇인지 본다.
--    AI_CONTEXT_TURNS 기본값이 5 이므로 LIMIT 5.
-- ────────────────────────────────────────────────────────────────────────────
SELECT '=== 9. 컨텍스트로 들어가는 최근 5건 (user_id 를 바꿔서 실행) ===' AS section;
SELECT *
FROM (
    SELECT id, question, answer, created_at
    FROM   chatlog
    WHERE  user_id = 'testuser'       -- ← 여기를 바꾸세요
      AND  status  = 'success'
    ORDER  BY id DESC
    LIMIT  5
) AS recent
ORDER BY id ASC;   -- AI 에는 오래된 것부터 시간순으로 들어간다


-- ────────────────────────────────────────────────────────────────────────────
-- 10. 한글 저장 검증
--     깨진 글자가 있으면 utf8mb4 설정이 빠진 것입니다.
-- ────────────────────────────────────────────────────────────────────────────
SELECT '=== 10. 한글 정상 저장 여부 ===' AS section;
SELECT
    id                 AS 번호,
    question           AS 질문,
    CHAR_LENGTH(question) AS 글자수,
    LENGTH(question)      AS 바이트수
FROM   chatlog
WHERE  question REGEXP '[가-힣]'
ORDER  BY id DESC
LIMIT  5;
-- 한글은 utf8mb4 에서 1글자 = 3바이트입니다.
-- 바이트수가 글자수의 3배 근처면 정상, 물음표(?)로 보이면 문자셋 설정 문제입니다.
