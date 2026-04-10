/**
 * claude-api.js - Claude API 통신 모듈 (Node.js HTTPS)
 * CEP 패널 내에서 Node.js require('https')를 사용합니다.
 */

(function () {
    'use strict';

    var https = require('https');
    var fs = require('fs');
    var path = require('path');

    var API_URL = 'api.anthropic.com';
    var API_PATH = '/v1/messages';
    var MODEL = 'claude-sonnet-4-6';

    // API 키 로드
    var _apiKey = '';

    function loadApiKey() {
        // 1) 전역 변수에서
        if (_apiKey) return _apiKey;

        // 2) 확장 폴더 내 .env 파일
        var extDir = path.resolve(__dirname, '..');
        var envPath = path.join(extDir, '.env');
        if (fs.existsSync(envPath)) {
            var lines = fs.readFileSync(envPath, 'utf8').split('\n');
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim();
                if (line.indexOf('ANTHROPIC_API_KEY=') === 0) {
                    _apiKey = line.split('=')[1].trim().replace(/['"]/g, '');
                    return _apiKey;
                }
            }
        }

        // 3) premiere_agent/.env 파일 (기존 파일)
        var altEnv = 'C:\\Users\\hsjang\\OneDrive\\\uBC14\uD0D5 \uD654\uBA74\\_COwork\\\uACAC\uC801\uC11C\\premiere_agent\\.env';
        if (fs.existsSync(altEnv)) {
            var lines2 = fs.readFileSync(altEnv, 'utf8').split('\n');
            for (var j = 0; j < lines2.length; j++) {
                var line2 = lines2[j].trim();
                if (line2.indexOf('ANTHROPIC_API_KEY=') === 0) {
                    _apiKey = line2.split('=')[1].trim().replace(/['"]/g, '');
                    return _apiKey;
                }
            }
        }

        return '';
    }

    function setApiKey(key) {
        _apiKey = key;
    }

    // 시스템 프롬프트 (간결하게)
    var SYSTEM_PROMPT = '당신은 Adobe Premiere Pro 편집 어시스턴트입니다. 한국어로 응답하고, 도구로 작업을 수행합니다. 인덱스는 0부터. 불확실하면 먼저 list_clips/sequence_info로 조회. 결과는 간결히 요약.';

    // 도구 정의 (압축: 공통 스키마 빌더 사용)
    var N = { type: "number" };
    var S = { type: "string" };
    var B = { type: "boolean" };
    function T(name, props, required) {
        return { name: name, description: "", input_schema: { type: "object", properties: props || {}, required: required || [] } };
    }
    var TI = { track_index: N, clip_index: N };
    var TT = { track_type: S, track_index: N, clip_index: N };
    var TTR = ["track_type", "track_index", "clip_index"];
    var TIR = ["track_index", "clip_index"];

    var TOOLS = [
        T("project_info"),
        T("save_project"),
        T("import_media", { file_paths: S }, ["file_paths"]),
        T("create_sequence", { name: S }, ["name"]),
        T("list_sequences"),
        T("set_active_sequence", { name: S }, ["name"]),
        T("list_items", { bin_path: S }),
        T("sequence_info"),
        T("list_clips", { track_type: S, track_index: N }, ["track_type", "track_index"]),
        T("remove_clip", TT, TTR),
        T("ripple_delete", TT, TTR),
        T("move_clip", { track_type: S, track_index: N, clip_index: N, new_start: N }, TTR.concat(["new_start"])),
        T("trim_clip", { track_type: S, track_index: N, clip_index: N, new_in: N, new_out: N }, TTR),
        T("razor_cut", { time: N, tracks: S }, ["time"]),
        T("set_speed", { track_index: N, clip_index: N, speed: N }, TIR.concat(["speed"])),
        T("duplicate_clip", TI, TIR),
        T("lift_range", { start: N, end: N }, ["start", "end"]),
        T("extract_range", { start: N, end: N }, ["start", "end"]),
        T("set_work_area", { "in": N, "out": N }, ["in", "out"]),
        T("play"),
        T("pause"),
        T("go_to", { time: N }, ["time"]),
        T("current_time"),
        T("apply_effect", { effect: S, track_index: N, clip_index: N }, ["effect"].concat(TIR)),
        T("remove_effect", { effect_index: N, track_index: N, clip_index: N }, ["effect_index"].concat(TIR)),
        T("list_effects", TI, TIR),
        T("set_parameter", { component: N, param: S, value: N, track_index: N, clip_index: N }, ["component", "param", "value"].concat(TIR)),
        T("set_opacity", { value: N, track_index: N, clip_index: N }, ["value"].concat(TIR)),
        T("set_scale", { value: N, track_index: N, clip_index: N }, ["value"].concat(TIR)),
        T("set_position", { x: N, y: N, track_index: N, clip_index: N }, ["x", "y"].concat(TIR)),
        T("set_rotation", { degrees: N, track_index: N, clip_index: N }, ["degrees"].concat(TIR)),
        T("apply_transition", { transition: S, track_index: N, clip_index: N, duration: N, position: S }, ["transition"].concat(TIR)),
        T("add_keyframe", { component: N, param: S, time: N, value: N, track_index: N, clip_index: N }, ["component", "param", "time", "value"].concat(TIR)),
        T("fade_in", { track_index: N, clip_index: N, duration: N }, TIR.concat(["duration"])),
        T("fade_out", { track_index: N, clip_index: N, duration: N }, TIR.concat(["duration"])),
        T("reset_effects", TI, TIR),
        T("list_markers"),
        T("add_marker", { time: N, name: S, comment: S, color: N }, ["time"]),
        T("remove_marker", { time: N }, ["time"]),
        T("clear_markers"),
        T("export", { output: S, preset: S, work_area_only: B }, ["output", "preset"]),
        T("export_encoder", { output: S, preset: S }, ["output", "preset"]),
        T("export_frame", { output: S, time: N }, ["output"])
    ];

    // 대화 기록
    var _conversationHistory = [];
    var MAX_HISTORY = 6;
    var MAX_TOOL_RESULT_CHARS = 2000;

    function clearHistory() {
        _conversationHistory = [];
    }

    /**
     * Claude API 호출
     * @param {Array} messages - 메시지 배열
     * @param {Function} callback - function(err, response)
     */
    function callAPI(messages, callback) {
        var key = loadApiKey();
        if (!key) {
            callback(new Error('API 키가 설정되지 않았습니다. 플러그인 폴더에 .env 파일을 만들어주세요.'));
            return;
        }

        var body = JSON.stringify({
            model: MODEL,
            max_tokens: 4096,
            system: SYSTEM_PROMPT,
            tools: TOOLS,
            messages: messages
        });

        var options = {
            hostname: API_URL,
            port: 443,
            path: API_PATH,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'x-api-key': key,
                'anthropic-version': '2023-06-01',
                'Content-Length': Buffer.byteLength(body)
            }
        };

        var req = https.request(options, function (res) {
            var data = [];
            res.on('data', function (chunk) { data.push(chunk); });
            res.on('end', function () {
                try {
                    var response = JSON.parse(Buffer.concat(data).toString());
                    if (res.statusCode !== 200) {
                        callback(new Error('API 오류 (' + res.statusCode + '): ' + (response.error ? response.error.message : JSON.stringify(response))));
                    } else {
                        callback(null, response);
                    }
                } catch (e) {
                    callback(new Error('응답 파싱 오류: ' + e.message));
                }
            });
        });

        req.on('error', function (e) {
            callback(new Error('네트워크 오류: ' + e.message));
        });

        req.write(body);
        req.end();
    }

    /**
     * 사용자 메시지 처리 (tool_use 루프 포함)
     * @param {string} userMessage
     * @param {Function} onToolCall - function(toolName, toolInput, callback)
     * @param {Function} onComplete - function(err, finalText)
     */
    function processMessage(userMessage, onToolCall, onComplete) {
        _conversationHistory.push({ role: 'user', content: userMessage });

        // 기록 길이 제한
        while (_conversationHistory.length > MAX_HISTORY * 2) {
            _conversationHistory.shift();
        }

        function loop(messages) {
            callAPI(messages, function (err, response) {
                if (err) {
                    onComplete(err, null);
                    return;
                }

                // 응답에서 텍스트와 도구 호출 분리
                var textParts = [];
                var toolUses = [];

                if (response.content) {
                    for (var i = 0; i < response.content.length; i++) {
                        var block = response.content[i];
                        if (block.type === 'text') {
                            textParts.push(block.text);
                        } else if (block.type === 'tool_use') {
                            toolUses.push(block);
                        }
                    }
                }

                // 어시스턴트 응답 기록
                _conversationHistory.push({ role: 'assistant', content: response.content });

                if (response.stop_reason === 'tool_use' && toolUses.length > 0) {
                    // 도구 호출 처리
                    var toolResults = [];
                    var completed = 0;

                    for (var t = 0; t < toolUses.length; t++) {
                        (function (toolUse, idx) {
                            onToolCall(toolUse.name, toolUse.input, function (result) {
                                var trimmed = String(result);
                                if (trimmed.length > MAX_TOOL_RESULT_CHARS) {
                                    trimmed = trimmed.substring(0, MAX_TOOL_RESULT_CHARS) + '\n...[truncated]';
                                }
                                toolResults[idx] = {
                                    type: 'tool_result',
                                    tool_use_id: toolUse.id,
                                    content: trimmed
                                };
                                completed++;
                                if (completed === toolUses.length) {
                                    // 도구 결과를 대화에 추가하고 재호출
                                    _conversationHistory.push({ role: 'user', content: toolResults });
                                    loop(_conversationHistory.slice());
                                }
                            });
                        })(toolUses[t], t);
                    }
                } else {
                    // 최종 텍스트 응답
                    onComplete(null, textParts.join('\n'));
                }
            });
        }

        loop(_conversationHistory.slice());
    }

    // 공개 API
    window.ClaudeAPI = {
        loadApiKey: loadApiKey,
        setApiKey: setApiKey,
        processMessage: processMessage,
        clearHistory: clearHistory,
        getHistory: function () { return _conversationHistory; }
    };

})();
