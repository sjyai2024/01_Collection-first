# 01 Brand Text Collector v2.8 — Collection-first

## 왜 v2.8인가
v2.7은 한 브랜드씩 수집한 직후 연구자 검토를 수행하는 흐름이었다.
본연구에서는 68개 후보의 실제 수집 가능성과 텍스트 분포를 먼저 확인하기 위해
**배치 원자료 수집 → 수집 진단 → 규칙 수정 → 연구자 검토** 순으로 변경한다.

## 주요 기능
1. `Brand, Seed_URL` CSV 배치 업로드
2. 8~12개 단위 권장 배치 크롤링
3. 연구자가 준 Brand명을 우선 사용하여 자동 브랜드명 오인식 방지
4. `OK / LOW_TEXT / ROBOTS_BLOCKED / ERROR` 상태 저장
5. 원자료 페이지와 오류 로그를 먼저 다운로드
6. 이전 raw CSV를 다시 불러와 수집을 이어갈 수 있음
7. 수집 후 페이지/Content Unit 검토 가능

## 기본 사용
1. `01_brand_seed_68.csv`를 열어 `Needs_URL_Verification` 브랜드 URL을 확인/입력
2. Streamlit에 seed CSV 업로드
3. 배치 크기 8~12 권장
4. 각 배치가 끝날 때 `raw pages CSV`와 `crawl status CSV` 저장
5. 모든 브랜드 수집 후 수집률/텍스트량 진단
6. 그 다음 자동 포함 규칙과 Unit 필터를 조정
7. 최종 승인 Unit만 02 분석에 투입

## 주의
- robots.txt를 존중한다.
- requests/BeautifulSoup 기반이므로 JavaScript 렌더링 페이지는 LOW_TEXT/ERROR가 날 수 있다.
- 그런 사이트는 실패로 삭제하지 말고 로그를 보존한 뒤 별도 수집법을 결정한다.
- 68개를 한 번에 실행하지 않는다. Streamlit timeout/사이트 rate limit을 피하기 위해 분할 실행한다.
- `URL_Status`가 `Identity_Verification_Required`인 브랜드는 출처 정체성 확인 전 분석에 넣지 않는다.

## 파일
- `app.py`
- `requirements.txt`
- `01_brand_seed_68.csv`
- `01_brand_seed_template.csv`
