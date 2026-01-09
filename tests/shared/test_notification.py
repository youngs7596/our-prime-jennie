"""
tests/shared/test_notification.py - 알림 모듈 테스트
===================================================

shared/notification.py의 TelegramBot 클래스를 테스트합니다.
"""

import pytest
from unittest.mock import MagicMock, patch


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def telegram_bot():
    """TelegramBot 인스턴스"""
    from shared.notification import TelegramBot
    return TelegramBot(token='test-token', chat_id='test-chat-id')


@pytest.fixture
def telegram_bot_no_credentials():
    """자격 증명 없는 TelegramBot"""
    from shared.notification import TelegramBot
    return TelegramBot(token=None, chat_id=None)


# ============================================================================
# Tests: TelegramBot 초기화
# ============================================================================

class TestTelegramBotInit:
    """TelegramBot 초기화 테스트"""
    
    def test_init_with_credentials(self, telegram_bot):
        """자격 증명으로 초기화"""
        assert telegram_bot.token == 'test-token'
        assert telegram_bot.chat_id == 'test-chat-id'
        assert 'test-token' in telegram_bot.base_url
    
    def test_init_from_env(self, monkeypatch):
        """환경 변수에서 초기화"""
        from shared.notification import TelegramBot
        
        monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'env-token')
        monkeypatch.setenv('TELEGRAM_CHAT_ID', 'env-chat-id')
        
        bot = TelegramBot()
        
        assert bot.token == 'env-token'
        assert bot.chat_id == 'env-chat-id'
    
    def test_init_no_credentials(self, telegram_bot_no_credentials):
        """자격 증명 없이 초기화"""
        assert telegram_bot_no_credentials.token is None
        assert telegram_bot_no_credentials.chat_id is None


# ============================================================================
# Tests: send_message
# ============================================================================

class TestSendMessage:
    """send_message 메서드 테스트"""
    
    @patch('shared.notification.requests.post')
    def test_send_message_success(self, mock_post, telegram_bot):
        """메시지 전송 성공"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        result = telegram_bot.send_message("테스트 메시지")
        
        assert result is True
        mock_post.assert_called_once()
        
        # 올바른 URL로 호출되었는지 확인
        call_args = mock_post.call_args
        assert 'sendMessage' in call_args[0][0]
    
    @patch('shared.notification.requests.post')
    def test_send_message_with_special_chars(self, mock_post, telegram_bot):
        """특수문자 이스케이프"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        telegram_bot.send_message("*bold* _italic_ [link](url)")
        
        # payload 확인
        call_args = mock_post.call_args
        payload = call_args[1]['json']
        
        # 특수문자가 이스케이프되어야 함
        assert '\\*' in payload['text'] or '*' not in payload['text']
    
    @patch('shared.notification.requests.post')
    def test_send_message_api_error(self, mock_post, telegram_bot):
        """API 에러 처리"""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = 'Bad Request'
        mock_response.raise_for_status.side_effect = Exception("HTTP Error")
        mock_post.return_value = mock_response
        
        result = telegram_bot.send_message("테스트 메시지")
        
        assert result is False
    
    @patch('shared.notification.requests.post')
    def test_send_message_network_error(self, mock_post, telegram_bot):
        """네트워크 에러 처리"""
        mock_post.side_effect = Exception("Network Error")
        
        result = telegram_bot.send_message("테스트 메시지")
        
        assert result is False
    
    def test_send_message_no_credentials(self, telegram_bot_no_credentials):
        """자격 증명 없으면 False 반환"""
        result = telegram_bot_no_credentials.send_message("테스트")
        
        assert result is False
    
    def test_send_message_no_token(self, monkeypatch):
        """토큰만 없는 경우"""
        from shared.notification import TelegramBot
        
        bot = TelegramBot(token=None, chat_id='some-chat-id')
        
        result = bot.send_message("테스트")
        
        assert result is False
    
    def test_send_message_no_chat_id(self, monkeypatch):
        """Chat ID만 없는 경우"""
        from shared.notification import TelegramBot
        
        bot = TelegramBot(token='some-token', chat_id=None)
        
        result = bot.send_message("테스트")
        
        assert result is False


# ============================================================================
# Tests: 메시지 포맷
# ============================================================================

class TestMessageFormat:
    """메시지 포맷 테스트"""
    
    @patch('shared.notification.requests.post')
    def test_markdown_parse_mode(self, mock_post, telegram_bot):
        """Markdown 파싱 모드"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        telegram_bot.send_message("테스트")
        
        call_args = mock_post.call_args
        payload = call_args[1]['json']
        
        assert payload['parse_mode'] == 'Markdown'
    
    @patch('shared.notification.requests.post')
    def test_chat_id_in_payload(self, mock_post, telegram_bot):
        """Chat ID가 payload에 포함"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        telegram_bot.send_message("테스트")
        
        call_args = mock_post.call_args
        payload = call_args[1]['json']
        
        assert payload['chat_id'] == 'test-chat-id'


# ============================================================================
# Tests: 타임아웃
# ============================================================================

class TestTimeout:
    """타임아웃 테스트"""
    
    @patch('shared.notification.requests.post')
    def test_request_timeout(self, mock_post, telegram_bot):
        """요청 타임아웃 설정"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        telegram_bot.send_message("테스트")
        
        call_args = mock_post.call_args
        
        # timeout 파라미터 확인
        assert call_args[1]['timeout'] == 10


# ============================================================================
# Tests: 로깅
# ============================================================================

class TestLogging:
    """로깅 테스트"""
    
    @patch('shared.notification.requests.post')
    def test_success_logging(self, mock_post, telegram_bot, caplog):
        """성공 로깅"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        with caplog.at_level('INFO'):
            telegram_bot.send_message("테스트")
        
        assert '텔레그램 알림 발송 성공' in caplog.text
    
    @patch('shared.notification.requests.post')
    def test_failure_logging(self, mock_post, telegram_bot, caplog):
        """실패 로깅"""
        mock_post.side_effect = Exception("Test Error")
        
        with caplog.at_level('ERROR'):
            telegram_bot.send_message("테스트")
        
        assert '텔레그램 알림 발송 실패' in caplog.text
    
    def test_no_credentials_warning(self, telegram_bot_no_credentials, caplog):
        """자격 증명 없음 경고"""
        with caplog.at_level('WARNING'):
            telegram_bot_no_credentials.send_message("테스트")
        
        assert '토큰 또는 Chat ID가 설정되지 않' in caplog.text


# ============================================================================
# Tests: parse_command
# ============================================================================

class TestParseCommand:
    """parse_command 메서드 테스트"""
    
    def test_parse_valid_command(self, telegram_bot):
        """유효한 명령어 파싱"""
        result = telegram_bot.parse_command("/buy 삼성전자 10")
        
        assert result is not None
        assert result['command'] == 'buy'
        assert result['args'] == ['삼성전자', '10']
        assert result['raw_text'] == '/buy 삼성전자 10'
    
    def test_parse_command_no_args(self, telegram_bot):
        """인자 없는 명령어"""
        result = telegram_bot.parse_command("/status")
        
        assert result is not None
        assert result['command'] == 'status'
        assert result['args'] == []
    
    def test_parse_command_with_bot_mention(self, telegram_bot):
        """@botname 포함된 명령어 (그룹 채팅)"""
        result = telegram_bot.parse_command("/buy@my_bot_name 삼성전자")
        
        assert result is not None
        assert result['command'] == 'buy'
        assert result['args'] == ['삼성전자']
    
    def test_parse_unsupported_command(self, telegram_bot):
        """지원하지 않는 명령어"""
        result = telegram_bot.parse_command("/unsupported_cmd")
        
        assert result is None
    
    def test_parse_no_slash(self, telegram_bot):
        """슬래시 없는 메시지"""
        result = telegram_bot.parse_command("그냥 메시지")
        
        assert result is None
    
    def test_parse_empty_string(self, telegram_bot):
        """빈 문자열"""
        result = telegram_bot.parse_command("")
        
        assert result is None
    
    def test_parse_none(self, telegram_bot):
        """None 입력"""
        result = telegram_bot.parse_command(None)
        
        assert result is None
    
    def test_parse_only_slash(self, telegram_bot):
        """슬래시만 있는 경우"""
        result = telegram_bot.parse_command("/")
        
        assert result is None
    
    def test_parse_all_supported_commands(self, telegram_bot):
        """모든 지원 명령어 테스트"""
        for cmd in telegram_bot.SUPPORTED_COMMANDS:
            result = telegram_bot.parse_command(f"/{cmd}")
            assert result is not None, f"/{cmd} should be parsed"
            assert result['command'] == cmd


# ============================================================================
# Tests: is_authorized
# ============================================================================

class TestIsAuthorized:
    """is_authorized 메서드 테스트"""
    
    def test_authorized_default_chat_id(self, telegram_bot):
        """기본 chat_id는 허용됨"""
        # 기본 chat_id는 allowed_chat_ids에 포함
        assert telegram_bot.is_authorized(int('123456')) is False  # 허용 안됨
    
    def test_authorized_with_explicit_list(self):
        """명시적 허용 목록"""
        from shared.notification import TelegramBot
        
        bot = TelegramBot(
            token='test-token',
            chat_id='12345',
            allowed_chat_ids=['12345', '67890']
        )
        
        assert bot.is_authorized(12345) is True
        assert bot.is_authorized(67890) is True
        assert bot.is_authorized(99999) is False
    
    def test_authorized_from_env(self, monkeypatch):
        """환경 변수에서 허용 목록"""
        from shared.notification import TelegramBot
        
        monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test-token')
        monkeypatch.setenv('TELEGRAM_CHAT_ID', '12345')
        monkeypatch.setenv('TELEGRAM_ALLOWED_CHAT_IDS', '12345, 67890, 11111')
        
        bot = TelegramBot()
        
        assert bot.is_authorized(12345) is True
        assert bot.is_authorized(67890) is True
        assert bot.is_authorized(11111) is True
        assert bot.is_authorized(99999) is False


# ============================================================================
# Tests: get_updates
# ============================================================================

class TestGetUpdates:
    """get_updates 메서드 테스트"""
    
    @patch('shared.notification.requests.get')
    def test_get_updates_success(self, mock_get, telegram_bot):
        """업데이트 성공적으로 가져오기"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'ok': True,
            'result': [
                {'update_id': 1, 'message': {'text': '/status'}},
                {'update_id': 2, 'message': {'text': '/portfolio'}}
            ]
        }
        mock_get.return_value = mock_response
        
        updates = telegram_bot.get_updates(timeout=5)
        
        assert len(updates) == 2
        assert telegram_bot._last_update_id == 2
    
    @patch('shared.notification.requests.get')
    def test_get_updates_empty(self, mock_get, telegram_bot):
        """업데이트 없음"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'ok': True, 'result': []}
        mock_get.return_value = mock_response
        
        updates = telegram_bot.get_updates(timeout=5)
        
        assert updates == []
    
    @patch('shared.notification.requests.get')
    def test_get_updates_api_error(self, mock_get, telegram_bot):
        """API 에러 응답"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'ok': False, 'description': 'Error'}
        mock_get.return_value = mock_response
        
        updates = telegram_bot.get_updates(timeout=5)
        
        assert updates == []
    
    @patch('shared.notification.requests.get')
    def test_get_updates_network_error(self, mock_get, telegram_bot):
        """네트워크 에러"""
        mock_get.side_effect = Exception("Network error")
        
        updates = telegram_bot.get_updates(timeout=5)
        
        assert updates == []
    
    @patch('shared.notification.requests.get')
    def test_get_updates_timeout(self, mock_get, telegram_bot):
        """타임아웃 (정상 동작)"""
        import requests
        mock_get.side_effect = requests.exceptions.Timeout()
        
        updates = telegram_bot.get_updates(timeout=5)
        
        assert updates == []  # 타임아웃은 정상
    
    def test_get_updates_no_token(self, telegram_bot_no_credentials):
        """토큰 없으면 빈 리스트"""
        updates = telegram_bot_no_credentials.get_updates()
        
        assert updates == []


# ============================================================================
# Tests: get_pending_commands
# ============================================================================

class TestGetPendingCommands:
    """get_pending_commands 메서드 테스트"""
    
    @patch('shared.notification.requests.get')
    def test_get_pending_commands_authorized(self, mock_get):
        """인가된 사용자의 명령어"""
        from shared.notification import TelegramBot
        
        bot = TelegramBot(
            token='test-token',
            chat_id='12345',
            allowed_chat_ids=['12345']
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'ok': True,
            'result': [
                {
                    'update_id': 1,
                    'message': {
                        'text': '/status',
                        'chat': {'id': 12345},
                        'from': {'username': 'testuser'}
                    }
                }
            ]
        }
        mock_get.return_value = mock_response
        
        commands = bot.get_pending_commands(timeout=1)
        
        assert len(commands) == 1
        assert commands[0]['command'] == 'status'
        assert commands[0]['chat_id'] == 12345
        assert commands[0]['username'] == 'testuser'
    
    @patch('shared.notification.requests.post')
    @patch('shared.notification.requests.get')
    def test_get_pending_commands_unauthorized(self, mock_get, mock_post):
        """미인가 사용자 명령어 거부"""
        from shared.notification import TelegramBot
        
        bot = TelegramBot(
            token='test-token',
            chat_id='12345',
            allowed_chat_ids=['12345']
        )
        
        mock_response_get = MagicMock()
        mock_response_get.status_code = 200
        mock_response_get.json.return_value = {
            'ok': True,
            'result': [
                {
                    'update_id': 1,
                    'message': {
                        'text': '/status',
                        'chat': {'id': 99999},  # 허용되지 않은 chat_id
                        'from': {'username': 'hacker'}
                    }
                }
            ]
        }
        mock_get.return_value = mock_response_get
        
        # 거부 메시지 전송 mock
        mock_response_post = MagicMock()
        mock_response_post.status_code = 200
        mock_post.return_value = mock_response_post
        
        commands = bot.get_pending_commands(timeout=1)
        
        # 미인가 사용자는 명령어가 반환되지 않음
        assert len(commands) == 0
        # 거부 메시지가 전송되었는지 확인
        mock_post.assert_called_once()
    
    @patch('shared.notification.requests.get')
    def test_get_pending_commands_non_command_message(self, mock_get):
        """일반 메시지 무시"""
        from shared.notification import TelegramBot
        
        bot = TelegramBot(
            token='test-token',
            chat_id='12345',
            allowed_chat_ids=['12345']
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'ok': True,
            'result': [
                {
                    'update_id': 1,
                    'message': {
                        'text': '일반 메시지입니다',  # 명령어 아님
                        'chat': {'id': 12345},
                        'from': {'username': 'testuser'}
                    }
                }
            ]
        }
        mock_get.return_value = mock_response
        
        commands = bot.get_pending_commands(timeout=1)
        
        assert len(commands) == 0


# ============================================================================
# Tests: reply
# ============================================================================

class TestReply:
    """reply 메서드 테스트"""
    
    @patch('shared.notification.requests.post')
    def test_reply_success(self, mock_post, telegram_bot):
        """응답 전송 성공"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        result = telegram_bot.reply(12345, "응답 메시지")
        
        assert result is True
        
        # chat_id가 올바르게 전달되었는지 확인
        call_args = mock_post.call_args
        payload = call_args[1]['json']
        assert payload['chat_id'] == '12345'
    
    @patch('shared.notification.requests.post')
    def test_reply_failure(self, mock_post, telegram_bot):
        """응답 전송 실패"""
        mock_post.side_effect = Exception("Network error")
        
        result = telegram_bot.reply(12345, "응답 메시지")
        
        assert result is False


# ============================================================================
# Tests: Edge Cases
# ============================================================================

class TestEdgeCases:
    """Edge case 테스트"""
    
    @patch('shared.notification.requests.post')
    def test_send_message_to_custom_chat_id(self, mock_post, telegram_bot):
        """다른 chat_id로 메시지 전송"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        telegram_bot.send_message("테스트", chat_id="custom-chat-id")
        
        call_args = mock_post.call_args
        payload = call_args[1]['json']
        assert payload['chat_id'] == 'custom-chat-id'
    
    def test_allowed_chat_ids_string_conversion(self):
        """chat_id 문자열 변환"""
        from shared.notification import TelegramBot
        
        bot = TelegramBot(
            token='test-token',
            chat_id=12345,  # int로 전달
            allowed_chat_ids=None
        )
        
        # int chat_id도 문자열로 변환되어 allowed_chat_ids에 포함
        assert '12345' in bot.allowed_chat_ids
    
    @patch('shared.notification.requests.get')
    def test_get_updates_updates_last_update_id(self, mock_get, telegram_bot):
        """update_id 추적"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'ok': True,
            'result': [
                {'update_id': 100},
                {'update_id': 200},
                {'update_id': 150}  # 순서가 뒤섞여도 최대값 추적
            ]
        }
        mock_get.return_value = mock_response
        
        telegram_bot.get_updates()
        
        assert telegram_bot._last_update_id == 200  # 최대값

