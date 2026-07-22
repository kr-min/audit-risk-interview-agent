# 실행 방법

## 1. 저장소 복제

GitHub 저장소를 내려받거나 ZIP 파일을 압축 해제합니다.

## 2. 라이브러리 설치

터미널에서 다음 명령을 실행합니다.

pip install -r requirements.txt

## 3. 샘플 분석 실행

프로젝트 최상위 폴더에서 다음 명령을 실행합니다.

python src/run_analysis.py

## 4. 실행 결과

다음 파일이 생성됩니다.

samples/sample_runtime_output.json

## 현재 실행 범위

독립 실행 스크립트는 전체 10개 규칙 중
RF-001의 핵심 계산 구조를 재현하는 최소 실행 예시입니다.

전체 분석 결과는 outputs 폴더와
Colab Notebook 실행 기록에서 확인할 수 있습니다.
