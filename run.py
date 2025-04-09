import os
import re
import io
import glob
from flask import Flask, request, render_template, send_from_directory, redirect, url_for, jsonify
from PyPDF2 import PdfReader, PdfWriter
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# OCR 관련 라이브러리는 선택적으로 임포트
OCR_AVAILABLE = False
try:
    import pytesseract
    import cv2
    import numpy as np
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    try:
        from PIL import Image  # 기본 이미지 처리만 가능하도록
    except ImportError:
        pass  # PIL도 없는 경우

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'output_sections'
MERGED_FOLDER = 'merged'
FIGURE_FOLDER = 'figures'
MARKET_DYNAMICS_FOLDER = 'market_dynamics'
SOUTH_KOREA_FOLDER = 'south_korea'
MARKET_DEFINITION_FOLDER = 'market_definition'
MARKET_OVERVIEW_FOLDER = 'market_overview'
MARKET_SHARE_FOLDER = 'market_share'

# 데이터베이스 설정
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///extracted_data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['MERGED_FOLDER'] = MERGED_FOLDER
app.config['FIGURE_FOLDER'] = FIGURE_FOLDER
app.config['MARKET_DYNAMICS_FOLDER'] = MARKET_DYNAMICS_FOLDER
app.config['SOUTH_KOREA_FOLDER'] = SOUTH_KOREA_FOLDER
app.config['MARKET_DEFINITION_FOLDER'] = MARKET_DEFINITION_FOLDER
app.config['MARKET_OVERVIEW_FOLDER'] = MARKET_OVERVIEW_FOLDER
app.config['MARKET_SHARE_FOLDER'] = MARKET_SHARE_FOLDER

# Firebase 설정 - 환경 변수에서 가져오기
app.config['FIREBASE_API_KEY'] = os.environ.get('FIREBASE_API_KEY', '')
app.config['FIREBASE_AUTH_DOMAIN'] = os.environ.get('FIREBASE_AUTH_DOMAIN', '')
app.config['FIREBASE_PROJECT_ID'] = os.environ.get('FIREBASE_PROJECT_ID', '')
app.config['FIREBASE_STORAGE_BUCKET'] = os.environ.get('FIREBASE_STORAGE_BUCKET', '')
app.config['FIREBASE_MESSAGING_SENDER_ID'] = os.environ.get('FIREBASE_MESSAGING_SENDER_ID', '')
app.config['FIREBASE_APP_ID'] = os.environ.get('FIREBASE_APP_ID', '')
app.config['FIREBASE_MEASUREMENT_ID'] = os.environ.get('FIREBASE_MEASUREMENT_ID', '')

# 모든 필요한 폴더 생성
for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, MERGED_FOLDER, FIGURE_FOLDER, 
               MARKET_DYNAMICS_FOLDER, SOUTH_KOREA_FOLDER, MARKET_DEFINITION_FOLDER,
               MARKET_OVERVIEW_FOLDER, MARKET_SHARE_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# 테서랙트 경로 설정 (Windows 환경)
if OCR_AVAILABLE:
    try:
        pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    except:
        OCR_AVAILABLE = False

db = SQLAlchemy(app)

# 추출 데이터 모델 정의
class ExtractedData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pdf_name = db.Column(db.String(255), nullable=False)
    section_type = db.Column(db.String(50), nullable=False)  # 'market_overview', 'five_force' 등
    pages = db.Column(db.String(255), nullable=False)  # 쉼표로 구분된 페이지 목록
    extracted_at = db.Column(db.DateTime, default=datetime.utcnow)
    content_hash = db.Column(db.String(64), nullable=True)  # 파일 내용 해시 (선택사항)

def safe_filename(name):
    """파일명에 사용할 수 없는 문자 대체 및 길이 제한"""
    # 사용할 수 없는 문자 대체
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    # 연속된 공백과 특수문자 정리
    name = re.sub(r'\s+', ' ', name)
    name = re.sub(r'[.]+', '.', name)
    name = re.sub(r'[_]+', '_', name)
    # 문자열 길이 제한 (최대 100자)
    if len(name) > 100:
        name = name[:97] + '...'
    return name

def find_toc_page(reader):
    """목차 페이지 찾기"""
    for i in range(min(20, len(reader.pages))):
        text = reader.pages[i].extract_text()
        if text and "TABLE OF CONTENTS" in text.upper():
            return i
    return None

def extract_sections(text):
    """목차에서 대목차 및 소목차 추출 (첫 번째 레벨만)"""
    sections = []
    hierarchy = []
    
    # 목차 번호 패턴을 저장할 집합
    chapter_patterns = set()
    
    # 첫 번째 패스: 모든 목차 번호 패턴 수집
    for line in text.splitlines():
        line = line.strip()
        if not line or "USD MILLION" in line or "2020" in line:
            continue

        # LIST OF TABLE이 발견되면 목차 추출 중단
        if "LIST OF TABLE" in line.upper():
                    break
        
        # 숫자 또는 숫자.숫자 형식 찾기
        patterns = re.findall(r'^(\d+(?:\.\d+)*)\s+(.+?)\s+(\d+)$', line)
        if patterns:
            num, title, page = patterns[0]
            # 목차 번호 패턴 저장
            if len(num.split('.')) <= 2:  # 최대 2레벨(예: 1.1)까지만 수집
                chapter_patterns.add(num)
    
    # 패턴을 정렬하여 확인
    patterns_sorted = sorted(chapter_patterns, key=lambda x: [int(n) for n in x.split('.')])
    print(f"인식된 목차 패턴: {patterns_sorted}")
    
    # 두 번째 패스: 수집된 패턴만 처리
    for line in text.splitlines():
        line = line.strip()
        if not line or "USD MILLION" in line or "2020" in line:
            continue
            
        # LIST OF TABLE이 발견되면 목차 추출 중단
        if "LIST OF TABLE" in line.upper():
            break
        
        # 개선된 목차 추출 정규식 - 정확한 시작과 끝 지정
        match = re.match(r'^(\d+(?:\.\d+)*)\s+(.+?)\s+(\d+)$', line)
        if match:
            num, title, page = match.groups()
            page = int(page)
            
            # 인식된 목차 패턴에 있는 경우만 처리
            if num in chapter_patterns:
                # Brazil과 같은 국가명이 포함된 깊은 레벨 목차는 제외
                if "BRAZIL" in title.upper() and num.count('.') > 1:
                    continue
                
                # 계층 구조 저장
                if '.' in num:  # 소목차 (예: 1.1)
                    hierarchy.append((num, title, page))
                else:  # 대목차 (예: 1)
                    if hierarchy:
                        sections.append(hierarchy)
                        hierarchy = []
                    hierarchy.append((num, title, page))
    
    if hierarchy:
        sections.append(hierarchy)
    
    return sections

def split_pdf_evenly(reader, output_folder, parts=5):
    """PDF 파일을 균등하게 분할"""
    total_pages = len(reader.pages)
    pages_per_part = total_pages // parts
    extra_pages = total_pages % parts  # 나머지 페이지 처리
    result_files = []

    start_page = 0
    for i in range(parts):
        writer = PdfWriter()

        # 각 파트의 페이지 범위 설정 (나머지 페이지를 앞에서부터 하나씩 추가)
        end_page = start_page + pages_per_part + (1 if i < extra_pages else 0)

        for page_num in range(start_page, min(end_page, total_pages)):
            writer.add_page(reader.pages[page_num])

        filename = f"Part_{i+1}.pdf"
        output_path = os.path.join(output_folder, filename)
        with open(output_path, 'wb') as output_file:
            writer.write(output_file)
        result_files.append(filename)

        start_page = end_page  # 다음 파트의 시작 페이지 설정

    return result_files

def split_pdf(input_pdf, output_folder):
    """PDF 파일을 목차에 따라 대목차 및 소목차로 분할"""
    reader = PdfReader(input_pdf)
    toc_page = find_toc_page(reader)
    total_pages = len(reader.pages)
    
    # 목차 페이지가 없으면 균등 분할
    if toc_page is None:
        return split_pdf_evenly(reader, output_folder), None

    # 목차 텍스트 추출
    full_toc_text = ""
    for i in range(toc_page, min(toc_page + 15, len(reader.pages))):
        text = reader.pages[i].extract_text()
        full_toc_text += text

    toc = extract_sections(full_toc_text)
    if not toc:
        return split_pdf_evenly(reader, output_folder), None

    # 목차의 페이지 번호와 실제 PDF 페이지 오프셋 계산
    # 첫 번째 목차 항목의 페이지 번호를 기준으로 오프셋 계산
    if toc and toc[0] and toc[0][0]:
        first_toc_page = toc[0][0][2]  # 첫 번째 목차의 페이지 번호
        # 첫 번째 목차 페이지가 실제 PDF 페이지보다 크다면 오프셋이 있는 것
        page_offset = 0
        if first_toc_page > total_pages:
            # 예상 오프셋 계산 (페이지 번호가 시작되는 지점)
            page_offset = first_toc_page - min(first_toc_page, total_pages)
            print(f"페이지 오프셋 감지: {page_offset}")

    result_files = []
    
    # 목차를 별도 파일로 저장
    toc_writer = PdfWriter()
    for page_num in range(toc_page, min(toc_page + 15, len(reader.pages))):
        toc_writer.add_page(reader.pages[page_num])
    
    toc_filename = "목차.pdf"
    toc_output_path = os.path.join(output_folder, toc_filename)
    with open(toc_output_path, 'wb') as toc_output_file:
        toc_writer.write(toc_output_file)
    result_files.append(toc_filename)
    
    for section in toc:
        # PDF 내 실제 페이지 번호 계산 (오프셋 적용)
        start_page = max(1, section[0][2] - page_offset)
        
        # PDF 총 페이지 수 제한 적용
        if start_page > total_pages:
            print(f"경고: 시작 페이지 {start_page}가 PDF 총 페이지 수 {total_pages}를 초과합니다. 건너뜁니다.")
            continue
            
        # 다음 섹션이 있으면 그 페이지까지, 없으면 5페이지 또는 PDF 끝까지
        next_section_page = None
        if len(section) > 1:
            end_page = section[-1][2] - page_offset
        else:
            end_page = min(start_page + 5, total_pages)
            
        # 페이지 번호가 PDF 페이지 수를 초과하지 않도록 제한
        end_page = min(end_page, total_pages)
        
        # 페이지 범위 검증 및 수정
        if start_page >= end_page:
            # 페이지 범위가 역순이거나 같은 경우 최소 한 페이지 포함
            end_page = min(start_page + 1, total_pages)
        
        # 대목차 파일 생성
        writer = PdfWriter()
        for page_num in range(start_page - 1, end_page):
            if 0 <= page_num < total_pages:  # 유효한 페이지 범위 확인
                writer.add_page(reader.pages[page_num])

        # 챕터 번호와 제목, 페이지 범위를 포함한 파일명 생성
        original_start = section[0][2]  # 원본 목차의 페이지 번호
        original_end = end_page + page_offset - 1  # 원본 목차의 페이지 번호로 변환
        filename = f"{section[0][0]} {section[0][1]} (p{original_start}-p{original_end}).pdf"
        output_path = os.path.join(output_folder, safe_filename(filename))
        
        # 최소한 하나의 페이지가 있을 때만 파일 생성
        if writer.pages:
            with open(output_path, 'wb') as output_file:
                writer.write(output_file)
            result_files.append(filename)

        # 소목차별 개별 파일 생성
        for i in range(1, len(section)):
            sub_writer = PdfWriter()
            
            # PDF 내 실제 페이지 번호 계산 (오프셋 적용)
            sub_start = max(1, section[i][2] - page_offset)
            
            # 유효한 페이지 범위 확인
            if sub_start > total_pages:
                continue
                
            # 다음 소목차가 있으면 그 페이지 전까지, 없으면 대목차의 끝까지
            if i + 1 < len(section):
                sub_end = max(1, section[i+1][2] - page_offset)
            else:
                sub_end = end_page
            
            # 페이지 번호가 PDF 페이지 수를 초과하지 않도록 제한
            sub_end = min(sub_end, total_pages)
            
            # 페이지 범위 검증 및 수정
            if sub_start >= sub_end:
                # 페이지 범위가 역순이거나 같은 경우 최소 한 페이지 포함
                sub_end = min(sub_start + 1, total_pages)
                
            for page_num in range(sub_start - 1, sub_end):
                if 0 <= page_num < total_pages:  # 유효한 페이지 범위 확인
                    sub_writer.add_page(reader.pages[page_num])

            # 소목차의 번호와 제목, 페이지 범위를 포함한 파일명 생성
            original_sub_start = section[i][2]  # 원본 목차의 페이지 번호
            original_sub_end = sub_end + page_offset - 1  # 원본 목차의 페이지 번호로 변환
            sub_filename = f"{section[i][0]} {section[i][1]} (p{original_sub_start}-p{original_sub_end}).pdf"
            sub_output_path = os.path.join(output_folder, safe_filename(sub_filename))
            
            # 최소한 하나의 페이지가 있을 때만 파일 생성
            if sub_writer.pages:
                with open(sub_output_path, 'wb') as sub_output_file:
                    sub_writer.write(sub_output_file)
                result_files.append(sub_filename)

    return result_files, None

@app.route('/')
def upload_file():
    # Firebase 설정 변수를 템플릿에 전달
    firebase_config = {
        'firebase_api_key': app.config['FIREBASE_API_KEY'],
        'firebase_auth_domain': app.config['FIREBASE_AUTH_DOMAIN'],
        'firebase_project_id': app.config['FIREBASE_PROJECT_ID'],
        'firebase_storage_bucket': app.config['FIREBASE_STORAGE_BUCKET'],
        'firebase_messaging_sender_id': app.config['FIREBASE_MESSAGING_SENDER_ID'],
        'firebase_app_id': app.config['FIREBASE_APP_ID'],
        'firebase_measurement_id': app.config['FIREBASE_MEASUREMENT_ID']
    }
    return render_template('index.html', **firebase_config)

@app.route('/login')
def login():
    # Firebase 설정 변수를 템플릿에 전달
    firebase_config = {
        'firebase_api_key': app.config['FIREBASE_API_KEY'],
        'firebase_auth_domain': app.config['FIREBASE_AUTH_DOMAIN'],
        'firebase_project_id': app.config['FIREBASE_PROJECT_ID'],
        'firebase_storage_bucket': app.config['FIREBASE_STORAGE_BUCKET'],
        'firebase_messaging_sender_id': app.config['FIREBASE_MESSAGING_SENDER_ID'],
        'firebase_app_id': app.config['FIREBASE_APP_ID'],
        'firebase_measurement_id': app.config['FIREBASE_MEASUREMENT_ID']
    }
    return render_template('login.html', **firebase_config)

@app.route('/register')
def register():
    # Firebase 설정 변수를 템플릿에 전달
    firebase_config = {
        'firebase_api_key': app.config['FIREBASE_API_KEY'],
        'firebase_auth_domain': app.config['FIREBASE_AUTH_DOMAIN'],
        'firebase_project_id': app.config['FIREBASE_PROJECT_ID'],
        'firebase_storage_bucket': app.config['FIREBASE_STORAGE_BUCKET'],
        'firebase_messaging_sender_id': app.config['FIREBASE_MESSAGING_SENDER_ID'],
        'firebase_app_id': app.config['FIREBASE_APP_ID'],
        'firebase_measurement_id': app.config['FIREBASE_MEASUREMENT_ID']
    }
    return render_template('register.html', **firebase_config)

@app.route('/upload', methods=['POST'])
def upload():
    if request.method == 'POST':
        file = request.files['file']
        if file and file.filename.endswith('.pdf'):
            input_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(input_path)
            result_files, error = split_pdf(input_path, app.config['OUTPUT_FOLDER'])
            if error:
                return f"오류 발생: {error}"
            return redirect(url_for('list_files'))
        else:
            return "유효한 PDF 파일을 업로드해주세요."

@app.route('/files')
def list_files():
    # 분할된 파일들
    files = os.listdir(app.config['OUTPUT_FOLDER'])
    
    # 직접 추출 파일들도 포함
    special_folders = {
        'South Korea': app.config['SOUTH_KOREA_FOLDER'],
        'Market Definition': app.config['MARKET_DEFINITION_FOLDER'],
        'Market Overview': app.config['MARKET_OVERVIEW_FOLDER'],
        'Executive Summary': app.config['FIGURE_FOLDER'],
        'Five Force': app.config['MARKET_DYNAMICS_FOLDER'],
        'Market Share': app.config['MARKET_SHARE_FOLDER']
    }
    
    special_files = []
    for category, folder in special_folders.items():
        if os.path.exists(folder):
            folder_files = os.listdir(folder)
            # PDF 파일만 추가 (디버그 파일, 텍스트 파일 제외)
            for file in folder_files:
                if file.endswith('.pdf'):
                    special_files.append((category, file, folder))
    
    # '목차.pdf' 파일을 맨 앞으로 이동
    if '목차.pdf' in files:
        files.remove('목차.pdf')
        files = ['목차.pdf'] + files
    
    # 파일명에서 목차 번호를 추출하여 정렬
    pattern = re.compile(r'^(\d+(?:\.\d+)?)\s+(.+?)\s+\(p\d+-p\d+\)\.pdf$')
    
    # 파일을 목차 번호로 분류
    structured_files = []
    for file in files:
        if file == '목차.pdf':
            structured_files.append(('0', file, 0, None))  # 목차.pdf를 맨 앞에 두기 위해 '0' 부여
            continue
        
        match = pattern.match(file)
        if match:
            number, title = match.groups()
            # 목차 레벨 결정 (대목차: 0, 소목차: 1, 기타: 2)
            level = 0 if '.' not in number else 1
            structured_files.append((number, file, level, None))
        else:
            structured_files.append(('999', file, 2, None))  # 기타 파일은 맨 뒤로
    
    # 특수 추출 파일 추가
    for category, file, folder in special_files:
        # 특수 추출 파일은 맨 마지막에 표시하기 위해 '1000' 번대 부여
        number = '1000'
        structured_files.append((number, file, 3, {'category': category, 'folder': folder}))
    
    # 목차 번호 기준으로 정렬
    def sort_key(item):
        num, _, level, _ = item
        if num == '0':  # 목차.pdf
            return (0, 0)
        elif num.startswith('1000'):  # 특수 추출 파일
            return (1000, 0)
        elif num == '999':  # 기타 파일
            return (999, 0)
        
        # 숫자.숫자 형식의 경우 각 부분을 정수로 변환하여 정렬
        parts = num.split('.')
        if len(parts) == 1:
            return (int(parts[0]), 0)
        else:
            return (int(parts[0]), int(parts[1]))
    
    structured_files.sort(key=sort_key)
    
    # HTML 생성
    html = """
    <h1>분할된 PDF 파일 및 추출된 파일 목록</h1>
    <form action="/merge" method="post">
    <button type="submit" style="margin-bottom:20px; padding:10px; background-color:#4CAF50; color:white; border:none; border-radius:5px; cursor:pointer;">
        선택한 파일 병합하기
    </button>
    <ul style='list-style-type:none; padding-left:20px;'>
    """
    
    # 분할 파일 섹션
    html += "<h2>분할된 파일</h2>"
    for num, file, level, special_info in structured_files:
        if special_info:  # 특수 추출 파일은 다음 섹션에서 처리
            continue
            
        # 들여쓰기 레벨에 따라 스타일 적용
        indent = "&nbsp;&nbsp;&nbsp;&nbsp;" * level
        
        # 목차 레벨에 따라 다른 스타일 적용
        if level == 0:  # 대목차
            if num == '0':  # 목차.pdf
                html += f"""<li style='margin-bottom:10px;'>
                    <input type="checkbox" name="selected_files" value="{file}" id="{file}" data-folder="output">
                    <a href='/download/{file}'><strong>{file}</strong></a>
                </li>"""
            else:
                html += f"""<li style='margin-top:15px; margin-bottom:5px;'>
                    <input type="checkbox" name="selected_files" value="{file}" id="{file}" data-folder="output">
                    <a href='/download/{file}'><strong>{file}</strong></a>
                </li>"""
        elif level == 1:  # 소목차
            html += f"""<li style='margin-left:30px;'>
                {indent}<input type="checkbox" name="selected_files" value="{file}" id="{file}" data-folder="output">
                <a href='/download/{file}'>{file}</a>
            </li>"""
        else:  # 기타 파일
            html += f"""<li>
                <input type="checkbox" name="selected_files" value="{file}" id="{file}" data-folder="output">
                <a href='/download/{file}'>{file}</a>
            </li>"""
    
    # 특수 추출 파일 섹션
    if any(special_info for _, _, _, special_info in structured_files):
        html += "<h2>직접 추출된 파일</h2>"
        
        # 카테고리별로 그룹화
        categories = {}
        for num, file, level, special_info in structured_files:
            if special_info:
                category = special_info['category']
                if category not in categories:
                    categories[category] = []
                categories[category].append((file, special_info['folder']))
        
        # 카테고리별로 파일 표시
        for category, files_info in categories.items():
            html += f"<h3>{category}</h3>"
            for file, folder in files_info:
                folder_name = os.path.basename(folder)
                html += f"""<li style='margin-left:10px;'>
                    <input type="checkbox" name="selected_special_files" value="{folder_name}:{file}" id="{folder_name}:{file}">
                    <a href='/download_special/{folder_name}/{file}'>{file}</a>
                </li>"""
    
    html += """
    </ul>
    </form>
    <script>
    // 대목차를 체크하면 그 아래 소목차들도 함께 체크/해제되는 기능
    document.addEventListener('DOMContentLoaded', function() {
        const checkboxes = document.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(function(checkbox) {
            checkbox.addEventListener('change', function() {
                if(this.id.indexOf('.') === -1 && this.dataset.folder === 'output') { // 대목차인 경우
                    const chapter = this.id.split(' ')[0]; // 챕터 번호 추출
                    const subchapters = document.querySelectorAll(`input[id^="${chapter}."]`);
                    subchapters.forEach(function(subchapter) {
                        subchapter.checked = checkbox.checked;
                    });
                }
            });
        });
    });
    </script>
    """
    return html

def extract_page_numbers(filename):
    """파일명에서 페이지 번호 범위 추출"""
    match = re.search(r'\(p(\d+)-p(\d+)\)', filename)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 0, 0

def merge_pdf_files(files, output_path):
    """선택된 PDF 파일들을 페이지 순서에 따라 병합"""
    # 페이지 범위 정보 추출 및 정렬
    files_with_pages = []
    for file in files:
        start_page, end_page = extract_page_numbers(file)
        files_with_pages.append((file, start_page, end_page))
    
    # 시작 페이지 기준으로 정렬
    files_with_pages.sort(key=lambda x: x[1])
    
    # 파일 병합
    merger = PdfWriter()
    for file, _, _ in files_with_pages:
        filepath = os.path.join(app.config['OUTPUT_FOLDER'], file)
        reader = PdfReader(filepath)
        for page in reader.pages:
            merger.add_page(page)
    
    # 병합된 파일 저장
    with open(output_path, 'wb') as output_file:
        merger.write(output_file)
    
    return os.path.basename(output_path)

@app.route('/merge', methods=['POST'])
def merge_files():
    selected_files = request.form.getlist('selected_files')
    selected_special_files = request.form.getlist('selected_special_files')
    
    if not selected_files and not selected_special_files:
        return "선택된 파일이 없습니다. <a href='/files'>돌아가기</a>"
    
    # 병합된 파일 저장 경로
    output_filename = f"merged_{len(selected_files) + len(selected_special_files)}files.pdf"
    output_path = os.path.join(app.config['MERGED_FOLDER'], output_filename)
    
    # 파일 병합
    merger = PdfWriter()
    
    # 일반 분할 파일 추가
    for file in selected_files:
        filepath = os.path.join(app.config['OUTPUT_FOLDER'], file)
        try:
            reader = PdfReader(filepath)
            for page in reader.pages:
                merger.add_page(page)
        except Exception as e:
            print(f"분할 파일 처리 중 오류: {filepath}, 오류: {e}")
    
    # 특수 추출 파일 추가
    for file_info in selected_special_files:
        folder_name, filename = file_info.split(':', 1)
        folder_map = {
            'market_definition': app.config['MARKET_DEFINITION_FOLDER'],
            'figures': app.config['FIGURE_FOLDER'],
            'market_dynamics': app.config['MARKET_DYNAMICS_FOLDER'],
            'south_korea': app.config['SOUTH_KOREA_FOLDER'],
            'market_overview': app.config['MARKET_OVERVIEW_FOLDER']
        }
        
        if folder_name in folder_map:
            filepath = os.path.join(folder_map[folder_name], filename)
            try:
                reader = PdfReader(filepath)
                for page in reader.pages:
                    merger.add_page(page)
            except Exception as e:
                print(f"특수 파일 처리 중 오류: {filepath}, 오류: {e}")
    
    # 병합된 파일 저장
    with open(output_path, 'wb') as output_file:
        merger.write(output_file)
    
    return f"""
    <h1>PDF 파일 병합 완료</h1>
    <p>{len(selected_files) + len(selected_special_files)}개의 파일이 성공적으로 병합되었습니다.</p>
    <p><a href='/download_merged/{output_filename}'>병합된 파일 다운로드</a></p>
    <p><a href='/files'>파일 목록으로 돌아가기</a></p>
    """

@app.route('/download_merged/<filename>')
def download_merged_file(filename):
    return send_from_directory(app.config['MERGED_FOLDER'], filename)

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename)

def extract_market_definition(output_folder):
    """MARKET DEFINITION 섹션을 찾아 모아서 별도 PDF로 저장"""
    result_files = []
    market_definition_files = []
    
    # 모든 PDF 파일 경로 가져오기
    files = os.listdir(output_folder)
    
    # "MARKET DEFINITION" 문자열이 포함된 파일 찾기
    for file in files:
        if file.endswith('.pdf') and "MARKET DEFINITION" in file.upper():
            market_definition_files.append(os.path.join(output_folder, file))
    
    if not market_definition_files:
        return []
    
    # 통합 PDF 저장 경로
    output_filename = "MARKET_DEFINITION_Combined.pdf"
    output_path = os.path.join(app.config['MARKET_DEFINITION_FOLDER'], output_filename)
    
    # 파일 병합
    merger = PdfWriter()
    for file_path in market_definition_files:
        try:
            reader = PdfReader(file_path)
            for page in reader.pages:
                merger.add_page(page)
        except Exception as e:
            print(f"파일 처리 중 오류 발생: {file_path}, 오류: {e}")
    
    # 병합된 파일 저장
    with open(output_path, 'wb') as output_file:
        merger.write(output_file)
    
    return [output_filename]

def extract_south_korea_from_original(pdf_path):
    """원본 PDF 파일에서 South Korea 키워드가 포함된 페이지만 추출"""
    result_files = []
    south_korea_pages = []
    debug_info = []
    
    try:
        # 원본 PDF 파일 이름 추출 (확장자 제외)
        original_filename = os.path.basename(pdf_path)
        original_name_without_ext = os.path.splitext(original_filename)[0]
        
        # 원본 PDF 읽기
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        
        print(f"총 {total_pages}페이지 PDF 파일에서 'South Korea' 키워드 검색 중...")
        
        # 각 페이지 텍스트 검색
        for page_num, page in enumerate(reader.pages):
            try:
                text = page.extract_text().upper()
                
                # 줄바꿈 제거한 텍스트도 생성
                text_no_newlines = text.replace('\n', ' ')
                
                # 공백 정리
                text_clean = ' '.join(text.split())
                
                # 특정 페이지 주변(145-160)의 텍스트 상세 로깅
                if 145 <= page_num+1 <= 160:
                    sample_text = text[:300] + "..." if len(text) > 300 else text
                    print(f"페이지 {page_num+1} 텍스트 샘플: {sample_text}")
                    debug_info.append(f"페이지 {page_num+1} 텍스트 샘플: {sample_text}")
                    
                    # 줄바꿈 주변 텍스트 확인
                    for i in range(len(text) - 5):
                        if text[i:i+5].upper() == "SOUTH" and i+5 < len(text) and '\n' in text[i+5:i+12]:
                            next_word_start = text.find("KOREA", i+5, i+20)
                            if next_word_start > -1:
                                print(f"페이지 {page_num+1}에서 줄바꿈으로 분리된 'SOUTH\\nKOREA' 발견")
                                debug_info.append(f"페이지 {page_num+1}에서 줄바꿈으로 분리된 'SOUTH\\nKOREA' 발견")
                
                # 여러 형태로 검색
                found = False
                
                # 1. 일반 형태
                if "SOUTH KOREA" in text:
                    print(f"'SOUTH KOREA' 키워드 발견: 페이지 {page_num+1}")
                    found = True
                
                # 2. 줄바꿈이 제거된 텍스트에서 검색
                elif "SOUTH KOREA" in text_no_newlines:
                    print(f"줄바꿈 제거 후 'SOUTH KOREA' 키워드 발견: 페이지 {page_num+1}")
                    found = True
                
                # 3. 정규식을 사용한 "SOUTH" 다음에 공백이나 줄바꿈 후 "KOREA"가 오는 패턴 검색
                elif re.search(r'SOUTH\s*[\n\r]*\s*KOREA', text):
                    print(f"줄바꿈 패턴으로 'SOUTH\\nKOREA' 키워드 발견: 페이지 {page_num+1}")
                    found = True
                
                # 4. 기타 변형
                elif any(pattern in text for pattern in ["S KOREA", "S. KOREA", "SOUTH-KOREA", "S.KOREA"]):
                    print(f"'South Korea' 변형 키워드 발견: 페이지 {page_num+1}")
                    found = True
                
                # 5. 'KOREA' 주변 컨텍스트 확인 (SOUTH로 시작하는 단어가 근처에 있는지)
                elif "KOREA" in text:
                    korea_pos = text.find("KOREA")
                    context = text[max(0, korea_pos-50):min(len(text), korea_pos+50)]
                    if "SOUTH" in context:
                        print(f"'KOREA' 주변에 'SOUTH' 발견: 페이지 {page_num+1}")
                        found = True
                
                if found:
                    south_korea_pages.append((page_num, page))
                
            except Exception as e:
                print(f"페이지 {page_num+1} 처리 중 오류: {e}")
                debug_info.append(f"페이지 {page_num+1} 처리 중 오류: {e}")
        
        if not south_korea_pages:
            print("'South Korea' 키워드가 포함된 페이지를 찾을 수 없습니다.")
            
            # 디버그 정보 저장
            debug_filename = f"south_korea_debug_{original_name_without_ext}.txt"
            debug_path = os.path.join(app.config['SOUTH_KOREA_FOLDER'], debug_filename)
            with open(debug_path, 'w', encoding='utf-8') as f:
                f.write(f"원본 PDF 파일 '{original_filename}'에서 South Korea 키워드 검색 디버그 정보:\n\n")
                for info in debug_info:
                    f.write(f"{info}\n\n")
            
            return []
        
        print(f"총 {len(south_korea_pages)}개의 페이지에서 'South Korea' 키워드 발견")
        
        # 통합 PDF 저장 경로 (원본 파일명 포함)
        output_filename = f"SOUTH_KOREA_Pages_{original_name_without_ext}.pdf"
        output_path = os.path.join(app.config['SOUTH_KOREA_FOLDER'], output_filename)
        
        # 파일 병합 - 페이지 단위로
        merger = PdfWriter()
        for page_num, page in south_korea_pages:
            try:
                # 페이지 추가
                merger.add_page(page)
            except Exception as e:
                print(f"페이지 {page_num+1} 추가 중 오류: {e}")
        
        # 병합된 파일 저장
        with open(output_path, 'wb') as output_file:
            merger.write(output_file)
        
        # South Korea 페이지의 출처 정보 저장
        sources_filename = f"south_korea_pages_{original_name_without_ext}.txt"
        sources_path = os.path.join(app.config['SOUTH_KOREA_FOLDER'], sources_filename)
        
        with open(sources_path, 'w', encoding='utf-8') as f:
            f.write(f"원본 PDF 파일 '{original_filename}'에서 South Korea 키워드가 발견된 페이지 목록:\n\n")
            for i, (page_num, _) in enumerate(south_korea_pages, 1):
                f.write(f"{i}. 페이지: {page_num+1}\n")
        
        # 디버그 정보 저장
        debug_filename = f"south_korea_debug_{original_name_without_ext}.txt"
        debug_path = os.path.join(app.config['SOUTH_KOREA_FOLDER'], debug_filename)
        with open(debug_path, 'w', encoding='utf-8') as f:
            f.write(f"원본 PDF 파일 '{original_filename}'에서 South Korea 키워드 검색 디버그 정보:\n\n")
            for info in debug_info:
                f.write(f"{info}\n\n")
        
        result_files = [output_filename, sources_filename, debug_filename]
        
    except Exception as e:
        print(f"PDF 파일 처리 중 오류 발생: {e}")
        return []
    
    return result_files

def extract_market_definition_from_original(pdf_path):
    """원본 PDF 파일에서 Market Definition 키워드가 포함된 페이지만 추출"""
    result_files = []
    market_definition_pages = []
    debug_info = []
    
    try:
        # 원본 PDF 파일 이름 추출 (확장자 제외)
        original_filename = os.path.basename(pdf_path)
        original_name_without_ext = os.path.splitext(original_filename)[0]
        
        # 원본 PDF 읽기
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        
        print(f"총 {total_pages}페이지 PDF 파일에서 'Market Definition' 키워드 검색 중...")
        
        # 각 페이지 텍스트 검색
        for page_num, page in enumerate(reader.pages):
            try:
                text = page.extract_text().upper()
                
                # 줄바꿈 제거한 텍스트도 생성
                text_no_newlines = text.replace('\n', ' ')
                
                # 공백 정리
                text_clean = ' '.join(text.split())
                
                # 줄바꿈 관련 디버깅 (특정 키워드 주변)
                if "MARKET" in text:
                    for i in range(len(text) - 6):
                        if text[i:i+6].upper() == "MARKET" and i+6 < len(text) and '\n' in text[i+6:i+20]:
                            next_word_start = text.find("DEFINITION", i+6, i+30)
                            if next_word_start > -1:
                                print(f"페이지 {page_num+1}에서 줄바꿈으로 분리된 'MARKET\\nDEFINITION' 발견")
                                debug_info.append(f"페이지 {page_num+1}에서 줄바꿈으로 분리된 'MARKET\\nDEFINITION' 발견")
                
                # 여러 형태로 검색
                found = False
                
                # 1. 일반 형태
                if "MARKET DEFINITION" in text:
                    print(f"'MARKET DEFINITION' 키워드 발견: 페이지 {page_num+1}")
                    found = True
                
                # 2. 줄바꿈이 제거된 텍스트에서 검색
                elif "MARKET DEFINITION" in text_no_newlines:
                    print(f"줄바꿈 제거 후 'MARKET DEFINITION' 키워드 발견: 페이지 {page_num+1}")
                    found = True
                
                # 3. 정규식을 사용한 "MARKET" 다음에 공백이나 줄바꿈 후 "DEFINITION"이 오는 패턴 검색
                elif re.search(r'MARKET\s*[\n\r]*\s*DEFINITION', text):
                    print(f"줄바꿈 패턴으로 'MARKET\\nDEFINITION' 키워드 발견: 페이지 {page_num+1}")
                    found = True
                
                # 4. 'DEFINITION' 주변 컨텍스트 확인 (MARKET 단어가 근처에 있는지)
                elif "DEFINITION" in text:
                    definition_pos = text.find("DEFINITION")
                    context = text[max(0, definition_pos-50):min(len(text), definition_pos+50)]
                    if "MARKET" in context:
                        print(f"'DEFINITION' 주변에 'MARKET' 발견: 페이지 {page_num+1}")
                        found = True
                
                if found:
                    market_definition_pages.append((page_num, page))
                
            except Exception as e:
                print(f"페이지 {page_num+1} 처리 중 오류: {e}")
                debug_info.append(f"페이지 {page_num+1} 처리 중 오류: {e}")
        
        if not market_definition_pages:
            print("'Market Definition' 키워드가 포함된 페이지를 찾을 수 없습니다.")
            
            # 디버그 정보 저장
            debug_filename = f"market_definition_debug_{original_name_without_ext}.txt"
            debug_path = os.path.join(app.config['MARKET_DEFINITION_FOLDER'], debug_filename)
            with open(debug_path, 'w', encoding='utf-8') as f:
                f.write(f"원본 PDF 파일 '{original_filename}'에서 Market Definition 키워드 검색 디버그 정보:\n\n")
                for info in debug_info:
                    f.write(f"{info}\n\n")
            
            return []
        
        print(f"총 {len(market_definition_pages)}개의 페이지에서 'Market Definition' 키워드 발견")
        
        # 통합 PDF 저장 경로 (원본 파일명 포함)
        output_filename = f"MARKET_DEFINITION_Pages_{original_name_without_ext}.pdf"
        output_path = os.path.join(app.config['MARKET_DEFINITION_FOLDER'], output_filename)
        
        # 파일 병합 - 페이지 단위로
        merger = PdfWriter()
        for page_num, page in market_definition_pages:
            try:
                # 페이지 추가
                merger.add_page(page)
            except Exception as e:
                print(f"페이지 {page_num+1} 추가 중 오류: {e}")
        
        # 병합된 파일 저장
        with open(output_path, 'wb') as output_file:
            merger.write(output_file)
        
        # 출처 정보 저장
        sources_filename = f"market_definition_pages_{original_name_without_ext}.txt"
        sources_path = os.path.join(app.config['MARKET_DEFINITION_FOLDER'], sources_filename)
        
        with open(sources_path, 'w', encoding='utf-8') as f:
            f.write(f"원본 PDF 파일 '{original_filename}'에서 Market Definition 키워드가 발견된 페이지 목록:\n\n")
            for i, (page_num, _) in enumerate(market_definition_pages, 1):
                f.write(f"{i}. 페이지: {page_num+1}\n")
        
        # 디버그 정보 저장
        debug_filename = f"market_definition_debug_{original_name_without_ext}.txt"
        debug_path = os.path.join(app.config['MARKET_DEFINITION_FOLDER'], debug_filename)
        with open(debug_path, 'w', encoding='utf-8') as f:
            f.write(f"원본 PDF 파일 '{original_filename}'에서 Market Definition 키워드 검색 디버그 정보:\n\n")
            for info in debug_info:
                f.write(f"{info}\n\n")
        
        result_files = [output_filename, sources_filename, debug_filename]
        
    except Exception as e:
        print(f"PDF 파일 처리 중 오류 발생: {e}")
        return []
    
    return result_files

def extract_executive_summary_from_original(pdf_path):
    """원본 PDF 파일에서 Executive Summary 키워드가 포함된 페이지만 추출"""
    result_files = []
    executive_summary_pages = []
    debug_info = []
    
    try:
        # 원본 PDF 파일 이름 추출 (확장자 제외)
        original_filename = os.path.basename(pdf_path)
        original_name_without_ext = os.path.splitext(original_filename)[0]
        
        # 원본 PDF 읽기
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        
        print(f"총 {total_pages}페이지 PDF 파일에서 'Executive Summary' 키워드 검색 중...")
        
        # 각 페이지 텍스트 검색
        for page_num, page in enumerate(reader.pages):
            try:
                text = page.extract_text().upper()
                
                # 줄바꿈 제거한 텍스트도 생성
                text_no_newlines = text.replace('\n', ' ')
                
                # 공백 정리
                text_clean = ' '.join(text.split())
                
                # 줄바꿈 관련 디버깅 (특정 키워드 주변)
                if "EXECUTIVE" in text:
                    for i in range(len(text) - 9):
                        if text[i:i+9].upper() == "EXECUTIVE" and i+9 < len(text) and '\n' in text[i+9:i+20]:
                            next_word_start = text.find("SUMMARY", i+9, i+30)
                            if next_word_start > -1:
                                print(f"페이지 {page_num+1}에서 줄바꿈으로 분리된 'EXECUTIVE\\nSUMMARY' 발견")
                                debug_info.append(f"페이지 {page_num+1}에서 줄바꿈으로 분리된 'EXECUTIVE\\nSUMMARY' 발견")
                
                # 여러 형태로 검색
                found = False
                
                # 1. 일반 형태
                if "EXECUTIVE SUMMARY" in text:
                    print(f"'EXECUTIVE SUMMARY' 키워드 발견: 페이지 {page_num+1}")
                    found = True
                
                # 2. 줄바꿈이 제거된 텍스트에서 검색
                elif "EXECUTIVE SUMMARY" in text_no_newlines:
                    print(f"줄바꿈 제거 후 'EXECUTIVE SUMMARY' 키워드 발견: 페이지 {page_num+1}")
                    found = True
                
                # 3. 정규식을 사용한 "EXECUTIVE" 다음에 공백이나 줄바꿈 후 "SUMMARY"가 오는 패턴 검색
                elif re.search(r'EXECUTIVE\s*[\n\r]*\s*SUMMARY', text):
                    print(f"줄바꿈 패턴으로 'EXECUTIVE\\nSUMMARY' 키워드 발견: 페이지 {page_num+1}")
                    found = True
                
                # 4. 'SUMMARY' 주변 컨텍스트 확인 (EXECUTIVE 단어가 근처에 있는지)
                elif "SUMMARY" in text:
                    summary_pos = text.find("SUMMARY")
                    context = text[max(0, summary_pos-50):min(len(text), summary_pos+50)]
                    if "EXECUTIVE" in context:
                        print(f"'SUMMARY' 주변에 'EXECUTIVE' 발견: 페이지 {page_num+1}")
                        found = True
                        
                # 5. Figure가 있는지 확인 (Executive Summary 섹션 내에 있는 Figure도 포함)
                elif "FIGURE" in text or "FIG." in text:
                    fig_pos = text.find("FIGURE") if "FIGURE" in text else text.find("FIG.")
                    context = text[max(0, fig_pos-100):min(len(text), fig_pos+100)]
                    print(f"페이지 {page_num+1}에서 'FIGURE' 발견, 이전 페이지 확인 필요")
                    
                    # 추가 검사: 이전 몇 페이지를 확인하여 Executive Summary 영역인지 확인
                    # 이 부분은 실제로 사용할 때는 로직을 개선해야 할 수 있음
                    is_in_exec_summary = False
                    for prev_page_num in range(max(0, page_num-5), page_num):
                        try:
                            prev_text = reader.pages[prev_page_num].extract_text().upper()
                            if "EXECUTIVE SUMMARY" in prev_text:
                                is_in_exec_summary = True
                                print(f"페이지 {page_num+1}의 FIGURE는 EXECUTIVE SUMMARY 영역에 있음")
                                break
                        except Exception:
                            pass
                    
                    if is_in_exec_summary:
                        found = True
                
                if found:
                    executive_summary_pages.append((page_num, page))
                
            except Exception as e:
                print(f"페이지 {page_num+1} 처리 중 오류: {e}")
                debug_info.append(f"페이지 {page_num+1} 처리 중 오류: {e}")
        
        if not executive_summary_pages:
            print("'Executive Summary' 키워드가 포함된 페이지를 찾을 수 없습니다.")
            
            # 디버그 정보 저장
            debug_filename = f"executive_summary_debug_{original_name_without_ext}.txt"
            debug_path = os.path.join(app.config['FIGURE_FOLDER'], debug_filename)
            with open(debug_path, 'w', encoding='utf-8') as f:
                f.write(f"원본 PDF 파일 '{original_filename}'에서 Executive Summary 키워드 검색 디버그 정보:\n\n")
                for info in debug_info:
                    f.write(f"{info}\n\n")
            
            return []
        
        print(f"총 {len(executive_summary_pages)}개의 페이지에서 'Executive Summary' 키워드 발견")
        
        # 통합 PDF 저장 경로 (원본 파일명 포함)
        output_filename = f"EXECUTIVE_SUMMARY_Pages_{original_name_without_ext}.pdf"
        output_path = os.path.join(app.config['FIGURE_FOLDER'], output_filename)
        
        # 파일 병합 - 페이지 단위로
        merger = PdfWriter()
        for page_num, page in executive_summary_pages:
            try:
                # 페이지 추가
                merger.add_page(page)
            except Exception as e:
                print(f"페이지 {page_num+1} 추가 중 오류: {e}")
        
        # 병합된 파일 저장
        with open(output_path, 'wb') as output_file:
            merger.write(output_file)
        
        # 출처 정보 저장
        sources_filename = f"executive_summary_pages_{original_name_without_ext}.txt"
        sources_path = os.path.join(app.config['FIGURE_FOLDER'], sources_filename)
        
        with open(sources_path, 'w', encoding='utf-8') as f:
            f.write(f"원본 PDF 파일 '{original_filename}'에서 Executive Summary 키워드가 발견된 페이지 목록:\n\n")
            for i, (page_num, _) in enumerate(executive_summary_pages, 1):
                f.write(f"{i}. 페이지: {page_num+1}\n")
        
        # 디버그 정보 저장
        debug_filename = f"executive_summary_debug_{original_name_without_ext}.txt"
        debug_path = os.path.join(app.config['FIGURE_FOLDER'], debug_filename)
        with open(debug_path, 'w', encoding='utf-8') as f:
            f.write(f"원본 PDF 파일 '{original_filename}'에서 Executive Summary 키워드 검색 디버그 정보:\n\n")
            for info in debug_info:
                f.write(f"{info}\n\n")
        
        result_files = [output_filename, sources_filename, debug_filename]
        
    except Exception as e:
        print(f"PDF 파일 처리 중 오류 발생: {e}")
        return []
    
    return result_files

def extract_five_force_from_original(pdf_path):
    """원본 PDF 파일에서 Five Force Analysis 키워드가 포함된 페이지만 추출"""
    result_files = []
    five_force_pages = []
    debug_info = []
    
    # Five Force Analysis 관련 키워드 목록 정의
    five_force_keywords = [
        "FIVE FORCE", "5 FORCE", "PORTER", "COMPETITIVE RIVALRY", "THREAT OF NEW ENTRANTS", 
        "BARGAINING POWER OF BUYERS", "BARGAINING POWER OF SUPPLIERS", "THREAT OF SUBSTITUTES"
    ]
    
    try:
        # 원본 PDF 파일 이름 추출 (확장자 제외)
        original_filename = os.path.basename(pdf_path)
        original_name_without_ext = os.path.splitext(original_filename)[0]
        
        # 원본 PDF 읽기
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        
        print(f"총 {total_pages}페이지 PDF 파일에서 'Five Force Analysis' 키워드 검색 중...")
        
        # 각 페이지 텍스트 검색
        for page_num, page in enumerate(reader.pages):
            try:
                text = page.extract_text().upper()
                
                # 줄바꿈 제거한 텍스트도 생성
                text_no_newlines = text.replace('\n', ' ')
                
                # 공백 정리
                text_clean = ' '.join(text.split())
                
                # 여러 형태로 검색
                found = False
                matched_keyword = ""
                
                # 1. 키워드 직접 검색
                for keyword in five_force_keywords:
                    if keyword in text:
                        matched_keyword = keyword
                        print(f"'{keyword}' 키워드 발견: 페이지 {page_num+1}")
                        found = True
                        break
                
                # 2. 줄바꿈이 제거된 텍스트에서 검색
                if not found:
                    for keyword in five_force_keywords:
                        if keyword in text_no_newlines:
                            matched_keyword = keyword
                            print(f"줄바꿈 제거 후 '{keyword}' 키워드 발견: 페이지 {page_num+1}")
                            found = True
                            break
                
                # 3. 정규식을 사용한 키워드 주변 검색
                if not found:
                    if re.search(r'FIVE\s*[\n\r]*\s*FORCE', text):
                        matched_keyword = "FIVE FORCE"
                        print(f"줄바꿈 패턴으로 'FIVE\\nFORCE' 키워드 발견: 페이지 {page_num+1}")
                        found = True
                    elif re.search(r'PORTER\s*[\n\r]*\s*', text) and ('FORCE' in text or 'ANALYSIS' in text):
                        matched_keyword = "PORTER"
                        print(f"'PORTER' 키워드와 'FORCE/ANALYSIS' 발견: 페이지 {page_num+1}")
                        found = True
                
                # 디버그 정보 추가
                if found:
                    debug_info.append(f"페이지 {page_num+1}에서 '{matched_keyword}' 키워드 발견")
                    five_force_pages.append((page_num, page))
                
            except Exception as e:
                print(f"페이지 {page_num+1} 처리 중 오류: {e}")
                debug_info.append(f"페이지 {page_num+1} 처리 중 오류: {e}")
        
        if not five_force_pages:
            print("'Five Force Analysis' 키워드가 포함된 페이지를 찾을 수 없습니다.")
            
            # 디버그 정보 저장
            debug_filename = f"five_force_debug_{original_name_without_ext}.txt"
            debug_path = os.path.join(app.config['MARKET_DYNAMICS_FOLDER'], debug_filename)
            with open(debug_path, 'w', encoding='utf-8') as f:
                f.write(f"원본 PDF 파일 '{original_filename}'에서 Five Force Analysis 키워드 검색 디버그 정보:\n\n")
                for info in debug_info:
                    f.write(f"{info}\n\n")
            
            return []
        
        print(f"총 {len(five_force_pages)}개의 페이지에서 'Five Force Analysis' 키워드 발견")
        
        # 통합 PDF 저장 경로 (원본 파일명 포함)
        output_filename = f"FIVE_FORCE_Pages_{original_name_without_ext}.pdf"
        output_path = os.path.join(app.config['MARKET_DYNAMICS_FOLDER'], output_filename)
        
        # 파일 병합 - 페이지 단위로
        merger = PdfWriter()
        for page_num, page in five_force_pages:
            try:
                # 페이지 추가
                merger.add_page(page)
            except Exception as e:
                print(f"페이지 {page_num+1} 추가 중 오류: {e}")
        
        # 병합된 파일 저장
        with open(output_path, 'wb') as output_file:
            merger.write(output_file)
        
        # 출처 정보 저장
        sources_filename = f"five_force_pages_{original_name_without_ext}.txt"
        sources_path = os.path.join(app.config['MARKET_DYNAMICS_FOLDER'], sources_filename)
        
        with open(sources_path, 'w', encoding='utf-8') as f:
            f.write(f"원본 PDF 파일 '{original_filename}'에서 Five Force Analysis 키워드가 발견된 페이지 목록:\n\n")
            for i, (page_num, _) in enumerate(five_force_pages, 1):
                f.write(f"{i}. 페이지: {page_num+1}\n")
        
        # 디버그 정보 저장
        debug_filename = f"five_force_debug_{original_name_without_ext}.txt"
        debug_path = os.path.join(app.config['MARKET_DYNAMICS_FOLDER'], debug_filename)
        with open(debug_path, 'w', encoding='utf-8') as f:
            f.write(f"원본 PDF 파일 '{original_filename}'에서 Five Force Analysis 키워드 검색 디버그 정보:\n\n")
            for info in debug_info:
                f.write(f"{info}\n\n")
        
        result_files = [output_filename, sources_filename, debug_filename]
        
    except Exception as e:
        print(f"PDF 파일 처리 중 오류 발생: {e}")
        return []
    
    return result_files

def extract_south_korea_sections(output_folder):
    """South Korea 키워드가 포함된 페이지만 추출하여 병합"""
    result_files = []
    south_korea_pages = []
    
    # 모든 PDF 파일 대상으로 텍스트 검색
    files = os.listdir(output_folder)
    
    for file in files:
        if not file.endswith('.pdf'):
            continue
            
        file_path = os.path.join(output_folder, file)
        
        # PDF에서 텍스트 추출
        try:
            reader = PdfReader(file_path)
            
            # 각 페이지 텍스트 검색
            for page_num, page in enumerate(reader.pages):
                text = page.extract_text().upper()
                if "SOUTH KOREA" in text:
                    print(f"'SOUTH KOREA' 키워드 발견: {file}, 페이지 {page_num+1}")
                    # 페이지와 출처 파일명 저장
                    south_korea_pages.append((file_path, page_num, page))
        except Exception as e:
            print(f"파일 처리 중 오류 발생: {file_path}, 오류: {e}")
    
    if not south_korea_pages:
        return []
    
    # 통합 PDF 저장 경로
    output_filename = "SOUTH_KOREA_Pages.pdf"
    output_path = os.path.join(app.config['SOUTH_KOREA_FOLDER'], output_filename)
    
    # 파일 병합 - 페이지 단위로
    merger = PdfWriter()
    for file_path, _, page in south_korea_pages:
        try:
            # 페이지만 추가
            merger.add_page(page)
        except Exception as e:
            print(f"페이지 추가 중 오류 발생: {file_path}, 오류: {e}")
    
    # 병합된 파일 저장
    with open(output_path, 'wb') as output_file:
        merger.write(output_file)
    
    # South Korea 페이지의 출처 정보 저장
    sources_filename = "south_korea_sources.txt"
    sources_path = os.path.join(app.config['SOUTH_KOREA_FOLDER'], sources_filename)
    
    with open(sources_path, 'w', encoding='utf-8') as f:
        f.write("South Korea 키워드가 발견된 페이지 목록:\n\n")
        for i, (file_path, page_num, _) in enumerate(south_korea_pages, 1):
            f.write(f"{i}. 파일: {os.path.basename(file_path)}, 페이지: {page_num+1}\n")
    
    result_files = [output_filename, sources_filename]
    return result_files

def extract_executive_summary_figures(output_folder):
    """EXECUTIVE SUMMARY 섹션에서 Figure 8-15 추출"""
    if not OCR_AVAILABLE:
        return []
        
    result_files = []
    executive_summary_files = []
    
    # 모든 PDF 파일 경로 가져오기
    files = os.listdir(output_folder)
    
    # "EXECUTIVE SUMMARY" 문자열이 포함된 파일 찾기
    for file in files:
        if file.endswith('.pdf') and "EXECUTIVE SUMMARY" in file.upper():
            executive_summary_files.append(os.path.join(output_folder, file))
    
    if not executive_summary_files:
        return []
    
    figure_images = []
    figure_count = 0
    
    # 각 Executive Summary 파일 처리
    for file_path in executive_summary_files:
        try:
            reader = PdfReader(file_path)
            
            for page_num, page in enumerate(reader.pages):
                # PDF 페이지를 이미지로 변환
                try:
                    # 현재는 더미 로직 - 실제 구현시 PDF 페이지를 이미지로 변환하는 코드 필요
                    # 예: pdf2image 라이브러리 사용
                    
                    # 텍스트 추출하여 "Figure" 문자열 포함 여부 확인
                    text = page.extract_text()
                    if "FIGURE" in text.upper() or "FIG." in text.upper():
                        # Figure 번호 추출
                        figure_match = re.search(r'FIGURE\s+(\d+)[:\.]', text.upper())
                        figure_num = figure_match.group(1) if figure_match else f"unknown_{figure_count}"
                        
                        # 이미지 저장 (더미 로직)
                        output_filename = f"Figure_{figure_num}.png"
                        output_path = os.path.join(app.config['FIGURE_FOLDER'], output_filename)
                        
                        # 더미 이미지 생성 (PIL이 있는 경우에만)
                        try:
                            img = Image.new('RGB', (800, 600), color=(255, 255, 255))
                            img.save(output_path)
                        except NameError:
                            # PIL이 없는 경우 빈 파일 생성
                            with open(output_path, 'wb') as f:
                                f.write(b'')
                        
                        figure_images.append(output_filename)
                        figure_count += 1
                        
                except Exception as e:
                    print(f"페이지 처리 중 오류 발생: {file_path}, 페이지: {page_num}, 오류: {e}")
        
        except Exception as e:
            print(f"파일 처리 중 오류 발생: {file_path}, 오류: {e}")
    
    # PDF 형태로도 저장
    if figure_images:
        # 통합 PDF 저장 경로
        output_filename = "Executive_Summary_Figures.pdf"
        output_path = os.path.join(app.config['FIGURE_FOLDER'], output_filename)
        
        # 더미 PDF 생성 (실제 구현 시 이미지를 PDF로 변환하는 코드 필요)
        writer = PdfWriter()
        try:
            dummy_page = writer.add_blank_page(width=800, height=600)
            writer.add_page(dummy_page)
        except:
            # 빈 페이지 추가 메서드가 실패하면 빈 PdfWriter 객체 사용
            pass
        
        # 병합된 파일 저장
        with open(output_path, 'wb') as output_file:
            writer.write(output_file)
        
        figure_images.append(output_filename)
    
    return figure_images

def extract_market_dynamics_images(output_folder):
    """Market Dynamics 섹션에서 Driver/Restraints/Opportunity/Challenge 이미지 추출"""
    if not OCR_AVAILABLE:
        return []
        
    result_files = []
    market_dynamics_files = []
    
    # 모든 PDF 파일 경로 가져오기
    files = os.listdir(output_folder)
    
    # "MARKET DYNAMICS" 문자열이 포함된 파일 찾기
    for file in files:
        if file.endswith('.pdf') and "MARKET DYNAMICS" in file.upper():
            market_dynamics_files.append(os.path.join(output_folder, file))
    
    if not market_dynamics_files:
        return []
    
    dynamics_images = []
    dynamics_count = 0
    
    keywords = ["DRIVER", "RESTRAINT", "OPPORTUNITY", "CHALLENGE"]
    
    # 각 Market Dynamics 파일 처리
    for file_path in market_dynamics_files:
        try:
            reader = PdfReader(file_path)
            
            for page_num, page in enumerate(reader.pages):
                # 텍스트 추출하여 키워드 포함 여부 확인
                text = page.extract_text().upper()
                
                for keyword in keywords:
                    if keyword in text:
                        # 더미 이미지 생성 (실제 구현 시 제거)
                        output_filename = f"{keyword.lower()}_{dynamics_count}.png"
                        output_path = os.path.join(app.config['MARKET_DYNAMICS_FOLDER'], output_filename)
                        
                        # 더미 이미지 생성 (PIL이 있는 경우에만)
                        try:
                            img = Image.new('RGB', (800, 600), color=(255, 255, 255))
                            img.save(output_path)
                        except NameError:
                            # PIL이 없는 경우 빈 파일 생성
                            with open(output_path, 'wb') as f:
                                f.write(b'')
                        
                        dynamics_images.append(output_filename)
                        dynamics_count += 1
        
        except Exception as e:
            print(f"파일 처리 중 오류 발생: {file_path}, 오류: {e}")
    
    # PDF 형태로도 저장
    if dynamics_images:
        # 통합 PDF 저장 경로
        output_filename = "Market_Dynamics_Images.pdf"
        output_path = os.path.join(app.config['MARKET_DYNAMICS_FOLDER'], output_filename)
        
        # 더미 PDF 생성 (실제 구현 시 이미지를 PDF로 변환하는 코드 필요)
        writer = PdfWriter()
        try:
            dummy_page = writer.add_blank_page(width=800, height=600)
            writer.add_page(dummy_page)
        except:
            # 빈 페이지 추가 메서드가 실패하면 빈 PdfWriter 객체 사용
            pass
        
        # 병합된 파일 저장
        with open(output_path, 'wb') as output_file:
            writer.write(output_file)
        
        dynamics_images.append(output_filename)
    
    return dynamics_images

def extract_market_overview_from_original(pdf_path):
    """원본 PDF 파일에서 Market Overview 키워드가 포함된 페이지만 추출"""
    result_files = []
    market_overview_pages = []
    extracted_page_numbers = []  # 추출된 페이지 번호를 저장할 리스트
    debug_info = []
    
    try:
        # 원본 PDF 파일 이름 추출 (확장자 제외)
        original_filename = os.path.basename(pdf_path)
        original_name_without_ext = os.path.splitext(original_filename)[0]
        
        # 원본 PDF 읽기
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        
        print(f"총 {total_pages}페이지 PDF 파일에서 'Market Overview' 키워드 검색 중...")
        
        # 특정 페이지 범위를 먼저 추가 (42페이지와 44-64페이지)
        # PDF 페이지는 0부터 시작하므로 -1 해줌
        special_pages = [41]  # 42페이지
        special_pages.extend(range(43, 64))  # 44-64페이지
        
        # 특정 페이지 범위 추가
        for page_idx in special_pages:
            if 0 <= page_idx < total_pages:  # 페이지 범위 확인
                market_overview_pages.append((page_idx, reader.pages[page_idx]))
                extracted_page_numbers.append(page_idx + 1)  # 1부터 시작하는 페이지 번호 저장
                print(f"특정 범위에 포함된 페이지 추가: {page_idx+1}")
        
        # 각 페이지 텍스트 검색
        for page_num, page in enumerate(reader.pages):
            # 이미 특정 페이지 범위에 포함된 페이지는 중복 추가하지 않음
            if page_num in special_pages:
                continue
                
            try:
                text = page.extract_text().upper()
                
                # 줄바꿈 제거한 텍스트도 생성
                text_no_newlines = text.replace('\n', ' ')
                
                # 공백 정리
                text_clean = ' '.join(text.split())
                
                # 줄바꿈 관련 디버깅 (특정 키워드 주변)
                if "MARKET" in text:
                    for i in range(len(text) - 6):
                        if text[i:i+6].upper() == "MARKET" and i+6 < len(text) and '\n' in text[i+6:i+20]:
                            next_word_start = text.find("OVERVIEW", i+6, i+30)
                            if next_word_start > -1:
                                print(f"페이지 {page_num+1}에서 줄바꿈으로 분리된 'MARKET\\nOVERVIEW' 발견")
                                debug_info.append(f"페이지 {page_num+1}에서 줄바꿈으로 분리된 'MARKET\\nOVERVIEW' 발견")
                
                # 여러 형태로 검색
                found = False
                
                # 1. 일반 형태
                if "MARKET OVERVIEW" in text:
                    print(f"'MARKET OVERVIEW' 키워드 발견: 페이지 {page_num+1}")
                    found = True
                
                # 2. 줄바꿈이 제거된 텍스트에서 검색
                elif "MARKET OVERVIEW" in text_no_newlines:
                    print(f"줄바꿈 제거 후 'MARKET OVERVIEW' 키워드 발견: 페이지 {page_num+1}")
                    found = True
                
                # 3. 정규식을 사용한 "MARKET" 다음에 공백이나 줄바꿈 후 "OVERVIEW"가 오는 패턴 검색
                elif re.search(r'MARKET\s*[\n\r]*\s*OVERVIEW', text):
                    print(f"줄바꿈 패턴으로 'MARKET\\nOVERVIEW' 키워드 발견: 페이지 {page_num+1}")
                    found = True
                
                # 4. 'OVERVIEW' 주변 컨텍스트 확인 (MARKET 단어가 근처에 있는지)
                elif "OVERVIEW" in text:
                    overview_pos = text.find("OVERVIEW")
                    context = text[max(0, overview_pos-50):min(len(text), overview_pos+50)]
                    if "MARKET" in context:
                        print(f"'OVERVIEW' 주변에 'MARKET' 발견: 페이지 {page_num+1}")
                        found = True
                
                if found:
                    market_overview_pages.append((page_num, page))
                    extracted_page_numbers.append(page_num + 1)  # 1부터 시작하는 페이지 번호 저장
                
            except Exception as e:
                print(f"페이지 {page_num+1} 처리 중 오류: {e}")
                debug_info.append(f"페이지 {page_num+1} 처리 중 오류: {e}")
        
        if not market_overview_pages:
            print("'Market Overview' 키워드가 포함된 페이지를 찾을 수 없습니다.")
            
            # 디버그 정보 저장
            debug_filename = f"market_overview_debug_{original_name_without_ext}.txt"
            debug_path = os.path.join(app.config['MARKET_OVERVIEW_FOLDER'], debug_filename)
            with open(debug_path, 'w', encoding='utf-8') as f:
                f.write(f"원본 PDF 파일 '{original_filename}'에서 Market Overview 키워드 검색 디버그 정보:\n\n")
                for info in debug_info:
                    f.write(f"{info}\n\n")
            
            return [], []
        
        # 페이지 번호로 정렬
        market_overview_pages.sort(key=lambda x: x[0])
        extracted_page_numbers.sort()
        
        print(f"총 {len(market_overview_pages)}개의 페이지가 추출됨")
        
        # 통합 PDF 저장 경로 (원본 파일명 포함)
        output_filename = f"MARKET_OVERVIEW_Pages_{original_name_without_ext}.pdf"
        output_path = os.path.join(app.config['MARKET_OVERVIEW_FOLDER'], output_filename)
        
        # 파일 병합 - 페이지 단위로
        merger = PdfWriter()
        for page_num, page in market_overview_pages:
            try:
                # 페이지 추가
                merger.add_page(page)
            except Exception as e:
                print(f"페이지 {page_num+1} 추가 중 오류: {e}")
        
        # 병합된 파일 저장
        with open(output_path, 'wb') as output_file:
            merger.write(output_file)
        
        # 출처 정보 저장
        sources_filename = f"market_overview_pages_{original_name_without_ext}.txt"
        sources_path = os.path.join(app.config['MARKET_OVERVIEW_FOLDER'], sources_filename)
        
        with open(sources_path, 'w', encoding='utf-8') as f:
            f.write(f"원본 PDF 파일 '{original_filename}'에서 Market Overview 관련 페이지 목록:\n\n")
            for i, (page_num, _) in enumerate(market_overview_pages, 1):
                f.write(f"{i}. 페이지: {page_num+1}\n")
        
        # 디버그 정보 저장
        debug_filename = f"market_overview_debug_{original_name_without_ext}.txt"
        debug_path = os.path.join(app.config['MARKET_OVERVIEW_FOLDER'], debug_filename)
        with open(debug_path, 'w', encoding='utf-8') as f:
            f.write(f"원본 PDF 파일 '{original_filename}'에서 Market Overview 키워드 검색 디버그 정보:\n\n")
            for info in debug_info:
                f.write(f"{info}\n\n")
        
        result_files = [output_filename, sources_filename, debug_filename]
        
    except Exception as e:
        print(f"PDF 파일 처리 중 오류 발생: {e}")
        return [], []
    
    return result_files, extracted_page_numbers

def extract_market_overview_sections(output_folder):
    """Market Overview 키워드가 포함된 페이지만 추출하여 병합"""
    result_files = []
    market_overview_pages = []
    market_overview_chapters = []  # Market Overview가 포함된 챕터 저장
    
    # 모든 PDF 파일 대상으로 텍스트 검색
    files = os.listdir(output_folder)
    
    # 1단계: 먼저 대제목에 Market Overview가 포함된 파일 찾기
    for file in files:
        if not file.endswith('.pdf'):
            continue
        
        # 파일명에서 챕터 번호와 제목 추출
        match = re.match(r'^(\d+(?:\.\d+)?)\s+(.+?)\s+\(p\d+-p\d+\)\.pdf$', file)
        if match:
            chapter_num, chapter_title = match.groups()
            if "MARKET OVERVIEW" in chapter_title.upper():
                print(f"대제목에 'MARKET OVERVIEW' 포함된 챕터 발견: {file}")
                market_overview_chapters.append(chapter_num)
    
    # 2단계: 모든 PDF 파일에서 검색
    for file in files:
        if not file.endswith('.pdf'):
            continue
            
        file_path = os.path.join(output_folder, file)
        
        # 같은 챕터인지 확인 (대제목 또는 소제목)
        is_chapter_match = False
        match = re.match(r'^(\d+(?:\.\d+)?)\s+(.+?)\s+\(p\d+-p\d+\)\.pdf$', file)
        if match:
            file_chapter_num = match.group(1)
            # 대제목과 같은 챕터 번호이거나, 대제목의 하위 챕터인 경우
            for chapter_num in market_overview_chapters:
                # 정확히 일치하거나, 소제목이 해당 대제목의 하위인 경우 (예: 5.1은 5의 하위)
                if file_chapter_num == chapter_num or (file_chapter_num.startswith(chapter_num + '.')):
                    is_chapter_match = True
                    print(f"Market Overview 챕터에 속한 파일 발견: {file}")
                    break
        
        # 대제목/소제목에 포함되는 경우 전체 페이지 추가
        if is_chapter_match:
            try:
                reader = PdfReader(file_path)
                for page_num, page in enumerate(reader.pages):
                    market_overview_pages.append((file_path, page_num, page))
                continue  # 이미 모든 페이지를 추가했으므로 다음 파일로
            except Exception as e:
                print(f"파일 처리 중 오류 발생: {file_path}, 오류: {e}")
        
        # 대제목에 포함되지 않는 경우 키워드 검색
        try:
            reader = PdfReader(file_path)
            
            # 각 페이지 텍스트 검색
            for page_num, page in enumerate(reader.pages):
                text = page.extract_text().upper()
                if "MARKET OVERVIEW" in text:
                    print(f"'MARKET OVERVIEW' 키워드 발견: {file}, 페이지 {page_num+1}")
                    # 페이지와 출처 파일명 저장
                    market_overview_pages.append((file_path, page_num, page))
        except Exception as e:
            print(f"파일 처리 중 오류 발생: {file_path}, 오류: {e}")
    
    if not market_overview_pages:
        return []
    
    # 통합 PDF 저장 경로
    output_filename = "MARKET_OVERVIEW_Pages.pdf"
    output_path = os.path.join(app.config['MARKET_OVERVIEW_FOLDER'], output_filename)
    
    # 파일 병합 - 페이지 단위로
    merger = PdfWriter()
    for file_path, _, page in market_overview_pages:
        try:
            # 페이지만 추가
            merger.add_page(page)
        except Exception as e:
            print(f"페이지 추가 중 오류 발생: {file_path}, 오류: {e}")
    
    # 병합된 파일 저장
    with open(output_path, 'wb') as output_file:
        merger.write(output_file)
    
    # Market Overview 페이지의 출처 정보 저장
    sources_filename = "market_overview_sources.txt"
    sources_path = os.path.join(app.config['MARKET_OVERVIEW_FOLDER'], sources_filename)
    
    with open(sources_path, 'w', encoding='utf-8') as f:
        f.write("Market Overview 키워드가 발견된 페이지 목록:\n\n")
        for i, (file_path, page_num, _) in enumerate(market_overview_pages, 1):
            f.write(f"{i}. 파일: {os.path.basename(file_path)}, 페이지: {page_num+1}\n")
    
    result_files = [output_filename, sources_filename]
    return result_files

@app.route('/direct_executive_summary', methods=['GET', 'POST'])
def direct_executive_summary():
    if request.method == 'POST':
        file = request.files['file']
        if file and file.filename.endswith('.pdf'):
            input_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(input_path)
            
            # Executive Summary 키워드 검색 및 페이지 추출
            result_files = extract_executive_summary_from_original(input_path)
            
            if not result_files:
                return "PDF 파일에서 'Executive Summary' 키워드가 포함된 페이지를 찾을 수 없습니다. <a href='/direct_executive_summary'>돌아가기</a>"
            
            return '''
            <h1>Executive Summary 관련 페이지 추출 완료</h1>
            <ul>
            ''' + ''.join([f"<li><a href='/download_special/figures/{file}'>{file}</a></li>" for file in result_files]) + '''
            </ul>
            <p><a href='/direct_executive_summary'>다른 PDF 파일 업로드</a></p>
            <p><a href='/'>메인 페이지로 돌아가기</a></p>
            '''
        else:
            return "유효한 PDF 파일을 업로드해주세요."
            
    return '''
    <!doctype html>
    <title>Executive Summary 페이지 추출</title>
    <h1>원본 PDF 파일에서 Executive Summary 키워드가 포함된 페이지만 추출</h1>
    <form method=post enctype=multipart/form-data>
      <input type=file name=file>
      <input type=submit value=업로드>
    </form>
    <p><a href='/'>메인 페이지로 돌아가기</a></p>
    '''

@app.route('/direct_market_definition', methods=['GET', 'POST'])
def direct_market_definition():
    if request.method == 'POST':
        file = request.files['file']
        if file and file.filename.endswith('.pdf'):
            input_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(input_path)
            
            # Market Definition 키워드 검색 및 페이지 추출
            result_files = extract_market_definition_from_original(input_path)
            
            if not result_files:
                return "PDF 파일에서 'Market Definition' 키워드가 포함된 페이지를 찾을 수 없습니다. <a href='/direct_market_definition'>돌아가기</a>"
            
            return '''
            <h1>Market Definition 관련 페이지 추출 완료</h1>
            <ul>
            ''' + ''.join([f"<li><a href='/download_special/market_definition/{file}'>{file}</a></li>" for file in result_files]) + '''
            </ul>
            <p><a href='/direct_market_definition'>다른 PDF 파일 업로드</a></p>
            <p><a href='/'>메인 페이지로 돌아가기</a></p>
            '''
        else:
            return "유효한 PDF 파일을 업로드해주세요."
            
    return '''
    <!doctype html>
    <title>Market Definition 페이지 추출</title>
    <h1>원본 PDF 파일에서 Market Definition 키워드가 포함된 페이지만 추출</h1>
    <form method=post enctype=multipart/form-data>
      <input type=file name=file>
      <input type=submit value=업로드>
    </form>
    <p><a href='/'>메인 페이지로 돌아가기</a></p>
    '''

@app.route('/direct_south_korea', methods=['GET', 'POST'])
def direct_south_korea():
    if request.method == 'POST':
        file = request.files['file']
        if file and file.filename.endswith('.pdf'):
            input_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(input_path)
            
            # South Korea 키워드 검색 및 페이지 추출
            result_files = extract_south_korea_from_original(input_path)
            
            if not result_files:
                return "PDF 파일에서 'South Korea' 키워드가 포함된 페이지를 찾을 수 없습니다. <a href='/direct_south_korea'>돌아가기</a>"
            
            return '''
            <h1>South Korea 관련 페이지 추출 완료</h1>
            <ul>
            ''' + ''.join([f"<li><a href='/download_special/south_korea/{file}'>{file}</a></li>" for file in result_files]) + '''
            </ul>
            <p><a href='/direct_south_korea'>다른 PDF 파일 업로드</a></p>
            <p><a href='/'>메인 페이지로 돌아가기</a></p>
            '''
        else:
            return "유효한 PDF 파일을 업로드해주세요."
            
    return '''
    <!doctype html>
    <title>South Korea 페이지 추출</title>
    <h1>원본 PDF 파일에서 South Korea 키워드가 포함된 페이지만 추출</h1>
    <form method=post enctype=multipart/form-data>
      <input type=file name=file>
      <input type=submit value=업로드>
    </form>
    <p><a href='/'>메인 페이지로 돌아가기</a></p>
    '''

@app.route('/direct_five_force', methods=['GET', 'POST'])
def direct_five_force():
    if request.method == 'POST':
        file = request.files['file']
        if file and file.filename.endswith('.pdf'):
            input_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(input_path)
            
            # Five Force Analysis 키워드 검색 및 페이지 추출
            result_files = extract_five_force_from_original(input_path)
            
            if not result_files:
                return "PDF 파일에서 'Five Force Analysis' 키워드가 포함된 페이지를 찾을 수 없습니다. <a href='/direct_five_force'>돌아가기</a>"
            
            return '''
            <h1>Five Force Analysis 관련 페이지 추출 완료</h1>
            <ul>
            ''' + ''.join([f"<li><a href='/download_special/market_dynamics/{file}'>{file}</a></li>" for file in result_files]) + '''
            </ul>
            <p><a href='/direct_five_force'>다른 PDF 파일 업로드</a></p>
            <p><a href='/'>메인 페이지로 돌아가기</a></p>
            '''
        else:
            return "유효한 PDF 파일을 업로드해주세요."
            
    return '''
    <!doctype html>
    <title>Five Force Analysis 페이지 추출</title>
    <h1>원본 PDF 파일에서 Five Force Analysis 키워드가 포함된 페이지만 추출</h1>
    <form method=post enctype=multipart/form-data>
      <input type=file name=file>
      <input type=submit value=업로드>
    </form>
    <p><a href='/'>메인 페이지로 돌아가기</a></p>
    '''

@app.route('/direct_market_overview', methods=['GET', 'POST'])
def direct_market_overview():
    if request.method == 'POST':
        file = request.files['file']
        if file and file.filename.endswith('.pdf'):
            input_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(input_path)
            
            # Market Overview 키워드 검색 및 페이지 추출
            result_files, _ = extract_market_overview_from_original(input_path)
            
            if not result_files:
                return "PDF 파일에서 'Market Overview' 키워드가 포함된 페이지를 찾을 수 없습니다. <a href='/direct_market_overview'>돌아가기</a>"
            
            return '''
            <h1>Market Overview 관련 페이지 추출 완료</h1>
            <ul>
            ''' + ''.join([f"<li><a href='/download_special/market_overview/{file}'>{file}</a></li>" for file in result_files]) + '''
            </ul>
            <p><a href='/direct_market_overview'>다른 PDF 파일 업로드</a></p>
            <p><a href='/'>메인 페이지로 돌아가기</a></p>
            '''
        else:
            return "유효한 PDF 파일을 업로드해주세요."
            
    return '''
    <!doctype html>
    <title>Market Overview 페이지 추출</title>
    <h1>원본 PDF 파일에서 Market Overview 키워드가 포함된 페이지만 추출</h1>
    <form method=post enctype=multipart/form-data>
      <input type=file name=file>
      <input type=submit value=업로드>
    </form>
    <p><a href='/'>메인 페이지로 돌아가기</a></p>
    '''

def extract_market_share_from_original(pdf_path):
    """원본 PDF 파일에서 Market Share 키워드가 포함된 페이지만 추출"""
    result_files = []
    market_share_pages = []
    debug_info = []
    
    try:
        # 원본 PDF 파일 이름 추출 (확장자 제외)
        original_filename = os.path.basename(pdf_path)
        original_name_without_ext = os.path.splitext(original_filename)[0]
        
        # 원본 PDF 읽기
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        
        print(f"총 {total_pages}페이지 PDF 파일에서 'Market Share' 키워드 검색 중...")
        
        # 특정 페이지 범위를 추가 - 주로 149-150 페이지 근처에서 많이 발견됨
        special_pages = list(range(148, 153))  # 149-153 페이지
        
        # 각 페이지 텍스트 검색
        for page_num, page in enumerate(reader.pages):
            try:
                text = page.extract_text().upper()
                
                # 줄바꿈 제거한 텍스트도 생성
                text_no_newlines = text.replace('\n', ' ')
                
                # 공백 정리
                text_clean = ' '.join(text.split())
                
                # 특정 페이지 주변 텍스트 상세 로깅
                if page_num+1 in special_pages:
                    sample_text = text[:300] + "..." if len(text) > 300 else text
                    print(f"페이지 {page_num+1} 텍스트 샘플: {sample_text}")
                    debug_info.append(f"페이지 {page_num+1} 텍스트 샘플: {sample_text}")
                
                # 줄바꿈 관련 디버깅 (특정 키워드 주변)
                if "MARKET" in text:
                    for i in range(len(text) - 6):
                        if text[i:i+6].upper() == "MARKET" and i+6 < len(text) and '\n' in text[i+6:i+20]:
                            next_word_start = text.find("SHARE", i+6, i+30)
                            if next_word_start > -1:
                                print(f"페이지 {page_num+1}에서 줄바꿈으로 분리된 'MARKET\\nSHARE' 발견")
                                debug_info.append(f"페이지 {page_num+1}에서 줄바꿈으로 분리된 'MARKET\\nSHARE' 발견")
                
                # 여러 형태로 검색
                found = False
                
                # 1. 일반 형태
                if "MARKET SHARE" in text:
                    print(f"'MARKET SHARE' 키워드 발견: 페이지 {page_num+1}")
                    found = True
                
                # 2. 줄바꿈이 제거된 텍스트에서 검색
                elif "MARKET SHARE" in text_no_newlines:
                    print(f"줄바꿈 제거 후 'MARKET SHARE' 키워드 발견: 페이지 {page_num+1}")
                    found = True
                
                # 3. 정규식을 사용한 "MARKET" 다음에 공백이나 줄바꿈 후 "SHARE"가 오는 패턴 검색
                elif re.search(r'MARKET\s*[\n\r]*\s*SHARE', text):
                    print(f"줄바꿈 패턴으로 'MARKET\\nSHARE' 키워드 발견: 페이지 {page_num+1}")
                    found = True
                
                # 4. "MARKET SHARE ANALYSIS" 포함 페이지 검색 (특별 케이스)
                elif "MARKET SHARE ANALYSIS" in text or re.search(r'MARKET\s*[\n\r]*\s*SHARE\s*[\n\r]*\s*ANALYSIS', text):
                    print(f"'MARKET SHARE ANALYSIS' 키워드 발견: 페이지 {page_num+1}")
                    found = True
                
                # 5. 'SHARE' 주변 컨텍스트 확인 (MARKET 단어가 근처에 있는지)
                elif "SHARE" in text:
                    share_pos = text.find("SHARE")
                    context = text[max(0, share_pos-50):min(len(text), share_pos+50)]
                    if "MARKET" in context:
                        print(f"'SHARE' 주변에 'MARKET' 발견: 페이지 {page_num+1}")
                        found = True
                
                if found:
                    market_share_pages.append((page_num, page))
                
            except Exception as e:
                print(f"페이지 {page_num+1} 처리 중 오류: {e}")
                debug_info.append(f"페이지 {page_num+1} 처리 중 오류: {e}")
        
        if not market_share_pages:
            print("'Market Share' 키워드가 포함된 페이지를 찾을 수 없습니다.")
            
            # 디버그 정보 저장
            debug_filename = f"market_share_debug_{original_name_without_ext}.txt"
            debug_path = os.path.join(app.config['MARKET_SHARE_FOLDER'], debug_filename)
            with open(debug_path, 'w', encoding='utf-8') as f:
                f.write(f"원본 PDF 파일 '{original_filename}'에서 Market Share 키워드 검색 디버그 정보:\n\n")
                for info in debug_info:
                    f.write(f"{info}\n\n")
            
            return []
        
        print(f"총 {len(market_share_pages)}개의 페이지에서 'Market Share' 키워드 발견")
        
        # 통합 PDF 저장 경로 (원본 파일명 포함)
        output_filename = f"MARKET_SHARE_Pages_{original_name_without_ext}.pdf"
        output_path = os.path.join(app.config['MARKET_SHARE_FOLDER'], output_filename)
        
        # 파일 병합 - 페이지 단위로
        merger = PdfWriter()
        for page_num, page in market_share_pages:
            try:
                # 페이지 추가
                merger.add_page(page)
            except Exception as e:
                print(f"페이지 {page_num+1} 추가 중 오류: {e}")
        
        # 병합된 파일 저장
        with open(output_path, 'wb') as output_file:
            merger.write(output_file)
        
        # Market Share 페이지의 출처 정보 저장
        sources_filename = f"market_share_pages_{original_name_without_ext}.txt"
        sources_path = os.path.join(app.config['MARKET_SHARE_FOLDER'], sources_filename)
        
        with open(sources_path, 'w', encoding='utf-8') as f:
            f.write(f"원본 PDF 파일 '{original_filename}'에서 Market Share 키워드가 발견된 페이지 목록:\n\n")
            for i, (page_num, _) in enumerate(market_share_pages, 1):
                f.write(f"{i}. 페이지: {page_num+1}\n")
        
        # 디버그 정보 저장
        debug_filename = f"market_share_debug_{original_name_without_ext}.txt"
        debug_path = os.path.join(app.config['MARKET_SHARE_FOLDER'], debug_filename)
        with open(debug_path, 'w', encoding='utf-8') as f:
            f.write(f"원본 PDF 파일 '{original_filename}'에서 Market Share 키워드 검색 디버그 정보:\n\n")
            for info in debug_info:
                f.write(f"{info}\n\n")
        
        result_files = [output_filename, sources_filename, debug_filename]
        
    except Exception as e:
        print(f"PDF 파일 처리 중 오류 발생: {e}")
        return []
    
    return result_files

@app.route('/direct_market_share', methods=['GET', 'POST'])
def direct_market_share():
    if request.method == 'POST':
        file = request.files['file']
        if file and file.filename.endswith('.pdf'):
            input_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(input_path)
            
            # Market Share 키워드 검색 및 페이지 추출
            result_files = extract_market_share_from_original(input_path)
            
            if not result_files:
                return "PDF 파일에서 'Market Share' 키워드가 포함된 페이지를 찾을 수 없습니다. <a href='/direct_market_share'>돌아가기</a>"
            
            return '''
            <h1>Market Share 관련 페이지 추출 완료</h1>
            <ul>
            ''' + ''.join([f"<li><a href='/download_special/market_share/{file}'>{file}</a></li>" for file in result_files]) + '''
            </ul>
            <p><a href='/direct_market_share'>다른 PDF 파일 업로드</a></p>
            <p><a href='/'>메인 페이지로 돌아가기</a></p>
            '''
        else:
            return "유효한 PDF 파일을 업로드해주세요."
            
    return '''
    <!doctype html>
    <title>Market Share 페이지 추출</title>
    <h1>원본 PDF 파일에서 Market Share 키워드가 포함된 페이지만 추출</h1>
    <form method=post enctype=multipart/form-data>
      <input type=file name=file>
      <input type=submit value=업로드>
    </form>
    <p><a href='/'>메인 페이지로 돌아가기</a></p>
    '''

@app.route('/download_special/<folder>/<filename>')
def download_special_file(folder, filename):
    folder_map = {
        'market_definition': app.config['MARKET_DEFINITION_FOLDER'],
        'figures': app.config['FIGURE_FOLDER'],
        'market_dynamics': app.config['MARKET_DYNAMICS_FOLDER'],
        'south_korea': app.config['SOUTH_KOREA_FOLDER'],
        'market_overview': app.config['MARKET_OVERVIEW_FOLDER'],
        'market_share': app.config['MARKET_SHARE_FOLDER']
    }
    
    if folder not in folder_map:
        return "잘못된 폴더 경로입니다."
    
    return send_from_directory(folder_map[folder], filename)

# 앱 실행 시 DB 테이블 생성
with app.app_context():
    # SQLite DB 파일 위치 확인
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    print(f"데이터베이스 URI: {db_uri}")
    
    if db_uri.startswith('sqlite:///'):
        db_path = db_uri.replace('sqlite:///', '')
        db_abs_path = os.path.abspath(db_path)
        print(f"SQLite DB 파일 경로: {db_abs_path}")
        db_dir = os.path.dirname(db_abs_path)
        print(f"DB 디렉토리: {db_dir} (존재: {os.path.exists(db_dir)})")
    
    try:
        print("데이터베이스 테이블 생성 시작")
        db.create_all()
        print("데이터베이스 테이블 생성 완료")
        
        # 테이블 목록 확인
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        print(f"데이터베이스 테이블 목록: {tables}")
        
        if 'extracted_data' in tables:
            print("ExtractedData 테이블 구조:")
            for column in inspector.get_columns('extracted_data'):
                print(f"  - {column['name']}: {column['type']}")
    except Exception as e:
        import traceback
        print(f"데이터베이스 초기화 오류: {str(e)}")
        print(traceback.format_exc())

@app.route('/db_extractions')
def db_extractions():
    try:
        print("데이터베이스 목록 조회 시작")
        
        # 모든 추출 데이터 조회
        all_data = ExtractedData.query.order_by(ExtractedData.extracted_at.desc()).all()
        
        print(f"조회된 데이터 수: {len(all_data)}")
        
        if not all_data:
            print("조회된 데이터 없음")
            return '''
            <h1>저장된 추출 데이터</h1>
            <p>아직 데이터베이스에 저장된 추출 데이터가 없습니다.</p>
            <p><a href='/'>메인 페이지로 돌아가기</a></p>
            '''
        
        # 데이터 테이블 생성
        table_rows = ""
        for data in all_data:
            print(f"데이터 ID: {data.id}, PDF: {data.pdf_name}, 타입: {data.section_type}, 페이지: {data.pages}")
            
            # 페이지 목록을 쉼표로 구분된 문자열에서 리스트로 변환
            pages = data.pages.split(',')
            pages_str = ', '.join(pages)
            
            # ISO 형식의 날짜/시간을 읽기 쉬운 형식으로 변환
            date_str = data.extracted_at.strftime('%Y-%m-%d %H:%M:%S')
            
            # 테이블 행 생성
            table_rows += f'''
            <tr>
                <td>{data.id}</td>
                <td>{data.pdf_name}</td>
                <td>{data.section_type}</td>
                <td>{pages_str}</td>
                <td>{date_str}</td>
                <td>
                    <a href="/show_extraction/{data.id}" class="btn btn-view">보기</a>
                    <a href="/delete_extraction/{data.id}" class="btn btn-delete">삭제</a>
                </td>
            </tr>
            '''
        
        print("HTML 테이블 생성 완료")
        
        return f'''
        <!doctype html>
        <html>
        <head>
            <title>저장된 추출 데이터</title>
            <style>
                table {{
                    border-collapse: collapse;
                    width: 100%;
                }}
                th, td {{
                    border: 1px solid #ddd;
                    padding: 8px;
                    text-align: left;
                }}
                th {{
                    background-color: #f2f2f2;
                }}
                tr:nth-child(even) {{
                    background-color: #f9f9f9;
                }}
                .btn {{
                    display: inline-block;
                    padding: 4px 8px;
                    text-decoration: none;
                    border-radius: 3px;
                    margin-right: 5px;
                    color: white;
                }}
                .btn-view {{
                    background-color: #2196F3;
                }}
                .btn-delete {{
                    background-color: #f44336;
                }}
            </style>
        </head>
        <body>
            <h1>저장된 추출 데이터</h1>
            <table>
                <tr>
                    <th>ID</th>
                    <th>PDF 파일명</th>
                    <th>섹션 유형</th>
                    <th>추출된 페이지</th>
                    <th>추출 날짜/시간</th>
                    <th>작업</th>
                </tr>
                {table_rows}
            </table>
            <p><a href='/'>메인 페이지로 돌아가기</a></p>
        </body>
        </html>
        '''
    except Exception as e:
        import traceback
        print(f"데이터베이스 조회 오류: {str(e)}")
        print(traceback.format_exc())
        return f'''
        <h1>오류 발생</h1>
        <p>데이터베이스 조회 중 오류가 발생했습니다: {str(e)}</p>
        <p><a href='/'>메인 페이지로 돌아가기</a></p>
        '''

@app.route('/show_extraction/<int:extraction_id>')
def show_extraction(extraction_id):
    try:
        # ID로 특정 추출 데이터 조회
        data = ExtractedData.query.get_or_404(extraction_id)
        
        # 페이지 목록을 쉼표로 구분된 문자열에서 리스트로 변환
        pages = data.pages.split(',')
        
        return f'''
        <!doctype html>
        <html>
        <head>
            <title>추출 데이터 상세 정보</title>
            <style>
                .container {{
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .info-box {{
                    border: 1px solid #ddd;
                    padding: 15px;
                    margin-bottom: 20px;
                    background-color: #f9f9f9;
                }}
                .page-list {{
                    display: flex;
                    flex-wrap: wrap;
                    gap: 5px;
                }}
                .page-item {{
                    background-color: #e9e9e9;
                    padding: 5px 10px;
                    border-radius: 3px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>추출 데이터 상세 정보</h1>
                <div class="info-box">
                    <h2>기본 정보</h2>
                    <p><strong>ID:</strong> {data.id}</p>
                    <p><strong>PDF 파일명:</strong> {data.pdf_name}</p>
                    <p><strong>섹션 유형:</strong> {data.section_type}</p>
                    <p><strong>추출 날짜/시간:</strong> {data.extracted_at.strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
                
                <div class="info-box">
                    <h2>추출된 페이지 목록</h2>
                    <div class="page-list">
                        {' '.join([f'<span class="page-item">페이지 {page}</span>' for page in pages])}
                    </div>
                </div>
                
                <p><a href="/db_extractions">목록으로 돌아가기</a></p>
                <p><a href="/">메인 페이지로 돌아가기</a></p>
            </div>
        </body>
        </html>
        '''
    except Exception as e:
        return f'''
        <h1>오류 발생</h1>
        <p>데이터 조회 중 오류가 발생했습니다: {str(e)}</p>
        <p><a href='/db_extractions'>목록으로 돌아가기</a></p>
        <p><a href='/'>메인 페이지로 돌아가기</a></p>
        '''

@app.route('/delete_extraction/<int:extraction_id>', methods=['GET', 'POST'])
def delete_extraction(extraction_id):
    try:
        # ID로 특정 추출 데이터 조회
        data = ExtractedData.query.get_or_404(extraction_id)
        
        if request.method == 'POST':
            # 데이터 삭제
            db.session.delete(data)
            db.session.commit()
            print(f"DB 데이터 삭제 완료 (ID: {extraction_id})")
            
            return redirect(url_for('db_extractions'))
        
        # GET 요청 시 삭제 확인 페이지 표시
        return f'''
        <!doctype html>
        <html>
        <head>
            <title>추출 데이터 삭제 확인</title>
            <style>
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .warning {{
                    background-color: #ffebee;
                    border: 1px solid #f44336;
                    padding: 15px;
                    border-radius: 5px;
                    margin-bottom: 20px;
                }}
                .btn {{
                    display: inline-block;
                    padding: 8px 16px;
                    text-decoration: none;
                    border-radius: 4px;
                    margin-right: 10px;
                }}
                .btn-delete {{
                    background-color: #f44336;
                    color: white;
                    border: none;
                }}
                .btn-cancel {{
                    background-color: #e0e0e0;
                    color: #333;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>추출 데이터 삭제 확인</h1>
                <div class="warning">
                    <h3>다음 데이터를 정말 삭제하시겠습니까?</h3>
                    <p><strong>ID:</strong> {data.id}</p>
                    <p><strong>PDF 파일명:</strong> {data.pdf_name}</p>
                    <p><strong>섹션 유형:</strong> {data.section_type}</p>
                    <p>이 작업은 되돌릴 수 없습니다.</p>
                </div>
                
                <form method="post">
                    <button type="submit" class="btn btn-delete">삭제</button>
                    <a href="/db_extractions" class="btn btn-cancel">취소</a>
                </form>
            </div>
        </body>
        </html>
        '''
    except Exception as e:
        import traceback
        print(f"데이터 삭제 중 오류 발생: {str(e)}")
        print(traceback.format_exc())
        return f'''
        <h1>오류 발생</h1>
        <p>데이터 삭제 중 오류가 발생했습니다: {str(e)}</p>
        <p><a href='/db_extractions'>목록으로 돌아가기</a></p>
        <p><a href='/'>메인 페이지로 돌아가기</a></p>
        '''

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
