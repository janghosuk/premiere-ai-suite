"""Premiere Pro 연결 관리 모듈"""

import time
import subprocess
import requests


class PremiereConnection:
    """Premiere Pro와의 연결을 관리합니다.
    pymiere Link 확장을 통해 HTTP로 통신합니다.
    """

    PYMIERE_PORT = 3000
    PYMIERE_URL = f"http://localhost:{PYMIERE_PORT}"

    def __init__(self):
        self._app = None

    def connect(self) -> bool:
        """Premiere Pro에 연결합니다."""
        try:
            import pymiere
            self._app = pymiere.objects.app
            # 연결 확인을 위해 간단한 속성 접근
            _ = self._app.version
            return True
        except Exception as e:
            print(f"[연결 실패] Premiere Pro에 연결할 수 없습니다: {e}")
            print("확인사항:")
            print("  1. Premiere Pro가 실행 중인지 확인하세요")
            print("  2. Pymiere Link 확장이 설치되어 있는지 확인하세요")
            return False

    def is_connected(self) -> bool:
        """현재 연결 상태를 확인합니다."""
        try:
            if self._app is None:
                return False
            _ = self._app.version
            return True
        except Exception:
            self._app = None
            return False

    def reconnect(self, max_retries: int = 3, delay: float = 2.0) -> bool:
        """연결이 끊어진 경우 재연결을 시도합니다."""
        for i in range(max_retries):
            print(f"[재연결] 시도 {i + 1}/{max_retries}...")
            if self.connect():
                print("[재연결] 성공!")
                return True
            time.sleep(delay)
        print("[재연결] 실패. Premiere Pro 상태를 확인하세요.")
        return False

    def ensure_connected(self) -> bool:
        """연결 상태를 보장합니다. 끊어져 있으면 재연결합니다."""
        if self.is_connected():
            return True
        return self.reconnect()

    @property
    def app(self):
        """pymiere app 객체를 반환합니다."""
        if not self.ensure_connected():
            raise ConnectionError("Premiere Pro에 연결되어 있지 않습니다.")
        return self._app

    def get_info(self) -> dict:
        """Premiere Pro 기본 정보를 반환합니다."""
        app = self.app
        return {
            "version": app.version,
            "build": str(app.build),
            "project_name": app.project.name if app.project else None,
            "project_path": app.project.path if app.project else None,
        }

    def execute_jsx(self, script: str, timeout: int = 30) -> str:
        """ExtendScript 코드를 직접 실행합니다.
        pymiere로 지원되지 않는 고급 기능에 사용합니다.
        Pymiere Link는 POST http://localhost:3000 에 {"to_eval": script} 형태로 전송합니다.
        응답은 plain text로 반환됩니다.
        """
        try:
            response = requests.post(
                self.PYMIERE_URL,
                json={"to_eval": script},
                timeout=timeout,
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            raise RuntimeError(f"JSX 스크립트 실행 실패: {e}")

    def execute_jsx_file(self, file_path: str) -> str:
        """JSX 파일을 읽어서 실행합니다."""
        with open(file_path, "r", encoding="utf-8") as f:
            script = f.read()
        return self.execute_jsx(script)
