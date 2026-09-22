CREATE TABLE IF NOT EXISTS login (
    id VARCHAR(50)  PRIMARY KEY,
    pw VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_logs (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id     VARCHAR(50) NOT NULL,
    question    VARCHAR(5000) NOT NULL,
    answer      VARCHAR(5000) NULL,
    status      VARCHAR(20) NOT NULL,
    error_code  VARCHAR(50) NULL,
    latency_ms  INT NULL,
    request_id  VARCHAR(64) NOT NULL,
    model       VARCHAR(80) NULL,
    created_at  DATETIME(6) NOT NULL,

    FOREIGN KEY (user_id) REFERENCES login(id)
);
