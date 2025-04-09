FROM python:3.9-slim

WORKDIR /app

# 필요한 패키지 설치
RUN apt-get update && apt-get install -y \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-kor \
    && rm -rf /var/lib/apt/lists/*

# 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY . .

# 필요한 디렉토리 생성
RUN mkdir -p uploads output_sections merged figures market_dynamics south_korea market_definition market_overview market_share

# 포트 설정
ENV PORT 8080

# 환경 변수 설정
ENV FLASK_APP=run.py

# 시작 명령어
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 run:app 