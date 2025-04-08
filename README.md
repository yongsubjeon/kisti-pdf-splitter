# KISTI PDF 분할 및 섹션 추출 도구

이 프로젝트는 PDF 파일을 목차에 따라 분할하고 특정 섹션을 자동으로 추출하는 웹 기반 애플리케이션입니다. 특히 리서치 보고서에서 Market Definition, South Korea, Executive Summary, Five Force Analysis, Market Overview, Market Share 등의 섹션을 자동으로 추출하는 기능을 제공합니다.

## 주요 기능

### 1. PDF 자동 분할
- 목차 페이지를 자동으로 인식하여 대목차 및 소목차 단위로 PDF 파일 분할
- 목차가 없는 경우 균등 분할 기능 제공

### 2. 특정 섹션 자동 추출
- **South Korea**: 'South Korea' 키워드가 포함된 페이지 자동 추출
- **Market Definition**: 'Market Definition' 키워드가 포함된 페이지 자동 추출
- **Executive Summary**: 'Executive Summary' 키워드가 포함된 페이지 자동 추출
- **Five Force Analysis**: 'Five Force', 'Porter', 'Competitive Rivalry' 등 관련 키워드 포함 페이지 자동 추출
- **Market Overview**: 'Market Overview' 키워드가 포함된 페이지 자동 추출
- **Market Share**: 'Market Share' 키워드가 포함된 페이지 자동 추출

### 3. 파일 관리 기능
- 분할된 PDF 파일 목록 제공
- 선택한 파일 병합 기능
- 추출 데이터 데이터베이스 저장 및 조회 기능

## 설치 방법

### 필수 요구사항
- Python 3.6 이상
- Flask
- Flask-SQLAlchemy
- PyPDF2
- (선택) OCR 기능 활용시: pytesseract, OpenCV, numpy, Pillow

### 설치 과정

1. 저장소 클론
   ```
   git clone https://github.com/yongsubjeon/kisti-cut.git
   cd kisti-cut
   ```

2. 필요한 패키지 설치
   ```
   pip install flask flask-sqlalchemy PyPDF2
   ```

3. (선택) OCR 기능을 사용하려면 추가 패키지 설치
   ```
   pip install pytesseract opencv-python numpy pillow
   ```
   
   - Windows 환경에서는 Tesseract OCR을 별도로 설치해야 합니다:
     - [Tesseract OCR 다운로드](https://github.com/UB-Mannheim/tesseract/wiki)
     - 설치 후 코드 내 경로 확인: `pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'`

## 사용 방법

1. 애플리케이션 실행
   ```
   python run.py
   ```

2. 웹 브라우저에서 접속
   ```
   http://127.0.0.1:5000/
   ```

3. 주요 기능 사용
   - 메인 페이지에서 PDF 파일 업로드
   - 분할된 파일 목록 페이지에서 파일 관리
   - 특정 섹션 직접 추출 기능 사용
   - 데이터베이스에 저장된 추출 데이터 조회

## 폴더 구조

애플리케이션 실행 시 자동으로 생성되는 폴더들:

- `uploads/`: 업로드된 원본 PDF 파일이 저장되는 폴더
- `output_sections/`: 분할된 PDF 파일이 저장되는 폴더
- `merged/`: 병합된 PDF 파일이 저장되는 폴더
- `figures/`: Executive Summary 관련 이미지가 저장되는 폴더
- `market_dynamics/`: Five Force Analysis 관련 파일이 저장되는 폴더
- `south_korea/`: South Korea 관련 페이지가 저장되는 폴더
- `market_definition/`: Market Definition 관련 페이지가 저장되는 폴더
- `market_overview/`: Market Overview 관련 페이지가 저장되는 폴더
- `market_share/`: Market Share 관련 페이지가 저장되는 폴더

## 시스템 상세 설명

### PDF 분할 알고리즘

1. 목차 페이지를 자동으로 인식 (TABLE OF CONTENTS 텍스트 검색)
2. 목차 텍스트 추출 및 계층 구조 분석
   - 각 챕터 번호와 제목, 페이지 번호 분석
   - 대목차와 소목차 구분
3. PDF 페이지 번호와 목차 페이지 번호 간의 오프셋 계산
4. 각 목차 항목별로 해당 페이지 범위만 추출하여 별도 PDF 생성

### 특정 섹션 추출 알고리즘

1. 키워드 기반 페이지 검색
   - 일반 텍스트 검색
   - 줄바꿈이 있는 경우 처리 (예: "SOUTH\nKOREA")
   - 정규식을 활용한 패턴 매칭
2. 텍스트 전처리 및 컨텍스트 분석
   - 줄바꿈과 공백 처리
   - 키워드 주변 컨텍스트 확인
3. 추출된 페이지를 하나의 PDF로 통합
4. 추출 정보 저장 및 디버그 정보 기록

### 데이터베이스 관리

- SQLite 데이터베이스 활용
- 추출된 데이터의 메타정보 (PDF 이름, 섹션 유형, 페이지 번호 등) 저장
- 웹 인터페이스를 통한 조회 및 관리 기능

## 향후 개선 계획

- OCR 성능 향상을 위한 추가 이미지 처리 알고리즘 구현
- 다양한 형식의 PDF 목차 인식 개선
- 사용자 인터페이스 개선
- 멀티 스레딩을 통한 대용량 PDF 처리 성능 최적화
- 클라우드 스토리지 연동 기능

## 라이센스

이 프로젝트는 MIT 라이센스 하에 배포됩니다. 