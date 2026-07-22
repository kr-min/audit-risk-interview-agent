# Audit Red Flag Interview Agent

재무제표의 3개년 변동을 규칙 기반으로 분석해 감사 착수 전 우선 검토 영역, 경영진 인터뷰 질문, 요청자료 및 후속 감사절차를 구조화하는 감사 사전분석 에이전트입니다.

## 프로젝트 목적

감사 초기 단계에서 기업과 환경을 이해하고 중요왜곡표시위험이 존재할 수 있는 영역을 식별하는 과정을 지원합니다.

주요 산출물은 다음과 같습니다.

- Red Flag와 Monitoring Signal
- Top 3 우선 검토 영역
- 실제 관측 수치와 감사상 의미
- 관련 재무제표 주장
- 경영진 인터뷰 질문
- 요청자료 및 증빙
- 가능한 정상적 사업 원인
- 잠재 회계·감사 위험
- 후속 감사절차

> 식별된 Red Flag는 오류나 부정의 존재를 의미하는 것이 아니라, 기업 및 환경에 대한 이해와 중요왜곡표시위험 평가를 위해 추가적인 질문과 검토가 필요한 영역을 의미한다.

## 주요 활용 시나리오

### 1. 신규 감사 또는 기업 최초 분석

최근 3개년 확정 연간 재무정보를 분석합니다.

- 전전기 확정 재무정보
- 전기 확정 재무정보
- 당기 확정 재무정보

회사의 재무적 특성, 계정 간 관계, 수익성, 운전자본과 자산 효율성 추세를 파악하고 감사위험 후보를 식별합니다.

### 2. 계속 감사 또는 당기 연말감사

전전기와 전기는 DART 공개자료를 활용하고, 당기는 회사가 제출한 미감사 재무자료를 결합합니다.

예를 들어 2026년 감사는 다음 자료를 결합합니다.

- 2024년 확정 재무정보
- 2025년 확정 재무정보
- 2026년 미감사 재무정보

결합된 3개년 자료를 기준으로 당기 변동에 대한 질문, 요청자료와 후속 감사절차를 도출합니다.

## 웹 애플리케이션

웹 앱은 네 가지 분석 모드를 제공합니다.

1. 실무 감사 분석
   - 전전기와 전기 DART 자료
   - 당기 미감사 CSV 업로드
   - 3개년 결합 분석

2. 공개자료 DART 분석
   - 공개된 최근 3개년 재무정보 수집
   - 규칙 기반 자동분석

3. 표준 CSV 직접 분석
   - 사용자가 준비한 3개년 CSV 분석

4. 검증 기업 예시
   - 삼성전자
   - NAVER
   - 카카오
   - 하이브

## 입력 데이터 구조

현재 버전은 다음 11개 표준 계정을 사용합니다.

| Account |
|---|
| Revenue |
| Operating_Profit |
| Net_Income |
| Total_Assets |
| Operating_Cash_Flow |
| Intangible_Assets |
| Goodwill |
| Investment_in_Associates |
| Accounts_Receivable |
| Inventory |
| Trade_Payables |

3개년 직접 분석 CSV는 Account 열과 세 개의 연도 열로 구성합니다.

당기 미감사 CSV는 Account 열과 당기 연도 열 하나로 구성합니다.

## 분석 규칙

현재 버전은 10개의 결정론적 규칙을 사용합니다.

- 외형 성장과 수익성 변화
- 이익과 영업현금흐름의 관계
- 영업권 비중과 손상검사
- 매출 대비 매출채권 증가
- 매출 대비 재고자산 증가
- 영업이익과 당기순손익의 관계
- 관계기업투자 변동
- 3개년 영업이익률 추세
- 매출 성장과 순손익 추세
- 자산회전율과 ROA 관계

규칙이 발동되지 않은 경우에는 실제 수치와 반대되는 위험 문구를 출력하지 않고 관측 결과에 맞는 Monitoring Signal로 표현합니다.

## Top 3 선정 방식

Top 3는 다음 순서로 선정합니다.

1. 실제 발동된 Red Flag
2. 우선순위 점수가 높은 Monitoring Signal
3. 서로 다른 위험군을 우선 선택

Red Flag가 0개인 경우에도 감사인이 우선 확인할 Monitoring Signal 세 개를 제공합니다.

## 설치

터미널에서 다음 명령을 실행합니다.

    pip install -r requirements.txt

## 웹 앱 실행

    python app.py

## 표준 CSV 직접 분석

    python src/generic_runtime_agent.py INPUT.csv --company "Example Company" --output-dir outputs

## DART API 키

실시간 DART 수집 기능을 사용하려면 환경변수 DART_API_KEY를 설정해야 합니다.

API 키는 코드나 GitHub 저장소에 직접 입력하지 않습니다.

## 출력 파일

- runtime_audit_analysis.json
- runtime_audit_report.md
- 분석 또는 결합 입력 CSV

JSON에는 다음 정보가 포함됩니다.

- priority_score
- observed_fact
- interpretation
- possible_normal_causes
- possible_audit_risks
- assertions
- interview_questions
- evidence_requests
- follow_up_procedures

## 검증 결과

공개 재무정보를 이용해 삼성전자, NAVER, 카카오, 하이브에 대해 입력 CSV, JSON 분석 결과와 보고서 생성을 검증했습니다.

카카오의 실시간 XBRL 호출은 DART 원본 파일 상태에 따라 제한될 수 있어 검증된 스냅샷을 제공합니다.

## 프로젝트 구조

    app.py
    requirements.txt
    README.md
    LICENSE
    src/
      generic_runtime_agent.py
      hybrid_audit_mode.py
      hybe_dart_pipeline.py
    samples/
      current_year_unaudited_template.csv
      naver_2026_unaudited_FICTIONAL.csv
    verified_demo/
      samsung_electronics/
      naver/
      kakao/
      hybe/
    tests/
      test_verified_outputs.py

## 현재 범위

- 연간 재무자료
- 3개년 비교
- 표준 11개 계정
- 규칙 기반 분석
- 감사 인터뷰와 요청자료 설계

## 현재 한계

- 임의 형식 Excel 또는 PDF 자동인식 미지원
- 재무제표 주석 전체 분석 미지원
- 분기와 반기의 전년 동기 분석 미지원
- 전표 및 거래 단위 테스트 미지원
- 감사의견 또는 부정 여부 판단 미지원
- 감사인의 전문적 판단을 대체하지 않음

## 기술적 특징

- 생성형 AI가 아닌 결정론적 규칙 기반 구조
- 동일 입력에 대해 동일 결과 생성
- 규칙 발동 여부와 근거 수치 추적 가능
- JSON 결과를 통한 재현성과 검증 가능
- 감사 실무의 질문과 자료 요청 흐름 중심 설계

## 향후 개선 방향

- 기업별 계정명 자동 매핑 확대
- 재무제표 주석 및 사업보고서 텍스트 분석
- 분기와 반기 비교 모드
- 산업별 규칙 라이브러리
- 중요성 금액과 위험평가 연계
- 감사조서 템플릿 출력
