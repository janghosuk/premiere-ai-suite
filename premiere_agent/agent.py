"""AI 에이전트 코어 - 자연어 명령을 Premiere Pro 작업으로 변환"""

import json
import os
from anthropic import Anthropic
from premiere.connection import PremiereConnection
from premiere.project import ProjectManager
from premiere.timeline import TimelineEditor
from premiere.effects import EffectsManager
from premiere.markers import MarkerManager
from premiere.export import ExportManager


SYSTEM_PROMPT = """당신은 Adobe Premiere Pro를 제어하는 전문 편집 에이전트입니다.
사용자의 자연어 명령을 분석하여 적절한 Premiere Pro 작업을 수행합니다.

## 사용 가능한 도구 (tools)

각 도구는 JSON 형식으로 호출합니다. 반드시 아래 형식을 따르세요:

### 프로젝트 관리
- project_info: 현재 프로젝트 정보 조회
- open_project: {"path": "프로젝트 경로"}
- save_project: 프로젝트 저장
- import_media: {"file_paths": ["파일 경로 목록"], "target_bin": "빈 이름(선택)"}
- create_sequence: {"name": "시퀀스 이름"}
- set_active_sequence: {"name": "시퀀스 이름"}
- list_items: {"bin_path": "빈 경로(선택)"}

### 타임라인 편집
- sequence_info: 현재 시퀀스 정보 조회
- list_clips: {"track_type": "video|audio", "track_index": 0}
- add_clip: {"item_name": "아이템 이름", "time": 0.0, "video_track": 0, "audio_track": 0}
- remove_clip: {"track_type": "video", "track_index": 0, "clip_index": 0}
- ripple_delete: {"track_type": "video", "track_index": 0, "clip_index": 0}
- move_clip: {"track_type": "video", "track_index": 0, "clip_index": 0, "new_start": 5.0}
- trim_clip: {"track_type": "video", "track_index": 0, "clip_index": 0, "new_in": 1.0, "new_out": 10.0}
- razor_cut: {"time": 5.0, "tracks": [0, 1]}
- set_speed: {"track_index": 0, "clip_index": 0, "speed": 2.0}
- play / pause / go_to: {"time": 5.0}
- current_time: 현재 재생 위치 조회
- set_work_area: {"in": 0.0, "out": 30.0}

### 이펙트 & 트랜지션
- apply_effect: {"effect": "블러", "track_index": 0, "clip_index": 0}
- remove_effect: {"effect_index": 0, "track_index": 0, "clip_index": 0}
- list_effects: {"track_index": 0, "clip_index": 0}
- set_parameter: {"component": 0, "param": "Scale", "value": 150, "track_index": 0, "clip_index": 0}
- set_opacity: {"value": 50, "track_index": 0, "clip_index": 0}
- set_position: {"x": 960, "y": 540, "track_index": 0, "clip_index": 0}
- set_scale: {"value": 120, "track_index": 0, "clip_index": 0}
- set_rotation: {"degrees": 45, "track_index": 0, "clip_index": 0}
- apply_transition: {"transition": "크로스 디졸브", "track_index": 0, "clip_index": 0, "duration": 1.0, "position": "end"}
- add_keyframe: {"component": 0, "param": "Scale", "time": 2.0, "value": 150, "track_index": 0, "clip_index": 0}

### 마커
- list_markers: 마커 목록 조회
- add_marker: {"time": 5.0, "name": "이름", "comment": "코멘트", "color": "빨강"}
- remove_marker: {"time": 5.0}
- clear_markers: 모든 마커 제거

### 내보내기
- list_presets: 사용 가능한 프리셋 목록
- export: {"output": "경로", "preset": "h264_1080p", "work_area_only": false}
- export_encoder: {"output": "경로", "preset": "h264_1080p"}
- batch_export: {"output_dir": "디렉토리", "preset": "h264_1080p", "sequences": ["시퀀스 이름"]}
- export_frame: {"output": "경로.png", "time": 5.0}

## 응답 규칙
1. 반드시 JSON 배열로 실행할 도구들을 반환하세요
2. 여러 작업이 필요하면 배열에 여러 도구를 순서대로 넣으세요
3. 응답 형식: {"actions": [{"tool": "도구이름", "params": {...}}], "message": "사용자에게 보여줄 메시지"}
4. 정보 조회가 필요한 경우 먼저 조회 도구를 호출한 후 결과를 바탕으로 다음 작업을 결정하세요
5. 한국어로 메시지를 작성하세요
"""


class PremiereAgent:
    """자연어 명령을 받아 Premiere Pro를 제어하는 AI 에이전트"""

    def __init__(self, api_key: str = None):
        self.client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.conn = PremiereConnection()
        self.project = ProjectManager(self.conn)
        self.timeline = TimelineEditor(self.conn)
        self.effects = EffectsManager(self.conn)
        self.markers = MarkerManager(self.conn)
        self.export = ExportManager(self.conn)
        self.conversation_history = []

    def connect(self) -> bool:
        """Premiere Pro에 연결합니다."""
        return self.conn.connect()

    def process_command(self, user_input: str) -> str:
        """사용자 명령을 처리하고 결과를 반환합니다."""
        # 현재 상태 컨텍스트 수집
        context = self._get_context()

        self.conversation_history.append({
            "role": "user",
            "content": f"[현재 상태]\n{context}\n\n[사용자 명령]\n{user_input}",
        })

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=self.conversation_history,
        )

        assistant_message = response.content[0].text
        self.conversation_history.append({
            "role": "assistant",
            "content": assistant_message,
        })

        # AI 응답에서 액션 파싱 & 실행
        try:
            parsed = json.loads(assistant_message)
            actions = parsed.get("actions", [])
            message = parsed.get("message", "")

            results = []
            for action in actions:
                tool = action.get("tool")
                params = action.get("params", {})
                result = self._execute_tool(tool, params)
                results.append({"tool": tool, "result": result})

            # 결과를 대화 히스토리에 추가
            if results:
                result_text = json.dumps(results, ensure_ascii=False, indent=2)
                self.conversation_history.append({
                    "role": "user",
                    "content": f"[실행 결과]\n{result_text}",
                })

                # 후속 응답 받기
                follow_up = self.client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1024,
                    system="실행 결과를 사용자에게 간결하게 한국어로 요약해주세요. JSON이 아닌 일반 텍스트로 응답하세요.",
                    messages=self.conversation_history,
                )
                summary = follow_up.content[0].text
                self.conversation_history.append({
                    "role": "assistant",
                    "content": summary,
                })
                return f"{message}\n{summary}" if message else summary

            return message

        except json.JSONDecodeError:
            # AI가 JSON이 아닌 일반 텍스트로 응답한 경우
            return assistant_message

    def _get_context(self) -> str:
        """현재 Premiere Pro 상태를 텍스트로 요약합니다."""
        try:
            if not self.conn.is_connected():
                return "Premiere Pro에 연결되지 않음"

            info = self.conn.get_info()
            context = f"Premiere Pro {info['version']}"

            if info.get("project_name"):
                context += f"\n프로젝트: {info['project_name']}"
                try:
                    seq_info = self.timeline.get_sequence_info()
                    context += f"\n활성 시퀀스: {seq_info['name']}"
                    context += f" (V{seq_info['video_tracks']}트랙, A{seq_info['audio_tracks']}트랙)"
                    context += f"\n시퀀스 길이: {seq_info['duration']}"

                    # 첫 번째 비디오 트랙 클립 요약
                    clips = self.timeline.list_clips("video", 0)
                    if clips:
                        context += f"\nV1 트랙 클립 수: {len(clips)}"
                        for c in clips[:5]:
                            context += f"\n  [{c['index']}] {c['name']} ({c['start']:.1f}s - {c['end']:.1f}s)"
                        if len(clips) > 5:
                            context += f"\n  ... 외 {len(clips) - 5}개"
                except Exception:
                    context += "\n(시퀀스 정보 없음)"

            return context
        except Exception as e:
            return f"상태 조회 실패: {e}"

    def _execute_tool(self, tool: str, params: dict) -> dict:
        """도구를 실행하고 결과를 반환합니다."""
        try:
            result = self._dispatch(tool, params)
            return {"status": "success", "data": result}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _dispatch(self, tool: str, params: dict):
        """도구 이름에 따라 적절한 메서드를 호출합니다."""

        # ── 프로젝트 관리 ──
        if tool == "project_info":
            return self.project.get_project_info()
        elif tool == "open_project":
            return self.project.open_project(params["path"])
        elif tool == "save_project":
            return self.project.save_project()
        elif tool == "import_media":
            return self.project.import_media(
                params["file_paths"], params.get("target_bin")
            )
        elif tool == "create_sequence":
            return self.project.create_sequence(params["name"])
        elif tool == "set_active_sequence":
            return self.project.set_active_sequence(params["name"])
        elif tool == "list_items":
            return self.project.list_project_items(params.get("bin_path"))

        # ── 타임라인 편집 ──
        elif tool == "sequence_info":
            return self.timeline.get_sequence_info()
        elif tool == "list_clips":
            return self.timeline.list_clips(
                params.get("track_type", "video"),
                params.get("track_index", 0),
            )
        elif tool == "add_clip":
            return self.timeline.add_clip_to_timeline(
                params["item_name"],
                params.get("time", 0.0),
                params.get("video_track", 0),
                params.get("audio_track", 0),
            )
        elif tool == "remove_clip":
            return self.timeline.remove_clip(
                params.get("track_type", "video"),
                params.get("track_index", 0),
                params["clip_index"],
            )
        elif tool == "ripple_delete":
            return self.timeline.ripple_delete(
                params.get("track_type", "video"),
                params.get("track_index", 0),
                params["clip_index"],
            )
        elif tool == "move_clip":
            return self.timeline.move_clip(
                params.get("track_type", "video"),
                params.get("track_index", 0),
                params["clip_index"],
                params["new_start"],
            )
        elif tool == "trim_clip":
            return self.timeline.trim_clip(
                params.get("track_type", "video"),
                params.get("track_index", 0),
                params["clip_index"],
                params.get("new_in"),
                params.get("new_out"),
            )
        elif tool == "razor_cut":
            return self.timeline.razor_cut(
                params["time"],
                params.get("tracks"),
            )
        elif tool == "set_speed":
            return self.timeline.set_clip_speed(
                params.get("track_index", 0),
                params["clip_index"],
                params["speed"],
            )
        elif tool == "play":
            self.timeline.play()
            return True
        elif tool == "pause":
            self.timeline.pause()
            return True
        elif tool == "go_to":
            self.timeline.go_to_time(params["time"])
            return True
        elif tool == "current_time":
            return self.timeline.get_current_time()
        elif tool == "set_work_area":
            return self.timeline.set_work_area(params["in"], params["out"])

        # ── 이펙트 & 트랜지션 ──
        elif tool == "apply_effect":
            return self.effects.apply_effect(
                params["effect"],
                params.get("track_index", 0),
                params.get("clip_index", 0),
            )
        elif tool == "remove_effect":
            return self.effects.remove_effect(
                params["effect_index"],
                params.get("track_index", 0),
                params.get("clip_index", 0),
            )
        elif tool == "list_effects":
            return self.effects.list_clip_effects(
                params.get("track_index", 0),
                params.get("clip_index", 0),
            )
        elif tool == "set_parameter":
            return self.effects.set_effect_parameter(
                params["component"],
                params["param"],
                params["value"],
                params.get("track_index", 0),
                params.get("clip_index", 0),
            )
        elif tool == "set_opacity":
            return self.effects.set_opacity(
                params["value"],
                params.get("track_index", 0),
                params.get("clip_index", 0),
            )
        elif tool == "set_position":
            return self.effects.set_position(
                params["x"], params["y"],
                params.get("track_index", 0),
                params.get("clip_index", 0),
            )
        elif tool == "set_scale":
            return self.effects.set_scale(
                params["value"],
                params.get("track_index", 0),
                params.get("clip_index", 0),
            )
        elif tool == "set_rotation":
            return self.effects.set_rotation(
                params["degrees"],
                params.get("track_index", 0),
                params.get("clip_index", 0),
            )
        elif tool == "apply_transition":
            return self.effects.apply_transition(
                params["transition"],
                params.get("track_index", 0),
                params.get("clip_index", 0),
                params.get("duration", 1.0),
                params.get("position", "end"),
            )
        elif tool == "add_keyframe":
            return self.effects.add_keyframe(
                params["component"],
                params["param"],
                params["time"],
                params["value"],
                params.get("track_index", 0),
                params.get("clip_index", 0),
            )

        # ── 마커 ──
        elif tool == "list_markers":
            return self.markers.list_markers()
        elif tool == "add_marker":
            return self.markers.add_marker(
                params["time"],
                params.get("name", ""),
                params.get("comment", ""),
                params.get("color", "green"),
                params.get("duration", 0.0),
            )
        elif tool == "remove_marker":
            return self.markers.remove_marker_at(params["time"])
        elif tool == "clear_markers":
            return self.markers.clear_all_markers()

        # ── 내보내기 ──
        elif tool == "list_presets":
            return self.export.list_presets()
        elif tool == "export":
            return self.export.export_direct(
                params["output"],
                params.get("preset", "h264_1080p"),
                params.get("work_area_only", False),
            )
        elif tool == "export_encoder":
            return self.export.export_to_encoder(
                params["output"],
                params.get("preset", "h264_1080p"),
            )
        elif tool == "batch_export":
            return self.export.batch_export(
                params["output_dir"],
                params.get("preset", "h264_1080p"),
                params.get("sequences"),
            )
        elif tool == "export_frame":
            return self.export.export_frame(
                params["output"],
                params.get("time"),
            )

        else:
            raise ValueError(f"알 수 없는 도구: {tool}")
