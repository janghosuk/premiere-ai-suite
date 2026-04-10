/**
 * main.js - 채팅 패널 UI 로직
 */

(function () {
    'use strict';

    var csInterface = new CSInterface();
    var chatBox, inputBox, sendBtn, statusBar, clearBtn;
    var isProcessing = false;

    function init() {
        chatBox = document.getElementById('chat-box');
        inputBox = document.getElementById('input-box');
        sendBtn = document.getElementById('send-btn');
        statusBar = document.getElementById('status-bar');
        clearBtn = document.getElementById('clear-btn');

        // 이벤트 리스너
        sendBtn.addEventListener('click', handleSend);
        inputBox.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
            }
        });
        inputBox.addEventListener('input', autoResizeInput);
        clearBtn.addEventListener('click', function () {
            ClaudeAPI.clearHistory();
            chatBox.innerHTML = '';
            addMessage('system', '대화 기록이 초기화되었습니다.');
        });

        // API 키 확인
        var key = ClaudeAPI.loadApiKey();
        if (!key) {
            setStatus('API 키 없음', 'error');
            addMessage('system',
                'ANTHROPIC_API_KEY가 설정되지 않았습니다.\n\n' +
                '플러그인 폴더의 .env 파일에 다음을 추가하세요:\n' +
                'ANTHROPIC_API_KEY=sk-ant-...\n\n' +
                '폴더 위치:\n' + getExtensionPath()
            );
        } else {
            setStatus('준비됨', 'ok');
            addMessage('assistant',
                '안녕하세요! Premiere Pro 편집을 도와드릴게요.\n\n' +
                '예시 명령어\n' +
                '· 현재 프로젝트 정보 보여줘\n' +
                '· 타임라인 클립 목록 보여줘\n' +
                '· 5초 지점에서 잘라줘\n' +
                '· 첫 번째 클립에 블러 효과 넣어줘\n' +
                '· 크로스 디졸브 트랜지션 넣어줘'
            );
        }

        inputBox.focus();
    }

    function getExtensionPath() {
        try {
            return csInterface.getSystemPath(SystemPath.EXTENSION);
        } catch (e) {
            return 'C:\\Users\\<user>\\AppData\\Roaming\\Adobe\\CEP\\extensions\\com.premiere.ai.agent';
        }
    }

    function autoResizeInput() {
        inputBox.style.height = 'auto';
        inputBox.style.height = Math.min(inputBox.scrollHeight, 140) + 'px';
    }

    function setStatus(text, type) {
        statusBar.textContent = text;
        statusBar.className = 'status ' + (type || '');
    }

    function labelFor(role) {
        if (role === 'user') return '나';
        if (role === 'assistant') return 'Claude';
        if (role === 'system') return '시스템';
        if (role === 'error') return '오류';
        return role;
    }

    function addMessage(role, content) {
        var msg = document.createElement('div');
        msg.className = 'msg msg-' + role;

        var label = document.createElement('div');
        label.className = 'msg-label';
        label.textContent = labelFor(role);

        var body = document.createElement('div');
        body.className = 'msg-body';
        body.textContent = content;

        msg.appendChild(label);
        msg.appendChild(body);
        chatBox.appendChild(msg);
        scrollToBottom();
        return msg;
    }

    function addLoadingMessage() {
        var msg = document.createElement('div');
        msg.className = 'msg msg-assistant';

        var label = document.createElement('div');
        label.className = 'msg-label';
        label.textContent = 'Claude';

        var body = document.createElement('div');
        body.className = 'msg-body';
        body.innerHTML = '<div class="loading-dots"><span></span><span></span><span></span></div>';

        msg.appendChild(label);
        msg.appendChild(body);
        chatBox.appendChild(msg);
        scrollToBottom();
        return msg;
    }

    function addToolCall(toolName, input) {
        var msg = document.createElement('div');
        msg.className = 'msg msg-tool';

        var label = document.createElement('div');
        label.className = 'msg-label';
        label.textContent = '⚙ ' + toolName;

        var body = document.createElement('div');
        body.className = 'msg-body tool-input';
        var inputStr = JSON.stringify(input);
        body.textContent = inputStr === '{}' ? '(파라미터 없음)' : inputStr;

        msg.appendChild(label);
        msg.appendChild(body);
        chatBox.appendChild(msg);
        scrollToBottom();
    }

    function addToolResult(result) {
        var msg = document.createElement('div');
        msg.className = 'msg msg-tool-result';

        var label = document.createElement('div');
        label.className = 'msg-label';
        label.textContent = '↳ 결과';

        var body = document.createElement('div');
        body.className = 'msg-body';
        // 자르지 않음 - max-height + scroll로 처리
        body.textContent = result;

        msg.appendChild(label);
        msg.appendChild(body);
        chatBox.appendChild(msg);
        scrollToBottom();
    }

    function scrollToBottom() {
        // 다음 프레임에 스크롤
        requestAnimationFrame(function () {
            chatBox.scrollTop = chatBox.scrollHeight;
        });
    }

    function handleSend() {
        if (isProcessing) return;
        var text = inputBox.value.trim();
        if (!text) return;

        addMessage('user', text);
        inputBox.value = '';
        autoResizeInput();
        isProcessing = true;
        sendBtn.disabled = true;
        setStatus('처리 중...', 'busy');

        var loadingMsg = addLoadingMessage();

        ClaudeAPI.processMessage(
            text,
            // onToolCall: 각 도구 호출시
            function (toolName, toolInput, callback) {
                // 로딩 메시지가 있으면 제거 (도구 호출이 시작되었으므로)
                if (loadingMsg && loadingMsg.parentNode) {
                    loadingMsg.parentNode.removeChild(loadingMsg);
                    loadingMsg = null;
                }
                addToolCall(toolName, toolInput);
                PremiereTools.dispatch(toolName, toolInput, function (result) {
                    addToolResult(result);
                    // 다음 응답 대기를 위한 새 로딩
                    loadingMsg = addLoadingMessage();
                    callback(result);
                });
            },
            // onComplete: 최종 응답
            function (err, finalText) {
                isProcessing = false;
                sendBtn.disabled = false;
                if (loadingMsg && loadingMsg.parentNode) {
                    loadingMsg.parentNode.removeChild(loadingMsg);
                    loadingMsg = null;
                }
                if (err) {
                    addMessage('error', err.message);
                    setStatus('오류', 'error');
                } else {
                    addMessage('assistant', finalText || '(응답 없음)');
                    setStatus('준비됨', 'ok');
                }
                inputBox.focus();
            }
        );
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
