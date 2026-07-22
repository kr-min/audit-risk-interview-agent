# Audit Red Flag Interview Agent

재무제표를 입력하면 주요 재무 위험 신호를 식별하고,
기업 담당자 인터뷰 질문과 요청자료를 생성하는
규칙 기반 감사 지원 시스템입니다.

## 주요 기능

- 11개 핵심 재무계정 검증
- 결측값, 중복, 숫자 오류 검사
- 3개년 재무 추세 분석
- 10개 Red Flag 규칙 적용
- Red Flag 및 Monitoring Signal 분류
- 기업 담당자 인터뷰 질문 생성
- 요청 증빙자료 생성
- JSON 및 Markdown 보고서 저장

## 하이브 자동 파이프라인

`src/hybe_dart_pipeline.py`는 다음 과정을 수행합니다.

OpenDART 연결재무제표 수집
→ 사업보고서 검색
→ XBRL 다운로드
→ 영업권 자동 추출
→ 11개 계정 CSV 생성
→ Red Flag Agent 실행
→ 인터뷰 질문 및 보고서 생성

## 최종 검증 결과

- 분석 기업: 하이브
- 분석기간: 2023~2025
- 필수 계정: 11개
- 결측값: 0
- Red Flag: 7
- Monitoring Signal: 3
- 종료 코드: 0

## 실행 방법

1. 패키지 설치

    pip install -r requirements.txt

2. OpenDART API Key 설정

    export DART_API_KEY="YOUR_API_KEY"

3. 파이프라인 실행

    python src/hybe_dart_pipeline.py --corp-code 01204056 --company 하이브 --years 2023 2024 2025 --project-root .

## 현재 구현 범위

재무제표 CSV 입력 기반 Red Flag 및 인터뷰 질문 생성 Agent는 범용 구조입니다.

OpenDART와 XBRL 데이터 자동 수집은 하이브를 대상으로
End-to-End 검증했습니다.

모든 기업의 XBRL 구조를 자동 처리하는 범용 수집기는 아직 아닙니다.

## Disclaimer

식별된 Red Flag는 오류나 부정의 존재를 의미하는 것이 아니라,
기업 및 환경에 대한 이해와 중요왜곡표시위험 평가를 위해
추가적인 질문과 검토가 필요한 영역을 의미한다.

## 범용성 검증

Agent 본체는 하이브 외 가상기업 샘플테크 데이터로도 검증했습니다.

- 정상 입력 종료 코드: 0
- Red Flag: 4
- Monitoring Signal: 6
- JSON 및 Markdown 보고서 생성: PASS
- 필수 계정 누락 차단: PASS
- 중복 계정 차단: PASS
- 숫자 오류 차단: PASS

테스트 파일:

- tests/test_generic_normal_input.py
- tests/test_invalid_inputs.py
- docs/generic_agent_validation.md

테스트 실행:

```bash
python tests/test_generic_normal_input.py
python tests/test_invalid_inputs.py
```
