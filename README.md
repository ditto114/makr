# makr

간단한 macOS용 단계별 자동화 도구입니다. Tkinter 기반 GUI를 최상단에 띄워 두고 `실행`/`다시` 버튼으로 마우스 클릭과 키 입력을 순차적으로 수행합니다.

## 동작 방식
- **실행 버튼**: 현재 단계의 동작을 실행합니다.
  - 1단계: pos1 좌표 클릭 → 0.1초 대기 → pos2 좌표 클릭
  - 2단계: pos3 좌표 클릭 → Enter 키 입력
  - 모든 단계를 수행하면 다시 1단계부터 반복합니다.
- **다시 버튼**: Esc 키를 입력한 뒤 1단계를 즉시 재실행합니다. 이후 `실행` 버튼을 누르면 2단계로 이어집니다.

## 사용법
1. `pip install -r requirements.txt`로 의존성을 설치합니다. (macOS에서 보안 승인 필요할 수 있습니다.)
2. `python -m makr.app`으로 GUI를 실행합니다.
3. `pos1`, `pos2`, `pos3`에 각각 클릭할 좌표의 X, Y 값을 입력합니다.
4. 창이 항상 최상단에 유지된 상태에서 `실행` 또는 `다시` 버튼을 눌러 동작을 제어합니다.

> pyautogui의 마우스/키보드 제어를 허용하도록 macOS 보안 설정(손쉬운 사용)을 승인해야 합니다.

## 성능 테스트 도구
테스트 과정에서 병목 지점을 빠르게 파악하려면 내장 프로파일러 CLI를 사용하세요.

- 모듈 실행 프로파일링: `python -m makr.perf_tool --module makr.packet --limit 30 --threshold-ms 1 --output perf_report.txt`
- 스크립트 파일 프로파일링: `python -m makr.perf_tool --script path/to/script.py -- perf_target_args`

보고서는 `perf_report.txt`에 기록되며, `--stats-file` 옵션으로 pstats 바이너리를 추가 저장해 다른 시각화 도구에서 열 수 있습니다.
