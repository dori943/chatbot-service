from pydantic import BaseModel

# ==============================================================================
# [인증 요청 DTO 스키마: AuthRequest]
# 회원가입(/auth/register) 및 로그인(/auth/login) 시 클라이언트가 전송하는 JSON 본문 검증
# ==============================================================================
class AuthRequest(BaseModel):
    # 사용자 계정 아이디
    id : str
    # 사용자 비밀번호 문자열
    pw : str
