
## 실행 방법
### 1. 환경변수 설정
```
.env.example => 복붙 + .env로 이름변경
```
### 2. Docker Compose 실행
```bash
docker compose up --build -d
```

### 3. 실행상태 / 로그 확인
```
# 실행 상태
docker ps             # 기존 도커 명령어와 동일합니다.
docker compose logs  
docker compose logs [컨테이너명]  # 특정 컨테이너 로그만 확인
```

### 4. 도커 종료
```
docker compose stop
```

## DB 테이블
[init.sql 보러가기](/data/init.sql)
```
login
- id: varchar(50)
- pw: varchar(255)
```

## 통신 방법
```
# 백엔드 서버와 통신 시 해당 주소로 요청 전송하시면 됩니다.
backend:8000/[요청할 api]
```

## 볼륨 / 네트워크
```
# 볼륨 
mysql-data   - mysql 컨테이너

# 네트워크
chatbot-network  - 백엔드 서버, mysql 컨테이너
=> 차후 프론트/AI 서버 추가 가능성
```
