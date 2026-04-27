"""
기존 티스토리 포스트에 쿠팡 파트너스 링크 자동 삽입
사용법:
  python insert_coupang.py --test 3   (3개 테스트)
  python insert_coupang.py --all      (전체 처리)
사전 준비: .env 파일에 KAKAO_EMAIL, KAKAO_PASSWORD 설정
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import argparse
import json
import os
import time
import urllib.parse
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv(dotenv_path=".env")

# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────
KAKAO_EMAIL    = os.environ["KAKAO_EMAIL"]
KAKAO_PASSWORD = os.environ["KAKAO_PASSWORD"]
BLOG_NAME      = "zzun"                        # 관리자 URL: zzun.tistory.com
BLOG_DOMAIN    = "zzun.net"                    # 공개 도메인 (커스텀)
COUPANG_ID     = "AF5718399"
PROCESSED_FILE = "processed_posts.json"

BLOG_CATEGORIES = [
    "IT/개발", "IT/보안", "IT/면접",
    "일상", "여러가지/경제", "여행",
    "리뷰/잡화", "리뷰/놀이시설", "리뷰/영화", "리뷰/장난감", "사진",
]

# 카테고리별 쿠팡 상품 (각 3개)
COUPANG_PRODUCTS = {
    "IT/개발": [
        {"name": "무선 기계식 키보드",    "query": "무선 기계식 키보드"},
        {"name": "모니터암 듀얼",         "query": "모니터암 듀얼 스탠드"},
        {"name": "USB-C 멀티허브",        "query": "USB C타입 허브 멀티포트"},
    ],
    "IT/보안": [
        {"name": "보안 암호화 USB",       "query": "보안 암호화 USB 드라이브"},
        {"name": "웹캠 프라이버시 커버",  "query": "웹캠 슬라이드 커버"},
        {"name": "ipTIME 와이파이6 공유기","query": "iptime 공유기 와이파이6"},
    ],
    "IT/면접": [
        {"name": "코딩 인터뷰 완전분석",  "query": "코딩 인터뷰 완전분석 책"},
        {"name": "노트북 거치대 (접이식)","query": "노트북 거치대 접이식 알루미늄"},
        {"name": "화이트보드 마커세트",   "query": "화이트보드 마커 세트"},
    ],
    "일상": [
        {"name": "스탠리 보온 텀블러",    "query": "스탠리 텀블러 보온 보냉"},
        {"name": "무선 블루투스 이어폰",  "query": "무선 이어폰 블루투스 노이즈캔슬링"},
        {"name": "각도조절 독서대",       "query": "독서대 책상 각도조절"},
    ],
    "여러가지/경제": [
        {"name": "재테크 베스트셀러 책",  "query": "재테크 투자 책 베스트셀러"},
        {"name": "가계부 다이어리",       "query": "가계부 다이어리 2025"},
        {"name": "크레마 전자책 리더기",  "query": "크레마 카르타 전자책 리더기"},
    ],
    "여행": [
        {"name": "경량 여행용 캐리어",    "query": "여행 캐리어 20인치 경량"},
        {"name": "여행 파우치 세트",      "query": "여행 파우치 세트 방수"},
        {"name": "항공기 목베개",         "query": "여행 목베개 비행기 쿠션"},
    ],
    "리뷰/잡화": [
        {"name": "대용량 보조배터리",     "query": "보조배터리 대용량 20000mAh"},
        {"name": "에어팟 프로 케이스",    "query": "에어팟 프로 케이스"},
        {"name": "차량용 무선충전 거치대","query": "차량용 핸드폰 거치대 무선충전"},
    ],
    "리뷰/놀이시설": [
        {"name": "방수 피크닉 돗자리",    "query": "피크닉 돗자리 방수 대형"},
        {"name": "경량 캠핑 의자",        "query": "캠핑 의자 경량 접이식"},
        {"name": "선크림 SPF50+",         "query": "선크림 자외선차단 SPF50 PA"},
    ],
    "리뷰/영화": [
        {"name": "블루투스 홈시어터",     "query": "홈시어터 블루투스 스피커 사운드바"},
        {"name": "미니 빔프로젝터",       "query": "미니 빔프로젝터 가정용 휴대용"},
        {"name": "팝콘 메이커",           "query": "팝콘 기계 가정용 에어팝"},
    ],
    "리뷰/장난감": [
        {"name": "어른 취미 레고 추천",   "query": "레고 어른 취미 추천 테크닉"},
        {"name": "가족 보드게임",         "query": "보드게임 가족 추천"},
        {"name": "애니메이션 피규어",     "query": "피규어 애니메이션 컬렉션"},
    ],
    "사진": [
        {"name": "경량 카메라 삼각대",    "query": "카메라 삼각대 경량 여행"},
        {"name": "카메라 백팩",           "query": "카메라 가방 백팩 방수"},
        {"name": "ND 렌즈 필터",          "query": "카메라 렌즈 ND 필터 세트"},
    ],
}

DEFAULT_PRODUCTS = COUPANG_PRODUCTS["IT/개발"]

# 제목 키워드 → 카테고리 매핑
KEYWORD_CATEGORY_MAP = {
    "IT/개발":          ["파이썬", "python", "자바", "java", "개발", "코딩", "api", "서버",
                        "도커", "docker", "깃", "git", "프로그래밍", "배포", "llm", "ai", "크롤링"],
    "IT/보안":          ["보안", "해킹", "암호화", "vpn", "취약점", "방화벽"],
    "IT/면접":          ["면접", "취업", "이력서", "알고리즘", "코딩테스트"],
    "여행":             ["여행", "해외", "국내여행", "숙박", "호텔", "항공", "맛집"],
    "리뷰/영화":        ["영화", "드라마", "ott", "넷플릭스", "디즈니", "왓챠"],
    "리뷰/장난감":      ["레고", "피규어", "보드게임", "장난감", "프라모델"],
    "여러가지/경제":    ["재테크", "주식", "투자", "부동산", "경제", "청약", "절세", "연말정산"],
    "사진":             ["사진", "카메라", "촬영", "렌즈", "필름"],
    "리뷰/잡화":        ["리뷰", "추천", "가성비", "구매후기", "언박싱"],
    "리뷰/놀이시설":    ["놀이공원", "테마파크", "전시회", "아쿠아리움", "키즈카페"],
    "일상":             ["일상", "루틴", "생산성", "독서", "카페", "취미"],
}


# ─────────────────────────────────────────
# processed_posts.json 관리
# ─────────────────────────────────────────
def load_processed() -> dict:
    if os.path.exists(PROCESSED_FILE):
        try:
            return json.loads(Path(PROCESSED_FILE).read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_processed(data: dict):
    Path(PROCESSED_FILE).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# ─────────────────────────────────────────
# 카카오 로그인 (auto_post.py 동일 패턴)
# ─────────────────────────────────────────
def _login(page, email: str, password: str):
    print("  카카오 로그인 중...")
    page.goto(f"https://{BLOG_NAME}.tistory.com/manage")
    page.wait_for_load_state("networkidle")
    page.click(".link_kakao_id")
    page.wait_for_url("**/accounts.kakao.com/**", timeout=15000)
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    for sel in ["#loginId--1", "input[name='loginId']"]:
        try:
            page.wait_for_selector(sel, timeout=3000)
            page.click(sel)
            page.type(sel, email, delay=50)
            break
        except Exception:
            continue

    for sel in ["#password--2", "input[name='password']", "input[type='password']"]:
        try:
            page.wait_for_selector(sel, timeout=3000)
            page.click(sel)
            page.type(sel, password, delay=50)
            break
        except Exception:
            continue

    page.click('button[type="submit"]')
    page.wait_for_url(
        lambda url: "tistory.com" in url and "kakao.com" not in url,
        timeout=60000
    )
    page.wait_for_load_state("networkidle", timeout=20000)
    print("  로그인 완료 —", page.url)


# ─────────────────────────────────────────
# 글 목록 수집 (/manage/posts)
# 실제 DOM 구조:
#   input[id^="inpCheck{ID}"]  → 포스트 ID
#   a.link_cont[title]         → 제목
#   .txt_cate                  → 카테고리
#   .wrap_paging a.link_num    → 페이지네이션
# ─────────────────────────────────────────
def collect_posts(page, max_pages: int = 100) -> list[dict]:
    """관리자 글 목록에서 post ID, 제목, 카테고리를 수집합니다."""
    posts = []

    for page_num in range(1, max_pages + 1):
        url = (
            f"https://{BLOG_NAME}.tistory.com/manage/posts"
            f"?category=-3&page={page_num}&searchKeyword=&searchType=title&visibility=all"
        )
        print(f"  글 목록: page {page_num}")
        page.goto(url)
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        items = page.evaluate("""
            () => {
                const inputs = document.querySelectorAll('input[id^="inpCheck"]');
                return Array.from(inputs).map(el => {
                    const postId  = el.id.replace('inpCheck', '');
                    const li      = el.closest('li');
                    const titleEl = li ? li.querySelector('a.link_cont') : null;
                    const catEl   = li ? li.querySelector('.txt_cate') : null;
                    return {
                        id:       postId,
                        title:    titleEl ? (titleEl.getAttribute('title') || titleEl.innerText.trim()) : '',
                        category: catEl   ? catEl.innerText.trim() : ''
                    };
                }).filter(item => item.id && item.title);
            }
        """)

        if not items:
            print(f"  page {page_num}: 글 없음 → 종료")
            break

        print(f"  page {page_num}: {len(items)}개 수집")
        posts.extend(items)

        # 다음 페이지 존재 여부: .wrap_paging 내 현재+1 페이지 링크 확인
        has_next = page.evaluate(f"""
            () => {{
                const links = document.querySelectorAll('.wrap_paging a.link_num');
                return Array.from(links).some(a => {{
                    const m = a.href.match(/page=(\\d+)/);
                    return m && parseInt(m[1]) === {page_num + 1};
                }});
            }}
        """)
        if not has_next:
            print(f"  마지막 페이지 도달 (page {page_num})")
            break

    # ID 기준 중복 제거
    seen, unique = set(), []
    for post in posts:
        if post["id"] not in seen:
            seen.add(post["id"])
            unique.append(post)

    print(f"  총 {len(unique)}개 글 수집 완료")
    return unique


# ─────────────────────────────────────────
# 카테고리/제목 기반 상품 매핑
# ─────────────────────────────────────────
def get_products_for_post(category: str, title: str) -> list[dict]:
    # 1. 정확한 카테고리 매칭
    if category in COUPANG_PRODUCTS:
        return COUPANG_PRODUCTS[category]

    # 2. 부분 카테고리 매칭
    for cat_key in COUPANG_PRODUCTS:
        if cat_key.lower() in category.lower() or category.lower() in cat_key.lower():
            return COUPANG_PRODUCTS[cat_key]

    # 3. 제목 키워드로 카테고리 추론
    title_lower = title.lower()
    for cat_key, keywords in KEYWORD_CATEGORY_MAP.items():
        if any(kw in title_lower for kw in keywords):
            return COUPANG_PRODUCTS.get(cat_key, DEFAULT_PRODUCTS)

    return DEFAULT_PRODUCTS


# ─────────────────────────────────────────
# 쿠팡 파트너스 HTML 생성
# ─────────────────────────────────────────
def build_coupang_html(products: list[dict]) -> str:
    items_html = ""
    for product in products[:3]:
        # 검색어 인코딩 (한글/공백만 인코딩, %는 safe로 두어 이중인코딩 방지)
        q = urllib.parse.quote(product["query"])          # 한글·공백 → %XX
        inner_url = f"https://www.coupang.com/np/search?q={q}"
        # url= 파라미터: 구조 문자(?=:/)도 인코딩하되 이미 인코딩된 %XX는 재인코딩하지 않음
        link_url = (
            f"https://link.coupang.com/a/{COUPANG_ID}"
            f"?url={urllib.parse.quote(inner_url, safe='%')}"
        )
        items_html += (
            f"<li style='margin:8px 0;'>"
            f"<a href='{link_url}' target='_blank' rel='noopener sponsored' "
            f"style='color:#e85c0d;text-decoration:none;font-weight:bold;'>"
            f"&#128722; {product['name']}"
            f"</a>"
            f"<span style='font-size:12px;color:#999;'> &mdash; 쿠팡에서 확인하기</span>"
            f"</li>"
        )

    disclaimer = (
        "이 포스팅은 쿠팡 파트너스 활동의 일환으로, "
        "이에 따른 일정액의 수수료를 제공받습니다."
    )

    return (
        "<div style='margin:40px 0 20px;padding:20px 24px;"
        "border-left:5px solid #e85c0d;background:#fff8f5;"
        "border-radius:4px;'>"
        "<h4 style='margin:0 0 12px;color:#e85c0d;font-size:16px;'>&#128722; 관련 상품</h4>"
        f"<ul style='margin:0;padding:0 0 0 4px;list-style:none;'>{items_html}</ul>"
        f"<p style='margin:14px 0 0;font-size:11px;color:#bbb;'>{disclaimer}</p>"
        "</div>"
    )


# ─────────────────────────────────────────
# 단일 포스트 처리
# ─────────────────────────────────────────
def process_post(page, post: dict) -> str:
    """
    단일 포스트에 쿠팡 링크를 삽입하고 발행합니다.
    반환값: 'done' | 'skipped:<reason>' | 'failed:<reason>'
    """
    post_id  = post["id"]
    title    = post["title"]
    category = post.get("category", "")

    # 수정 페이지: /manage/post/{id}  (auto_post.py의 newpost/ 는 새 글용)
    edit_url = f"https://{BLOG_NAME}.tistory.com/manage/post/{post_id}"
    print(f"    수정 페이지: {edit_url}")
    page.goto(edit_url)
    page.wait_for_load_state("networkidle")
    time.sleep(3)

    # TinyMCE 로드 대기 (auto_post.py 동일 패턴)
    try:
        page.wait_for_function(
            "() => typeof tinymce !== 'undefined' && tinymce.editors.length > 0",
            timeout=15000
        )
    except Exception as e:
        print(f"    TinyMCE 로드 실패: {e}")
        return "failed:tinymce_not_loaded"

    # 기존 본문 읽기 + 쿠팡 링크 중복 확인
    check = page.evaluate("""
        () => {
            const editor = tinymce.get(0) || tinymce.editors[0];
            if (!editor) return { ok: false };
            const content = editor.getContent();
            return {
                ok:          true,
                has_coupang: content.includes('link.coupang.com'),
                length:      content.length
            };
        }
    """)

    if not check.get("ok"):
        print(f"    에디터 인스턴스 접근 실패")
        return "failed:editor_not_accessible"

    fix_mode = post.get("_fix", False)

    if check.get("has_coupang") and not fix_mode:
        print(f"    이미 쿠팡 링크 포함 → 스킵")
        return "skipped:already_has_coupang"

    print(f"    기존 본문 {check['length']}자")

    products     = get_products_for_post(category, title)
    coupang_html = build_coupang_html(products)
    print(f"    상품: {[p['name'] for p in products]}")

    # 기존 본문 읽기 후 쿠팡 섹션 추가 (auto_post.py 동일 이스케이프)
    new_content = page.evaluate("""
        () => {
            const editor = tinymce.get(0) || tinymce.editors[0];
            if (!editor) return '';
            let content = editor.getContent();
            // --fix 모드: 기존 쿠팡 div 제거 (link.coupang.com 포함 div)
            const parser = new DOMParser();
            const doc = parser.parseFromString(content, 'text/html');
            doc.querySelectorAll('div').forEach(div => {
                if (div.innerHTML.includes('link.coupang.com')) {
                    div.remove();
                }
            });
            return doc.body.innerHTML;
        }
    """) if fix_mode else page.evaluate("""
        () => {
            const editor = tinymce.get(0) || tinymce.editors[0];
            return editor ? editor.getContent() : '';
        }
    """)

    appended = new_content + coupang_html
    content_escaped = (
        appended
        .replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("$", "\\$")
    )

    result = page.evaluate(f"""
        () => {{
            const editor = tinymce.get(0) || tinymce.editors[0];
            if (!editor) return 'editor not found';
            editor.setContent(`{content_escaped}`);
            editor.save();
            editor.fire('change');
            editor.fire('input');
            return 'ok: ' + editor.getContent().length + ' chars';
        }}
    """)
    print(f"    에디터: {result}")

    if "editor not found" in str(result):
        return "failed:editor_set_failed"

    time.sleep(1)

    # 발행 패널 열기 ("완료" 버튼) — auto_post.py 동일
    print(f"    발행 패널 열기...")
    page.click("button:has-text('완료')")
    time.sleep(3)

    # 공개 발행 버튼 — auto_post.py 동일
    btn_texts = [b.inner_text().strip() for b in page.locator("button").all()]
    print(f"    버튼 목록: {[t for t in btn_texts if t and len(t) < 20]}")

    published = False
    for keyword in ["공개 발행", "발행", "공개 저장"]:
        candidates = page.locator(f"button:has-text('{keyword}')").all()
        visible    = [b for b in candidates if "비공개" not in b.inner_text()]
        if visible:
            print(f"    '{keyword}' 클릭")
            visible[0].click()
            time.sleep(3)
            published = True
            break

    if not published:
        print(f"    발행 버튼 없음!")
        return "failed:publish_button_not_found"

    # 발행 완료 대기 (auto_post.py 동일)
    try:
        page.wait_for_url(lambda url: "manage/post/" not in url, timeout=10000)
    except Exception:
        pass
    page.wait_for_load_state("networkidle", timeout=10000)
    print(f"    완료! URL: {page.url}")
    return "done"


# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="티스토리 기존 글에 쿠팡 파트너스 링크 자동 삽입"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--test", type=int, metavar="N", help="N개만 테스트")
    group.add_argument("--all",  action="store_true",   help="전체 글 처리")
    group.add_argument("--fix",  type=int, metavar="N", help="이미 쿠팡 링크가 있는 글 N개를 올바른 URL로 교체")
    args = parser.parse_args()

    print("=" * 55)
    print(f"  쿠팡 파트너스 링크 자동 삽입  ({BLOG_DOMAIN})")
    print(f"  파트너스 ID: {COUPANG_ID}")
    print("=" * 55)

    processed = load_processed()
    print(f"  기존 처리 기록: {len(processed)}개")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()

        # ── Step 1: 로그인 ──────────────────────────
        print("\n🔐 Step 1: 로그인")
        _login(page, KAKAO_EMAIL, KAKAO_PASSWORD)

        # ── Step 2: 글 목록 수집 ────────────────────
        print("\n📋 Step 2: 글 목록 수집")
        max_pages = 2 if (args.test or args.fix) else 100
        all_posts = collect_posts(page, max_pages=max_pages)

        if not all_posts:
            print("  수집된 글 없음, 종료")
            browser.close()
            return

        if args.fix:
            # --fix: 이미 쿠팡 링크가 있는 글만 대상, _fix 플래그 설정
            todo_posts = all_posts[: args.fix]
            for p in todo_posts:
                p["_fix"] = True
            print(f"\n  [수정 모드] {len(todo_posts)}개 쿠팡 링크 교체")
        else:
            # 이미 완료된 글 제외
            DONE_STATUSES = {"done", "skipped:already_has_coupang"}
            todo_posts = [
                post for post in all_posts
                if post["id"] not in processed
                or processed[post["id"]].get("status") not in DONE_STATUSES
            ]
            if args.test:
                todo_posts = todo_posts[: args.test]
                print(f"\n  [테스트 모드] {len(todo_posts)}개 처리")
            else:
                print(
                    f"\n  [전체 모드] {len(todo_posts)}개 처리 "
                    f"(전체 {len(all_posts)}개 중 미처리)"
                )

        if not todo_posts:
            print("  처리할 글이 없습니다.")
            browser.close()
            return

        # ── Step 3: 쿠팡 링크 삽입 ─────────────────
        print(f"\n🛒 Step 3: 쿠팡 링크 삽입")
        counts = {"done": 0, "skipped": 0, "failed": 0}

        for i, post in enumerate(todo_posts, 1):
            post_id  = post["id"]
            title    = post["title"]
            category = post.get("category", "")
            print(f"\n  [{i}/{len(todo_posts)}] ID:{post_id} [{category}] {title}")

            # 처리 시작 기록 (크래시 대비)
            processed[post_id] = {
                "title":    title,
                "category": category,
                "status":   "processing",
            }
            save_processed(processed)

            status = process_post(page, post)

            # 결과 기록
            if status == "done":
                processed[post_id].update({"status": "done", "url": page.url})
                counts["done"] += 1
            elif status.startswith("skipped"):
                processed[post_id]["status"] = status
                counts["skipped"] += 1
            else:
                processed[post_id]["status"] = status
                counts["failed"] += 1

            save_processed(processed)

            if i < len(todo_posts):
                print(f"    3초 대기...")
                time.sleep(3)

        browser.close()

    # ── 결과 요약 ────────────────────────────────
    print(f"\n{'='*55}")
    print("  처리 결과 요약")
    print(f"{'='*55}")
    print(f"  ✅ 성공:  {counts['done']}개")
    print(f"  ⏭️  스킵:  {counts['skipped']}개")
    print(f"  ❌ 실패:  {counts['failed']}개")
    print(f"  기록 파일: {PROCESSED_FILE}")


if __name__ == "__main__":
    main()
