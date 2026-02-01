# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

makr은 macOS 및 Windows용 순차적 마우스 클릭/키보드 입력 자동화 도구입니다. Tkinter GUI와 Scapy 기반 패킷 캡처를 활용하여 게임/애플리케이션 자동화를 수행합니다.

## 빌드 및 실행 명령

```bash
# 의존성 설치
pip install -r requirements.txt

# GUI 애플리케이션 실행
python -m makr.app

# 성능 프로파일링 (모듈)
python -m makr.perf_tool --module makr.packet --limit 30 --threshold-ms 1 --output perf_report.txt

# 성능 프로파일링 (스크립트)
python -m makr.perf_tool --script path/to/script.py -- args

# pstats 바이너리 파일 생성
python -m makr.perf_tool --module makr.app --stats-file stats.prof
```

## 아키텍처

### 핵심 구조

- **makr/app.py**: 메인 GUI 애플리케이션 (1800+ lines)
  - `MacroController`: 실행 시퀀스 및 좌표 관리
  - `RepeatingClickTask` / `RepeatingActionTask`: 백그라운드 스레드 반복 작업
  - `SoundPlayer`: 크로스플랫폼 오디오 재생
  - `PacketCaptureManager`: 패킷 캡처 통합
  - `ChannelDetectionSequence`: 채널 감지 워크플로우
  - 탭 기반 UI: UI1("채변"), UI2("월재")

- **makr/packet.py**: Scapy AsyncSniffer 래퍼
  - 스레드 안전 패킷 캡처
  - 포트 32800 필터링, UTF-8 페이로드 디코딩
  - 콜백 기반 아키텍처

- **makr/perf_tool.py**: cProfile 기반 성능 분석 도구

### 스레딩 모델

- 메인 스레드: Tkinter GUI 이벤트 루프
- 백그라운드 스레드: 클릭/액션 반복, 패킷 캡처, 핫키 리스너
- UI 업데이트: `root.after(0, callback)`으로 스레드 안전하게 처리
- 정리 종료: `threading.Event`로 stop 신호 전달

### 상태 저장 경로

- Windows: `%LOCALAPPDATA%/makr/app_state.json`
- macOS: `~/Library/Application Support/makr/app_state.json`
- Linux: `~/.config/makr/app_state.json`

### 핫키 매핑

- F9: 리셋 후 실행 (UI1)
- F10: 채널 감지 시퀀스 토글
- F11: F4 일괄 실행 (UI2)
- F12: 캐릭터 선택 (UI2) 또는 자동화 중지

### 채널 감지 패턴

패킷 페이로드에서 "DevLogic", "AdminLevel" 마커를 파싱하고, 정규식 `[A-Z][가-힣]\d{2,3}` 패턴으로 채널명 추출

## 주요 패턴 및 규칙

- 모든 딜레이 값은 밀리초(ms) 단위로 입력, `time.sleep()` 호출 시 초 단위로 변환
- 타입 힌트 사용: `from __future__ import annotations`
- UI 텍스트 및 주석은 한국어로 작성
- macOS에서는 접근성 권한 승인 필요 (시스템 환경설정)

## 의존성

- `pyautogui>=0.9.54`: 크로스플랫폼 마우스/키보드 제어
- `pynput>=1.7.6`: 저수준 입력 장치 제어
- `scapy>=2.5.0`: 패킷 캡처 및 조작
