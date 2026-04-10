# Clip Exporter 설치 및 사용 가이드

Premiere Pro 타임라인의 모든 클립을 한 번에 각각 익스포트하고, 각 클립의
첫 프레임을 스틸 이미지로 저장하는 CEP 패널 플러그인.

## 1. 설치

### 1-1. CEP Debug Mode 활성화 (최초 1회)

Windows:
```cmd
reg add HKCU\Software\Adobe\CSXS.11 /v PlayerDebugMode /t REG_SZ /d 1 /f
reg add HKCU\Software\Adobe\CSXS.12 /v PlayerDebugMode /t REG_SZ /d 1 /f
```

### 1-2. 플러그인 파일 배포

아래 경로에 `com.premiere.clip.exporter` 폴더 전체를 복사:

```
C:\Users\<사용자>\AppData\Roaming\Adobe\CEP\extensions\com.premiere.clip.exporter\
```

폴더 구조:
```
com.premiere.clip.exporter/
├── CSXS/manifest.xml
├── index.html
├── css/style.css
├── js/CSInterface.js
├── js/main.js
└── jsx/export.jsx
```

### 1-3. Premiere Pro 재시작

Premiere Pro 메뉴 > **창 > 확장 > Clip Exporter** 에서 패널 열기.

## 2. Export 프리셋 준비 (최초 1회)

`exportAsMediaDirect` API는 Premiere 프리셋 파일(.epr)이 필요합니다.

1. Premiere 메뉴: **파일 > 내보내기 > 미디어**
2. 형식/품질/해상도 등 원하는 설정 구성
3. **"프리셋 저장"** 버튼 클릭
4. 이름 지정 후 저장 (예: `MyPreset_H264_1080p.epr`)
5. 저장 위치:
   `C:\Users\<사용자>\Documents\Adobe\Adobe Media Encoder\<버전>\Presets\`

## 3. 사용 방법

1. Premiere에서 시퀀스 열기 (Scene Edit Detection 등으로 클립이 자른 상태)
2. 패널의 **⟳** 버튼으로 시퀀스 정보 새로고침
3. **출력 폴더** 선택
4. **Export 프리셋 (.epr)** 선택 (한 번 설정하면 다음부터 자동 기억)
5. **파일명 패턴** 확인 (`{sequence}_Clip_{num}` 등)
6. **각 클립의 첫 프레임 캡처** 체크 (선택)
7. **▶ 타임라인 클립 일괄 익스포트** 클릭

결과 구조:
```
출력 폴더/
├── MySeq_Clip_001.mp4
├── MySeq_Clip_002.mp4
├── MySeq_Clip_003.mp4
├── ...
└── thumbnails/
    ├── MySeq_Clip_001.jpg
    ├── MySeq_Clip_002.jpg
    └── ...
```

## 4. 파일명 패턴 토큰

| 토큰 | 의미 | 예시 |
|---|---|---|
| `{sequence}` | 시퀀스 이름 | `MyTimeline` |
| `{num}` | 클립 번호 (3자리 0 패딩) | `001`, `002` |
| `{name}` | 클립 이름 | `video.mp4` |

## 5. 주의사항

- **`exportAsMediaDirect`는 동기식 블로킹 호출**입니다. 전체 클립 익스포트 중에는
  Premiere UI가 응답하지 않을 수 있습니다. 이는 정상입니다.
- **첫 번째 비디오 트랙(V1)의 클립만** 처리합니다.
- 클립 개수와 길이에 비례해 시간이 걸립니다 (H.264 1080p 기준 클립당 5~30초).
- 프리셋의 출력 형식과 `파일명 패턴`의 확장자가 일치하도록 주의하세요.

## 6. 트러블슈팅

### 패널이 메뉴에 안 보임
- CEP Debug Mode 활성화 확인
- `CSXS.11`, `CSXS.12` 둘 다 등록 (Premiere 버전에 따라)
- Premiere 완전 종료 후 재실행

### "프리셋 파일을 찾을 수 없음" 오류
- 경로에 한글/특수문자가 있으면 영문 경로로 복사
- 절대 경로 사용 (`C:/Users/...`)

### 익스포트 실패
- 프리셋과 소스 해상도/프레임레이트 호환성 확인
- 출력 폴더 쓰기 권한 확인
- Premiere Pro의 Events 패널에서 상세 로그 확인
