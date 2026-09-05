# 검증 스크립트

v4 계층 분리 때 만든 것들. **P2 작업 뒤 회귀 확인에 그대로 쓴다.**

콘솔이 CP949 라 로그의 이모지에서 죽는다. 반드시 UTF-8 로 실행할 것:

```bash
cd ..                                   # 프로젝트 루트에서
PYTHONIOENCODING=utf-8 python tests/test_detection.py
```

| 파일 | 무엇을 확인하나 | 기준 |
|---|---|---|
| `test_detection.py` | D-01 — 임계값이 다른 템플릿 2개에서 이름·좌표가 일치하는가 | A 만 검출, 좌표 ±2px |
| `test_safety.py` | 안전 계층 7종 (페일세이프·개입·창소실·워치독 등) | 11/11 PASS |
| `test_pipeline.py` | D-03 — 스캔 200ms 부하에도 키가 주기를 지키는가 | 밀림 0회 |
| `bench_detection.py` | 검출 속도·다중 검출 정확도 (합성 화면) | 15ms 이하, 5/5 |
| `bench_capture.py` | 실제 mss 캡처 포함 창 크기별 스캔 비용 | 창 모드 15ms 이하 |

## 주의

- 경로가 하드코딩되어 있다. 워크스페이스를 옮기면 각 파일 상단의
  `sys.path.insert` 와 데이터 경로를 고칠 것.
- `test_pipeline.py` 는 실제 입력을 주입하지 않는다 (FakeHand). 마우스가
  움직이지 않는 것이 정상.
- `test_pipeline.py` 의 키 간격이 설정값보다 9% 큰 것은 테스트가 지각 스레드에
  `time.sleep` 을 쓰기 때문이다 (스레드 경합). 실제 스캔은 OpenCV 연산이라
  조건이 다르다 — 단독 측정에서는 `wait(100ms)` → 100.1ms 였다.
