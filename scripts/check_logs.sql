-- 대화 기록 점검용 읽기 전용 쿼리. 실행 방법: docs/testing-guide.md
-- testuser 및 request_id 예시를 확인할 값으로 바꾼다.

SHOW TABLES;
DESCRIBE chat_logs;
SELECT TABLE_NAME, TABLE_COLLATION
FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE();

-- 전체 현황
SELECT
    (SELECT COUNT(*) FROM login) AS users,
    COUNT(*) AS chats,
    COALESCE(SUM(status = 'success'), 0) AS successes,
    COALESCE(SUM(status <> 'success'), 0) AS failures,
    MIN(created_at) AS first_created_at,
    MAX(created_at) AS last_created_at
FROM chat_logs;

-- 최근 대화: DB 시각은 UTC, 표시할 때만 KST로 변환
SELECT id, user_id, DATE_ADD(created_at, INTERVAL 9 HOUR) AS created_at_kst,
       LEFT(question, 40) AS question, LEFT(answer, 60) AS answer,
       status, error_code, latency_ms, model, request_id
FROM chat_logs ORDER BY id DESC LIMIT 20;

-- 사용자별 이용 현황
SELECT l.id AS user_id, COUNT(c.id) AS chats,
       COALESCE(SUM(c.status = 'success'), 0) AS successes,
       COALESCE(SUM(c.status <> 'success'), 0) AS failures,
       ROUND(AVG(CASE WHEN c.status = 'success' THEN c.latency_ms END)) AS avg_success_ms,
       MAX(c.created_at) AS last_created_at
FROM login l LEFT JOIN chat_logs c ON c.user_id = l.id
GROUP BY l.id ORDER BY chats DESC;

-- 실패 요청 추적
SELECT id, user_id, created_at, status, error_code, latency_ms, model, request_id
FROM chat_logs WHERE status <> 'success' ORDER BY id DESC LIMIT 20;
SELECT error_code, COUNT(*) AS failures
FROM chat_logs WHERE status <> 'success'
GROUP BY error_code ORDER BY failures DESC;

-- 최종 성공 모델 분포. 폴백 여부는 DB 컬럼이 없어 서버의 ai_fallback_start 로그로 확인한다.
SELECT model, COUNT(*) AS successes, ROUND(AVG(latency_ms)) AS avg_ms
FROM chat_logs WHERE status = 'success'
GROUP BY model ORDER BY successes DESC;

-- 성공 응답 속도 분포
SELECT CASE WHEN latency_ms < 1000 THEN '<1s'
            WHEN latency_ms < 3000 THEN '1-3s'
            WHEN latency_ms < 5000 THEN '3-5s'
            WHEN latency_ms < 10000 THEN '5-10s'
            ELSE '>=10s' END AS latency_range,
       COUNT(*) AS successes
FROM chat_logs WHERE status = 'success' AND latency_ms IS NOT NULL
GROUP BY latency_range ORDER BY MIN(latency_ms);

-- 특정 사용자의 전체 대화 / 서버 로그의 request_id와 연결
SELECT id, created_at, question, answer, status FROM chat_logs
WHERE user_id = 'testuser' ORDER BY id;
SELECT * FROM chat_logs WHERE request_id = 'replace-with-request-id';

-- AI 문맥 후보: 기본 최근 성공 5턴. 실제 프롬프트는 MAX_CONTEXT_CHARS에 따라 더 줄어들 수 있다.
SELECT * FROM (
    SELECT id, question, answer, created_at FROM chat_logs
    WHERE user_id = 'testuser' AND status = 'success'
    ORDER BY id DESC LIMIT 5
) AS recent ORDER BY id;

-- 한글/이모지 저장 확인: 문자 수와 UTF-8 바이트 수는 서로 다를 수 있다.
SELECT id, question, CHAR_LENGTH(question) AS characters, LENGTH(question) AS bytes
FROM chat_logs ORDER BY id DESC LIMIT 5;
