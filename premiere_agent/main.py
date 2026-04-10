"""Premiere Pro AI Agent - 대화형 CLI 인터페이스"""

import sys
import os
import io

# UTF-8 출력 강제 (Windows cp949 호환)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 프로젝트 루트와 로컬 lib 경로 추가
_project_dir = os.path.dirname(os.path.abspath(__file__))
_lib_dir = os.path.join(_project_dir, "lib")
if os.path.isdir(_lib_dir):
    sys.path.insert(0, _lib_dir)
sys.path.insert(0, _project_dir)

from agent import PremiereAgent


BANNER = """
╔══════════════════════════════════════════════════════════╗
║           🎬 Premiere Pro AI Agent                       ║
║                                                          ║
║  자연어로 Premiere Pro를 제어합니다.                      ║
║  예: "타임라인 클립 목록 보여줘"                          ║
║      "첫 번째 클립을 5초 지점에서 잘라줘"                ║
║      "두 번째 클립에 크로스 디졸브 넣어줘"               ║
║      "H.264 1080p로 내보내기 해줘"                       ║
║                                                          ║
║  종료: quit / exit / 종료                                ║
║  도움말: help / 도움말                                   ║
╚══════════════════════════════════════════════════════════╝
"""

HELP_TEXT = """
━━━ 사용 가능한 명령어 예시 ━━━

📁 프로젝트 관리:
  • "현재 프로젝트 정보 보여줘"
  • "프로젝트 저장해줘"
  • "영상 파일 임포트 해줘: C:/Videos/clip01.mp4"
  • "새 시퀀스 만들어줘: 메인 편집"
  • "시퀀스 목록 보여줘"

🎬 타임라인 편집:
  • "타임라인 클립 목록 보여줘"
  • "V1 트랙 첫 번째 클립 삭제해줘"
  • "5초 지점에서 잘라줘" (razor cut)
  • "두 번째 클립을 10초로 옮겨줘"
  • "첫 번째 클립을 2배속으로 해줘"
  • "클립 인포인트를 3초로 설정해줘"

✨ 이펙트 & 트랜지션:
  • "첫 번째 클립에 블러 효과 넣어줘"
  • "불투명도 50%로 설정해줘"
  • "클립 스케일 120%로 키워줘"
  • "크로스 디졸브 트랜지션 넣어줘"
  • "적용된 이펙트 목록 보여줘"
  • "페이드인 효과 넣어줘"

📌 마커:
  • "5초에 빨간 마커 추가해줘"
  • "마커 목록 보여줘"
  • "모든 마커 삭제해줘"

📤 내보내기:
  • "H.264 1080p로 내보내기 해줘"
  • "미디어 인코더로 보내줘"
  • "프리셋 목록 보여줘"
  • "현재 프레임 PNG로 저장해줘"
  • "모든 시퀀스 일괄 내보내기 해줘"

🎮 재생 제어:
  • "재생" / "정지" / "5초로 이동"
  • "현재 시간 알려줘"
"""


def main():
    print(BANNER)

    # API 키 확인 (.env 파일도 지원)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    if line.strip().startswith("ANTHROPIC_API_KEY="):
                        api_key = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
                        break
    if not api_key:
        print("[경고] ANTHROPIC_API_KEY가 설정되지 않았습니다.")
        print("  set ANTHROPIC_API_KEY=sk-ant-...")
        print("  또는 premiere_agent/.env 파일에 ANTHROPIC_API_KEY=sk-ant-... 를 추가하세요.")
        print("  AI 명령 파싱 없이 직접 명령 모드로 시작합니다.\n")

    agent = PremiereAgent(api_key=api_key)

    # Premiere Pro 연결
    print("[연결] Premiere Pro에 연결 중...")
    if agent.connect():
        info = agent.conn.get_info()
        print(f"[연결 성공] Premiere Pro {info['version']}")
        if info.get("project_name"):
            print(f"[프로젝트] {info['project_name']}")
    else:
        print("[경고] Premiere Pro에 연결할 수 없습니다.")
        print("  Premiere Pro를 실행하고 Pymiere Link 확장을 활성화한 후 다시 시도하세요.")
        print("  연결 없이 계속하려면 Enter를 누르세요. (일부 기능 제한)")
        input()

    # 대화 루프
    while True:
        try:
            user_input = input("\n🎬 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료합니다.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "종료", "q"):
            print("종료합니다. 작업을 저장했는지 확인하세요!")
            break

        if user_input.lower() in ("help", "도움말", "h", "?"):
            print(HELP_TEXT)
            continue

        if user_input.lower() in ("reconnect", "재연결"):
            print("[재연결] Premiere Pro에 재연결 중...")
            if agent.connect():
                print("[재연결] 성공!")
            else:
                print("[재연결] 실패.")
            continue

        if user_input.lower() in ("clear", "클리어", "초기화"):
            agent.conversation_history.clear()
            print("[초기화] 대화 기록이 초기화되었습니다.")
            continue

        if user_input.lower() in ("status", "상태"):
            context = agent._get_context()
            print(context)
            continue

        # AI 에이전트로 명령 처리
        print("[처리 중...]")
        try:
            result = agent.process_command(user_input)
            print(f"\n{result}")
        except Exception as e:
            print(f"\n[오류] {e}")
            print("  'reconnect' 명령으로 재연결을 시도하거나,")
            print("  'help' 명령으로 사용법을 확인하세요.")


if __name__ == "__main__":
    main()
