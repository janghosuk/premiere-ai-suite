"""렌더링 & 내보내기 모듈"""

import os
import time
from .connection import PremiereConnection


class ExportManager:
    """시퀀스 렌더링 및 내보내기를 관리합니다."""

    # 일반적으로 사용하는 내보내기 프리셋 경로 (Windows)
    PRESET_BASE = os.path.join(
        os.environ.get("PROGRAMFILES", "C:\\Program Files"),
        "Adobe",
        "Adobe Premiere Pro 2024",
        "MediaIO",
        "systempresets",
    )

    # 자주 사용하는 프리셋 매핑
    PRESETS = {
        "h264_1080p": "MatchSource-H.264-Medium Bitrate.epr",
        "h264_4k": "MatchSource-H.264-High Bitrate.epr",
        "h265_1080p": "MatchSource-H.265-Medium Bitrate.epr",
        "prores_422": "Apple ProRes 422.epr",
        "prores_4444": "Apple ProRes 4444.epr",
        "dnxhd": "DNxHD.epr",
        "youtube_1080p": "YouTube 1080p Full HD.epr",
        "youtube_4k": "YouTube 2160p 4K Ultra HD.epr",
        "vimeo_1080p": "Vimeo 1080p Full HD.epr",
    }

    def __init__(self, conn: PremiereConnection):
        self.conn = conn

    @property
    def active_sequence(self):
        seq = self.conn.app.project.activeSequence
        if not seq:
            raise RuntimeError("활성 시퀀스가 없습니다.")
        return seq

    def list_presets(self) -> list[str]:
        """사용 가능한 내보내기 프리셋 키 목록을 반환합니다."""
        return list(self.PRESETS.keys())

    def export_direct(
        self,
        output_path: str,
        preset_key: str = "h264_1080p",
        work_area_only: bool = False,
    ) -> bool:
        """시퀀스를 직접 렌더링하여 내보냅니다.

        Args:
            output_path: 출력 파일 경로 (확장자 포함)
            preset_key: 프리셋 키 (list_presets() 참조)
            work_area_only: True이면 작업 영역만 렌더링
        """
        seq = self.active_sequence

        preset_name = self.PRESETS.get(preset_key)
        if not preset_name:
            raise ValueError(
                f"알 수 없는 프리셋: {preset_key}. "
                f"사용 가능: {', '.join(self.PRESETS.keys())}"
            )

        # 프리셋 파일 경로 찾기
        preset_path = self._find_preset(preset_name)
        if not preset_path:
            # 커스텀 프리셋 경로 시도 (사용자 프리셋 폴더)
            preset_path = self._find_user_preset(preset_name)

        if not preset_path:
            raise FileNotFoundError(
                f"프리셋 파일을 찾을 수 없습니다: {preset_name}. "
                f"Premiere Pro에서 해당 프리셋이 설치되어 있는지 확인하세요."
            )

        # 출력 디렉토리 확인
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        # 내보내기 범위 설정
        # 0 = 전체 시퀀스, 1 = 작업 영역
        scope = 1 if work_area_only else 0

        seq.exportAsMediaDirect(
            output_path,
            preset_path,
            scope,
        )
        print(f"[내보내기] 완료: {output_path}")
        return True

    def export_to_encoder(
        self,
        output_path: str,
        preset_key: str = "h264_1080p",
        work_area_only: bool = False,
    ) -> bool:
        """Adobe Media Encoder로 내보내기를 큐에 추가합니다.

        Args:
            output_path: 출력 파일 경로
            preset_key: 프리셋 키
            work_area_only: 작업 영역만 렌더링
        """
        seq = self.active_sequence

        preset_name = self.PRESETS.get(preset_key, preset_key)
        preset_path = self._find_preset(preset_name) or self._find_user_preset(preset_name)

        if not preset_path:
            raise FileNotFoundError(f"프리셋 파일을 찾을 수 없습니다: {preset_name}")

        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        scope = 1 if work_area_only else 0

        # Encoder에 큐 추가
        app = self.conn.app
        encoder = app.encoder
        encoder.launchEncoder()
        encoder.encodeSequence(
            seq,
            output_path,
            preset_path,
            scope,
            removeOnCompletion=True,
        )
        print(f"[인코더] 큐에 추가됨: {output_path}")
        return True

    def batch_export(
        self,
        output_dir: str,
        preset_key: str = "h264_1080p",
        sequences: list[str] = None,
    ) -> list[str]:
        """여러 시퀀스를 일괄 내보내기합니다.

        Args:
            output_dir: 출력 디렉토리
            preset_key: 프리셋 키
            sequences: 시퀀스 이름 목록 (None이면 모든 시퀀스)

        Returns:
            내보내기 큐에 추가된 파일 경로 목록
        """
        project = self.conn.app.project
        os.makedirs(output_dir, exist_ok=True)

        queued_files = []
        for i in range(project.sequences.numSequences):
            seq = project.sequences[i]
            if sequences and seq.name not in sequences:
                continue

            output_path = os.path.join(output_dir, f"{seq.name}.mp4")
            project.activeSequence = seq

            try:
                self.export_to_encoder(output_path, preset_key)
                queued_files.append(output_path)
            except Exception as e:
                print(f"[경고] {seq.name} 내보내기 실패: {e}")

        print(f"[일괄 내보내기] {len(queued_files)}개 시퀀스 큐에 추가됨")
        return queued_files

    def export_frame(self, output_path: str, time_seconds: float = None) -> bool:
        """현재 프레임(또는 특정 시간)을 이미지로 내보냅니다.

        Args:
            output_path: 출력 이미지 경로 (.png, .jpg 등)
            time_seconds: 캡처할 시간 (None이면 현재 재생 위치)
        """
        jsx = f"""
        var seq = app.project.activeSequence;
        """
        if time_seconds is not None:
            jsx += f"""
        var time = new Time();
        time.seconds = {time_seconds};
        seq.setPlayerPosition(time.ticks);
        """

        output_escaped = output_path.replace("\\", "/")
        jsx += f"""
        seq.exportFramePNG(
            "{output_escaped}",
            seq.getPlayerPosition()
        );
        "success";
        """
        result = self.conn.execute_jsx(jsx)
        return "success" in result

    def _find_preset(self, preset_name: str) -> str | None:
        """시스템 프리셋 경로에서 프리셋을 찾습니다."""
        if not os.path.exists(self.PRESET_BASE):
            # 다른 버전 시도
            for year in ["2025", "2024", "2023", "2022"]:
                alt_base = self.PRESET_BASE.replace("2024", year)
                if os.path.exists(alt_base):
                    return self._search_preset_dir(alt_base, preset_name)
            return None
        return self._search_preset_dir(self.PRESET_BASE, preset_name)

    def _find_user_preset(self, preset_name: str) -> str | None:
        """사용자 프리셋 폴더에서 찾습니다."""
        user_preset_dir = os.path.join(
            os.environ.get("APPDATA", ""),
            "Adobe",
            "Common",
            "AME",
            "Presets",
        )
        if os.path.exists(user_preset_dir):
            return self._search_preset_dir(user_preset_dir, preset_name)
        return None

    def _search_preset_dir(self, base_dir: str, preset_name: str) -> str | None:
        """디렉토리를 재귀 검색하여 프리셋 파일을 찾습니다."""
        for root, dirs, files in os.walk(base_dir):
            for f in files:
                if f == preset_name or f.lower() == preset_name.lower():
                    return os.path.join(root, f)
        return None
