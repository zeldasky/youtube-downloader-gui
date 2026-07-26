# YouTube 다운로더

`yt-dlp` 를 감싼 Windows GUI 앱. **포터블판은 아무 의존성 없이 단독 실행**된다.

## 산출물

| 항목 | 설명 |
|------|------|
| `YouTube다운로더_포터블.zip` (87.6MB) | **배포용.** 다른 사람에게 이 파일만 주면 된다 |
| `dist\YouTubeDownloader\` (185.3MB) | 압축 전 포터블 폴더 |
| `ytdl_gui.py` | 앱 소스 |
| `build_portable.ps1` | 재빌드 스크립트 |
| `사용법.txt` | 받는 사람용 안내문 (ZIP 안에 동봉됨) |
| `YouTube 다운로더.vbs` | 소스에서 바로 실행하는 런처 (개발용) |

## 배포 방법

`YouTube다운로더_포터블.zip` 을 전달 → 받는 사람은 압축을 풀고 **`YouTube 다운로더.exe`** 더블클릭.

설치할 것이 없다. Python, ffmpeg, Node.js 모두 불필요하다.

> 폴더를 통째로 옮겨야 한다. `exe` 하나만 빼내면 동작하지 않는다 (`bin`, `_internal` 필요).

## 내장 구성 요소

| 파일 | 버전 | 역할 | 라이선스 |
|------|------|------|----------|
| `bin\yt-dlp.exe` | 2026.07.04 | 다운로드 | Unlicense |
| `bin\ffmpeg.exe` + `ffprobe.exe` + DLL | n8.1.2 | 화질 병합·MP3 변환 | LGPL v2.1+ |
| `bin\qjs.exe` | QuickJS-ng 0.15.1 | 유튜브 추출용 JS 엔진 | MIT |

**JS 런타임을 왜 넣었나:** 최근 yt-dlp 는 YouTube 추출에 JavaScript 런타임을 요구하고 기본 지원은 `deno` 하나뿐이다. 없어도 지금은 동작하지만 yt-dlp 가 deprecated 로 표시한 경로라 언제 막힐지 모른다. Deno(110MB)·Node(50MB) 대신 **QuickJS(1.7MB)** 를 넣어 1.7MB로 해결했다.

**ffmpeg 빌드 선택:** 배포를 고려해 GPL 대신 **LGPL shared** 빌드를 썼다. `libmp3lame` 이 포함되어 MP3 인코딩이 정상 동작하는 것을 확인했다. `ffplay.exe`(17MB)는 쓰지 않아 제외했다. ffmpeg 는 별도 프로세스로 호출만 하므로 링크 의무는 발생하지 않고, 라이선스 전문(`bin\FFMPEG-LICENSE.txt`)과 소스 출처만 동봉하면 된다.

## 기능

- 링크 여러 개를 목록에 넣고 순차 다운로드 (클립보드 붙여넣기 지원)
- 비디오(MP4) / 오디오(MP3) 선택
- 품질 상·중·하
- 저장 폴더 선택 및 탐색기로 열기
- 진행률·속도·ETA 표시, 중지
- yt-dlp 원본 로그 창
- 설정 자동 저장 (`%APPDATA%\YoutubeDownloader\config.json`)

### 품질 기준

| 품질 | 비디오 | 오디오 |
|------|--------|--------|
| 상 | 최대 2160p (4K) | MP3 약 320kbps |
| 중 | 최대 1080p (FHD) | MP3 약 192kbps |
| 하 | 최대 480p (SD) | MP3 약 128kbps |

원본을 초과할 수는 없다. 원본이 720p 면 "상" 을 골라도 720p 다.

## 메뉴

- **파일** — 저장 폴더 선택 / 열기 / 종료
- **도구** — 다운로더 실행 파일 지정, 버전 확인, 업데이트, 로그 지우기
- **도움말** — 정보 (감지된 구성 요소 경로 확인 가능)

## 재빌드

```powershell
powershell -ExecutionPolicy Bypass -File build_portable.ps1
```

`ytdl_gui.py` 수정 후 실행하면 `dist\` 와 ZIP 이 다시 만들어진다. 바이너리는 `_bincache\` 에 캐시되어 재다운로드하지 않는다.

빌드에는 PyInstaller 가 필요하다 (`python -m pip install pyinstaller`, 현재 6.21.0 설치됨).

> `--noconfirm` 이 `dist` 를 비우므로 **빌드 후에** `bin` 을 복사해야 한다. 스크립트는 이 순서를 지킨다.

## 문제 해결

`--selftest` 로 구성 요소 탐지 상태를 점검할 수 있다.

```powershell
& "dist\YouTubeDownloader\YouTube 다운로더.exe" --selftest
type "$env:TEMP\ytdl_selftest.txt"
```

windowed 빌드는 콘솔이 없어 결과를 파일로 남긴다. 각 바이너리를 실제로 실행해 버전까지 확인한다.

## 탐지 순서

앱은 실행할 때마다 이 순서로 구성 요소를 찾는다.

1. 내장 `bin\` 폴더 ← 포터블판은 여기서 전부 해결
2. 앱 폴더
3. 시스템 `PATH`
4. 알려진 설치 경로 (KMPlayer 동봉본 등)

내장본이 없으면 시스템 설치본으로 자동 대체되므로, 소스에서 직접 실행할 때도 그대로 동작한다.

## 검증 기록

압축을 푼 뒤 `PATH` 에서 시스템 Python·Node·ffmpeg 를 모두 제거한 상태로 확인했다.

- 구성 요소 4종 전부 내장본으로 탐지, 각각 실행 성공
- 4K 다운로드 (3840×2160 AV1, 709MB) — 영상+음성 병합 성공
- MP3 변환 — 썸네일·메타데이터 임베드 성공
- GUI 정상 표시 (창 제목 `YouTube 다운로더 v1.0`)
- 폴더 경로를 바꿔도 동작 (경로 비의존)

## 참고

- 서명되지 않은 실행 파일이라 백신이 처음 실행을 막을 수 있다.
- 유튜브 사양 변경으로 다운로드가 깨지면 **[도구] > [다운로더 업데이트]** 로 yt-dlp 를 갱신한다.
- 본인이 권한을 가진 콘텐츠에 대해서만 사용할 것.
