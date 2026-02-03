# Makr 프로젝트

대칭 전력 마우스/키보드 자동화를 위한 GUI 애플리케이션입니다.

## 프로젝트 구조

```
makr/
├── main.py                 # 진입점
├── app.py                  # 하위 호환성을 위한 re-export
├── packet.py               # 패킷 캡처 관리
├── core/                   # 핵심 비즈니스 로직 (UI 무관)
│   ├── config.py           # DelayConfig, UiTwoDelayConfig, 상수
│   ├── persistence.py      # 경로 유틸, 상태 저장/로드
│   ├── tasks.py            # RepeatingTask (반복 작업)
│   ├── sound.py            # SoundPlayer, BeepNotifier
│   ├── state.py            # DevLogicState, UI2AutomationState
│   └── channel.py          # ChannelSegmentRecorder, 채널 감지
├── controllers/            # UI와 Core 연결
│   ├── macro_controller.py # MacroController (UI1 매크로)
│   ├── ui2_controller.py   # UI2Controller (월재 자동화)
│   └── channel_detection.py# ChannelDetectionSequence (F10)
└── ui/                     # 프레젠테이션 레이어
    ├── app.py              # MakrApplication 메인 클래스
    ├── styles.py           # 탭 스타일, 색상 상수
    ├── widgets/            # 재사용 가능한 위젯
    │   ├── coordinate_row.py # 좌표 입력 위젯
    │   └── delay_row.py    # 딜레이 입력 위젯
    ├── panels/             # 탭 패널
    │   ├── ui1_panel.py    # UI1 (채변) 패널
    │   └── ui2_panel.py    # UI2 (월재) 패널
    └── windows/            # 보조 창
        ├── test_window.py  # 채널목록 창
        └── record_window.py# 월재기록 창
```

## 주요 기능

### 핫키
- **F9**: UI1에서 Esc 후 1단계 실행 (reset_and_run_first)
- **F10**: 채널 감지 시퀀스 시작/중지
- **F11**: UI2에서 F4 배치 실행
- **F12**: UI2에서 F6 실행 또는 자동화 중단

### UI1 (채변)
- pos1(메뉴), pos2(채널), pos3(열), pos4(∇), esc_click 좌표 등록
- pos3는 1~6열 모드 지원
- 딜레이 설정: F2 전/후, F1 전/후, 반복 횟수

### UI2 (월재)
- pos11(···), pos12(🔃), pos13(로그인), pos14(캐릭터) 좌표 등록
- 자동화 모드: 신규채널 → 일반채널 → 선택창 감지 시퀀스
- F4/F5/F6 딜레이 설정

## 핵심 클래스

### MakrApplication (`ui/app.py`)
메인 애플리케이션 클래스. 모든 컴포넌트를 조율합니다.

### MacroController (`controllers/macro_controller.py`)
UI1 매크로 실행을 관리합니다.
- `run_step()`: 현재 단계 실행
- `reset_and_run_first()`: Esc 후 1단계 재실행

### UI2Controller (`controllers/ui2_controller.py`)
UI2 자동화 로직을 관리합니다.
- `run_f4()`, `run_f5()`, `run_f6()`: 각 기능 실행
- `start_automation()`, `stop_automation()`: 자동화 제어

### ChannelDetectionSequence (`controllers/channel_detection.py`)
F10 채널 감지 시퀀스를 관리합니다.
- 채널명 감시 → 신규 채널 발견 시 F1 실행

### RepeatingTask (`core/tasks.py`)
반복 작업을 위한 통합 클래스.
- `start()`: 커스텀 액션 반복
- `start_click()`: 마우스 클릭 반복

## 상태 관리

### DevLogicState (`core/state.py`)
DevLogic 패킷 감지 상태를 관리합니다.
- `last_detected_at`: 마지막 감지 시간
- `last_packet`: 마지막 패킷 내용
- `last_is_new_channel`: 신규 채널 여부

### UI2AutomationState (`core/state.py`)
UI2 자동화 상태를 관리합니다.
- `active`: 자동화 활성화 여부
- `waiting_for_new_channel`: 신규 채널 대기 중
- `waiting_for_normal_channel`: 일반 채널 대기 중
- `waiting_for_selection`: 선택창 대기 중

## 설정 파일

앱 상태는 JSON 형식으로 저장됩니다:
- Windows: `%LOCALAPPDATA%/makr/app_state.json`
- macOS: `~/Library/Application Support/makr/app_state.json`
- Linux: `~/.config/makr/app_state.json`

## 개발 가이드

### 실행
```bash
python -m makr.main
# 또는
python -m makr.app  # 하위 호환
```

### 의존성
- `pyautogui`: 마우스/키보드 자동화
- `pynput`: 글로벌 핫키 리스너
- `scapy`: 패킷 캡처 (선택적)

### 코드 스타일
- 타입 힌트 사용
- 한글 UI 텍스트
- 영문 코드/주석

### 테스트
```bash
python -c "from makr.ui.app import MakrApplication; print('OK')"
```

## 아키텍처 원칙

1. **레이어 분리**: core(비즈니스 로직) → controllers(연결) → ui(프레젠테이션)
2. **단일 책임**: 각 모듈은 하나의 명확한 역할
3. **하위 호환성**: 기존 `makr.app` 임포트 유지
4. **상태 캡슐화**: nonlocal 대신 상태 클래스 사용
