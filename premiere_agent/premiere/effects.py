"""이펙트 & 트랜지션 모듈"""

from .connection import PremiereConnection


class EffectsManager:
    """비디오/오디오 이펙트와 트랜지션을 관리합니다."""

    # 자주 사용하는 이펙트 매핑 (한글 → ExtendScript 이름)
    EFFECT_MAP = {
        "블러": "Gaussian Blur",
        "가우시안 블러": "Gaussian Blur",
        "샤프닝": "Sharpen",
        "모자이크": "Mosaic",
        "흑백": "Black & White",
        "컬러 보정": "Lumetri Color",
        "루메트리": "Lumetri Color",
        "크롭": "Crop",
        "불투명도": "Opacity",
        "모션": "Motion",
        "울트라 키": "Ultra Key",
        "크로마키": "Ultra Key",
        "밝기/대비": "Brightness & Contrast",
        "색조/채도": "Hue/Saturation",
        "반전": "Invert",
        "글로우": "Glow",
        "노이즈": "Noise",
        "왜곡": "Twirl",
    }

    TRANSITION_MAP = {
        "크로스 디졸브": "Cross Dissolve",
        "디졸브": "Cross Dissolve",
        "디핑 블랙": "Dip to Black",
        "디핑 화이트": "Dip to White",
        "페이드": "Film Dissolve",
        "필름 디졸브": "Film Dissolve",
        "와이프": "Wipe",
        "슬라이드": "Slide",
        "푸시": "Push",
    }

    def __init__(self, conn: PremiereConnection):
        self.conn = conn

    @property
    def active_sequence(self):
        seq = self.conn.app.project.activeSequence
        if not seq:
            raise RuntimeError("활성 시퀀스가 없습니다.")
        return seq

    # ─── 이펙트 적용 ──────────────────────────────

    def apply_effect(
        self,
        effect_name: str,
        track_index: int = 0,
        clip_index: int = 0,
    ) -> bool:
        """클립에 이펙트를 적용합니다.

        Args:
            effect_name: 이펙트 이름 (한글 또는 영문)
            track_index: 비디오 트랙 번호
            clip_index: 클립 인덱스
        """
        # 한글 이름을 영문으로 변환
        en_name = self.EFFECT_MAP.get(effect_name, effect_name)

        jsx = f"""
        var seq = app.project.activeSequence;
        var clip = seq.videoTracks[{track_index}].clips[{clip_index}];
        var effects = app.project.activeSequence.videoTracks[{track_index}].clips[{clip_index}];

        // QE를 통한 이펙트 적용
        var qeSeq = qe.project.getActiveSequence();
        var qeTrack = qeSeq.getVideoTrackAt({track_index});
        var qeClip = qeTrack.getItemAt({clip_index});
        qeClip.addVideoEffect(qe.project.getVideoEffectByName("{en_name}"));
        "success";
        """
        result = self.conn.execute_jsx(jsx)
        return "success" in result

    def remove_effect(
        self,
        effect_index: int,
        track_index: int = 0,
        clip_index: int = 0,
    ) -> bool:
        """클립에서 이펙트를 제거합니다.

        Args:
            effect_index: 제거할 이펙트 인덱스 (0 = 첫 번째 적용된 이펙트)
            track_index: 비디오 트랙 번호
            clip_index: 클립 인덱스
        """
        jsx = f"""
        var clip = app.project.activeSequence.videoTracks[{track_index}].clips[{clip_index}];
        var components = clip.components;
        // 기본 컴포넌트(Motion, Opacity)를 건너뛰고 사용자 이펙트에 접근
        var userEffectIdx = {effect_index} + 2;  // Motion(0) + Opacity(1)
        if (userEffectIdx < components.numItems) {{
            components[userEffectIdx].remove();
            "success";
        }} else {{
            "effect_not_found";
        }}
        """
        result = self.conn.execute_jsx(jsx)
        return "success" in result

    # ─── 이펙트 파라미터 수정 ──────────────────────

    def list_clip_effects(self, track_index: int = 0, clip_index: int = 0) -> list[dict]:
        """클립에 적용된 이펙트와 파라미터를 나열합니다."""
        seq = self.active_sequence
        clip = seq.videoTracks[track_index].clips[clip_index]
        components = clip.components

        effects = []
        for i in range(components.numItems):
            comp = components[i]
            params = []
            for j in range(comp.properties.numItems):
                prop = comp.properties[j]
                try:
                    value = prop.getValue()
                except Exception:
                    value = "N/A"
                params.append({
                    "name": prop.displayName,
                    "value": value,
                })
            effects.append({
                "index": i,
                "name": comp.displayName,
                "parameters": params,
            })
        return effects

    def set_effect_parameter(
        self,
        component_index: int,
        param_name: str,
        value,
        track_index: int = 0,
        clip_index: int = 0,
    ) -> bool:
        """이펙트 파라미터 값을 변경합니다.

        Args:
            component_index: 컴포넌트 인덱스 (0=Motion, 1=Opacity, 2+=사용자 이펙트)
            param_name: 파라미터 이름
            value: 설정할 값
        """
        seq = self.active_sequence
        clip = seq.videoTracks[track_index].clips[clip_index]
        comp = clip.components[component_index]

        for i in range(comp.properties.numItems):
            prop = comp.properties[i]
            if prop.displayName == param_name:
                prop.setValue(value, updateUI=True)
                return True

        raise ValueError(f"파라미터를 찾을 수 없습니다: {param_name}")

    # ─── 모션 & 불투명도 (기본 컴포넌트) ──────────

    def set_opacity(
        self, value: float, track_index: int = 0, clip_index: int = 0
    ) -> bool:
        """클립의 불투명도를 설정합니다 (0-100)."""
        return self.set_effect_parameter(1, "Opacity", value, track_index, clip_index)

    def set_position(
        self, x: float, y: float, track_index: int = 0, clip_index: int = 0
    ) -> bool:
        """클립의 위치를 설정합니다."""
        seq = self.active_sequence
        clip = seq.videoTracks[track_index].clips[clip_index]
        motion = clip.components[0]  # Motion component
        for i in range(motion.properties.numItems):
            prop = motion.properties[i]
            if prop.displayName == "Position":
                prop.setValue([x, y], updateUI=True)
                return True
        return False

    def set_scale(
        self, value: float, track_index: int = 0, clip_index: int = 0
    ) -> bool:
        """클립의 스케일을 설정합니다 (100 = 원본 크기)."""
        return self.set_effect_parameter(0, "Scale", value, track_index, clip_index)

    def set_rotation(
        self, degrees: float, track_index: int = 0, clip_index: int = 0
    ) -> bool:
        """클립의 회전 값을 설정합니다."""
        return self.set_effect_parameter(0, "Rotation", degrees, track_index, clip_index)

    # ─── 트랜지션 ──────────────────────────────────

    def apply_transition(
        self,
        transition_name: str,
        track_index: int = 0,
        clip_index: int = 0,
        duration_seconds: float = 1.0,
        position: str = "start",
    ) -> bool:
        """클립에 트랜지션을 적용합니다.

        Args:
            transition_name: 트랜지션 이름 (한글 또는 영문)
            track_index: 비디오 트랙 번호
            clip_index: 클립 인덱스
            duration_seconds: 트랜지션 길이 (초)
            position: "start", "end", "both"
        """
        en_name = self.TRANSITION_MAP.get(transition_name, transition_name)
        duration_ticks = int(duration_seconds * 254016000000)

        jsx = f"""
        var qeSeq = qe.project.getActiveSequence();
        var qeTrack = qeSeq.getVideoTrackAt({track_index});
        var qeClip = qeTrack.getItemAt({clip_index});

        var transition = qe.project.getVideoTransitionByName("{en_name}");
        """

        if position in ("start", "both"):
            jsx += f"""
        qeClip.addTransition(transition, true, "{duration_ticks}");
        """
        if position in ("end", "both"):
            jsx += f"""
        qeClip.addTransition(transition, false, "{duration_ticks}");
        """

        jsx += '"success";'
        result = self.conn.execute_jsx(jsx)
        return "success" in result

    # ─── 키프레임 ──────────────────────────────────

    def add_keyframe(
        self,
        component_index: int,
        param_name: str,
        time_seconds: float,
        value,
        track_index: int = 0,
        clip_index: int = 0,
    ) -> bool:
        """파라미터에 키프레임을 추가합니다.

        Args:
            component_index: 컴포넌트 인덱스
            param_name: 파라미터 이름
            time_seconds: 키프레임 시간 (초, 클립 내 상대 시간)
            value: 키프레임 값
        """
        seq = self.active_sequence
        clip = seq.videoTracks[track_index].clips[clip_index]
        comp = clip.components[component_index]

        for i in range(comp.properties.numItems):
            prop = comp.properties[i]
            if prop.displayName == param_name:
                if not prop.isTimeVarying():
                    prop.setTimeVarying(True)
                prop.addKey(time_seconds)
                prop.setValueAtKey(time_seconds, value, updateUI=True)
                return True

        raise ValueError(f"파라미터를 찾을 수 없습니다: {param_name}")
