"""
쿠팡 파트너스 단축 링크 생성기
방법1: partners.coupang.com 로그인 → 바로가기 링크 API로 단축 URL 생성 (수수료 추적 가능)
방법2: 쿠팡 검색 URL 직접 사용 (fallback, 수수료 추적 불가)
결과: coupang_links.json 저장

사용법:
  python gen_coupang_links.py           # 생성 (기존 캐시 유지)
  python gen_coupang_links.py --force   # 전체 재생성
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

COUPANG_EMAIL    = os.environ["COUPANG_EMAIL"]
COUPANG_PASSWORD = os.environ["COUPANG_PASSWORD"]
COUPANG_ID       = "AF5718399"
LINKS_FILE       = "coupang_links.json"

# ─────────────────────────────────────────
# 링크 생성 대상 상품 (카테고리별 3개, 총 33개)
# ─────────────────────────────────────────
PRODUCTS = [
    # IT/개발
    {"name": "무선 기계식 키보드",      "query": "무선 기계식 키보드",             "category": "IT/개발"},
    {"name": "모니터암 듀얼",           "query": "모니터암 듀얼 스탠드",            "category": "IT/개발"},
    {"name": "USB-C 멀티허브",          "query": "USB C타입 허브 멀티포트",         "category": "IT/개발"},
    # IT/보안
    {"name": "보안 암호화 USB",         "query": "보안 암호화 USB 드라이브",        "category": "IT/보안"},
    {"name": "웹캠 프라이버시 커버",    "query": "웹캠 슬라이드 커버",              "category": "IT/보안"},
    {"name": "ipTIME 와이파이6",        "query": "iptime 공유기 와이파이6",          "category": "IT/보안"},
    # IT/면접
    {"name": "코딩 인터뷰 완전분석",    "query": "코딩 인터뷰 완전분석 책",         "category": "IT/면접"},
    {"name": "노트북 거치대",           "query": "노트북 거치대 접이식 알루미늄",    "category": "IT/면접"},
    {"name": "화이트보드 마커세트",     "query": "화이트보드 마커 세트",             "category": "IT/면접"},
    # 일상
    {"name": "스탠리 보온 텀블러",      "query": "스탠리 텀블러 보온 보냉",          "category": "일상"},
    {"name": "무선 블루투스 이어폰",    "query": "무선 이어폰 블루투스 노이즈캔슬링","category": "일상"},
    {"name": "각도조절 독서대",         "query": "독서대 책상 각도조절",             "category": "일상"},
    # 여러가지/경제
    {"name": "재테크 베스트셀러 책",    "query": "재테크 투자 책 베스트셀러",        "category": "여러가지/경제"},
    {"name": "가계부 다이어리",         "query": "가계부 다이어리 2025",             "category": "여러가지/경제"},
    {"name": "전자책 리더기",           "query": "크레마 카르타 전자책 리더기",      "category": "여러가지/경제"},
    # 여행
    {"name": "경량 여행용 캐리어",      "query": "여행 캐리어 20인치 경량",          "category": "여행"},
    {"name": "여행 파우치 세트",        "query": "여행 파우치 세트 방수",            "category": "여행"},
    {"name": "항공기 목베개",           "query": "여행 목베개 비행기 쿠션",          "category": "여행"},
    # 리뷰/잡화
    {"name": "대용량 보조배터리",       "query": "보조배터리 대용량 20000mAh",       "category": "리뷰/잡화"},
    {"name": "에어팟 프로 케이스",      "query": "에어팟 프로 케이스",               "category": "리뷰/잡화"},
    {"name": "차량용 무선충전 거치대",  "query": "차량용 핸드폰 거치대 무선충전",    "category": "리뷰/잡화"},
    # 리뷰/놀이시설
    {"name": "방수 피크닉 돗자리",      "query": "피크닉 돗자리 방수 대형",          "category": "리뷰/놀이시설"},
    {"name": "경량 캠핑 의자",          "query": "캠핑 의자 경량 접이식",            "category": "리뷰/놀이시설"},
    {"name": "선크림 SPF50+",           "query": "선크림 자외선차단 SPF50 PA",       "category": "리뷰/놀이시설"},
    # 리뷰/영화
    {"name": "블루투스 홈시어터",       "query": "홈시어터 블루투스 스피커 사운드바","category": "리뷰/영화"},
    {"name": "미니 빔프로젝터",         "query": "미니 빔프로젝터 가정용 휴대용",    "category": "리뷰/영화"},
    {"name": "팝콘 메이커",             "query": "팝콘 기계 가정용 에어팝",          "category": "리뷰/영화"},
    # 리뷰/장난감
    {"name": "어른 취미 레고",          "query": "레고 어른 취미 추천 테크닉",       "category": "리뷰/장난감"},
    {"name": "가족 보드게임",           "query": "보드게임 가족 추천",               "category": "리뷰/장난감"},
    {"name": "애니메이션 피규어",       "query": "피규어 애니메이션 컬렉션",         "category": "리뷰/장난감"},
    # 사진
    {"name": "경량 카메라 삼각대",      "query": "카메라 삼각대 경량 여행",          "category": "사진"},
    {"name": "카메라 백팩",             "query": "카메라 가방 백팩 방수",            "category": "사진"},
    {"name": "ND 렌즈 필터",            "query": "카메라 렌즈 ND 필터 세트",         "category": "사진"},
]


# ─────────────────────────────────────────
# 링크 캐시 파일 관리
# ─────────────────────────────────────────
def load_links() -> dict:
    if os.path.exists(LINKS_FILE):
        try:
            return json.loads(Path(LINKS_FILE).read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_links(data: dict):
    Path(LINKS_FILE).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# ─────────────────────────────────────────
# 방법2 fallback: 쿠팡 검색 URL 직접 생성
# ─────────────────────────────────────────
def _fallback_url(query: str) -> str:
    """수수료 추적 없이 쿠팡 검색 결과로 직접 연결 (fallback 전용)."""
    q = urllib.parse.quote(query)
    return f"https://www.coupang.com/np/search?q={q}&channel=user&subChannel=user"


# ─────────────────────────────────────────
# 방법1-A: 파트너스 내부 API 호출
# ─────────────────────────────────────────
def _generate_via_api(page, search_url: str) -> str | None:
    """페이지 세션 쿠키를 이용해 파트너스 API에 단축 URL 생성 요청."""
    # 쿠팡 파트너스 단축 URL API 엔드포인트 목록 (우선순위 순)
    api_calls = [
        # 바로가기 링크 생성 API (파트너스 대시보드 내부 사용)
        {
            "url": "https://partners.coupang.com/api/v1/shortUrl",
            "body": {"url": search_url},
            "field": ["shortUrl", "url", "data"],
        },
        {
            "url": "https://partners.coupang.com/api/v1/links/shorten",
            "body": {"originalUrl": search_url},
            "field": ["shortUrl", "url", "shortenUrl"],
        },
        {
            "url": "https://partners.coupang.com/api/v1/banner/shortUrl",
            "body": {"url": search_url, "type": "search"},
            "field": ["shortUrl", "url"],
        },
    ]

    for api in api_calls:
        try:
            result = page.evaluate("""
                async (apiUrl, body) => {
                    try {
                        const resp = await fetch(apiUrl, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'Accept': 'application/json',
                            },
                            credentials: 'include',
                            body: JSON.stringify(body)
                        });
                        if (!resp.ok) return null;
                        const data = await resp.json();
                        return JSON.stringify(data);
                    } catch(e) {
                        return null;
                    }
                }
            """, api["url"], api["body"])

            if result:
                data = json.loads(result)
                # 응답에서 단축 URL 추출
                for field in api["field"]:
                    if isinstance(data, dict):
                        val = data.get(field)
                        if isinstance(val, dict):
                            val = val.get("url") or val.get("shortUrl")
                        if val and "link.coupang.com" in str(val):
                            return val
                    elif isinstance(data, list) and data:
                        val = data[0].get(field)
                        if val and "link.coupang.com" in str(val):
                            return val
        except Exception as e:
            continue

    return None


# ─────────────────────────────────────────
# 방법1-B: 파트너스 UI에서 바로가기 링크 생성
# ─────────────────────────────────────────
def _generate_via_ui(page, search_url: str) -> str | None:
    """파트너스 대시보드 UI에서 바로가기 링크를 생성합니다."""
    # 파트너스 바로가기 링크 페이지 URL 후보
    ui_pages = [
        "https://partners.coupang.com/#/bannerLink",
        "https://partners.coupang.com/#/shortUrl",
        "https://partners.coupang.com/bannerLink",
    ]

    for ui_url in ui_pages:
        try:
            page.goto(ui_url, timeout=15000)
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            # URL 입력 필드 찾기
            input_sels = [
                "input[placeholder*='URL']",
                "input[placeholder*='링크']",
                "input[placeholder*='주소']",
                "input[placeholder*='url' i]",
                "textarea[placeholder*='URL']",
                ".url-input input",
                "input[type='url']",
            ]
            input_el = None
            for sel in input_sels:
                try:
                    el = page.wait_for_selector(sel, timeout=3000)
                    if el and el.is_visible():
                        input_el = sel
                        break
                except:
                    continue

            if not input_el:
                continue

            # URL 입력
            page.fill(input_el, search_url)
            time.sleep(0.5)

            # 생성 버튼 클릭
            btn_sels = [
                "button:has-text('단축 URL 생성')",
                "button:has-text('생성')",
                "button:has-text('만들기')",
                "button:has-text('확인')",
                "button[type='submit']",
                ".btn-create",
            ]
            for btn in btn_sels:
                try:
                    page.click(btn, timeout=3000)
                    time.sleep(2)
                    break
                except:
                    continue

            # 생성된 단축 링크 추출
            short_link = page.evaluate("""
                () => {
                    // link.coupang.com 포함된 input value 또는 a[href] 찾기
                    for (const el of document.querySelectorAll(
                        'input[value*="link.coupang.com"], a[href*="link.coupang.com"]'
                    )) {
                        return el.value || el.href;
                    }
                    // 텍스트에서 정규식으로 추출
                    const m = document.body.innerText.match(
                        /https:\\/\\/link\\.coupang\\.com\\/a\\/[A-Za-z0-9]+/
                    );
                    return m ? m[0] : null;
                }
            """)

            if short_link and "link.coupang.com" in short_link:
                return short_link

        except Exception as e:
            print(f"    UI 오류 ({ui_url}): {e}")
            continue

    return None


# ─────────────────────────────────────────
# 파트너스 로그인
# ─────────────────────────────────────────
def _login_partners(page) -> bool:
    """쿠팡 파트너스 로그인. 성공 시 True."""
    print("  파트너스 사이트 접속 중...")
    try:
        page.goto("https://partners.coupang.com/", timeout=30000)
        page.wait_for_load_state("networkidle")
        time.sleep(3)

        print(f"  접속 URL: {page.url} / 제목: {page.title()[:40]}")

        # Akamai WAF 차단 확인
        if "Access Denied" in page.title() or "Access Denied" in page.evaluate("() => document.body.innerText.slice(0, 100)"):
            print("  Akamai WAF 차단 감지 → 로그인 불가")
            return False

        # 이미 로그인된 경우
        cur_url = page.url
        if "partners.coupang.com" in cur_url and "login" not in cur_url.lower():
            # 대시보드 요소 확인
            for sel in [".gnb-user", ".user-info", "[class*='profile']", "[class*='dashboard']", ".main-content"]:
                try:
                    page.wait_for_selector(sel, timeout=3000)
                    print(f"  이미 로그인됨 (요소: {sel})")
                    return True
                except:
                    continue

        # 로그인 버튼 찾아 클릭
        for sel in ["button:has-text('로그인')", "a:has-text('로그인')", ".login-btn", "[href*='login']"]:
            try:
                page.click(sel, timeout=3000)
                page.wait_for_load_state("networkidle")
                time.sleep(2)
                break
            except:
                continue

        print(f"  로그인 폼 URL: {page.url}")
        time.sleep(3)

        # Akamai WAF 차단 재확인
        if "Access Denied" in page.evaluate("() => document.body.innerText.slice(0, 100)"):
            print("  로그인 페이지 Akamai 차단")
            return False

        # 이메일 입력
        email_filled = False
        for sel in [
            "input[name='email']",
            "input[type='email']",
            "input[name='loginId']",
            "input[id*='email' i]",
            "input[placeholder*='이메일']",
            "input[placeholder*='Email']",
            "input[type='text']:visible",
        ]:
            try:
                el = page.wait_for_selector(sel, timeout=3000)
                if el and el.is_visible():
                    page.fill(sel, COUPANG_EMAIL)
                    print(f"  이메일 입력: {sel}")
                    email_filled = True
                    break
            except:
                continue

        if not email_filled:
            print("  이메일 필드 없음 → 로그인 실패")
            return False

        # 비밀번호 입력
        for sel in ["input[name='password']", "input[type='password']"]:
            try:
                el = page.wait_for_selector(sel, timeout=3000)
                if el and el.is_visible():
                    page.fill(sel, COUPANG_PASSWORD)
                    break
            except:
                continue

        # 제출
        submitted = False
        for sel in ["button[type='submit']", ".btn-login", "button:has-text('로그인')", "input[type='submit']"]:
            try:
                page.click(sel, timeout=3000)
                submitted = True
                break
            except:
                continue
        if not submitted:
            page.keyboard.press("Enter")

        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(4)

        final_url = page.url
        print(f"  로그인 결과 URL: {final_url}")

        success = "partners.coupang.com" in final_url and "login" not in final_url.lower()
        if success:
            print("  로그인 성공")
        else:
            print("  로그인 실패")
        return success

    except Exception as e:
        print(f"  로그인 오류: {e}")
        return False


# ─────────────────────────────────────────
# 단일 상품 링크 생성 (방법1 → 방법2 순서)
# ─────────────────────────────────────────
def _generate_link(page, product: dict, logged_in: bool) -> dict:
    query      = product["query"]
    search_url = f"https://www.coupang.com/np/search?q={urllib.parse.quote(query)}"
    short_link = None
    method     = "fallback"

    if logged_in:
        # 방법1-A: 내부 API
        short_link = _generate_via_api(page, search_url)
        if short_link:
            method = "api"
        else:
            # 방법1-B: UI (API 실패 시)
            short_link = _generate_via_ui(page, search_url)
            if short_link:
                method = "ui"

    if not short_link:
        # 방법2: 직접 URL
        short_link = _fallback_url(query)
        method = "fallback"

    icon = "✅" if method != "fallback" else "⚠️ "
    print(f"  {icon} [{method}] {product['name']}")
    print(f"         {short_link[:80]}")

    return {
        "name":     product["name"],
        "query":    query,
        "category": product["category"],
        "url":      short_link,
        "method":   method,
    }


# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="쿠팡 파트너스 단축 링크 생성기")
    parser.add_argument("--force", action="store_true", help="기존 캐시 무시하고 전체 재생성")
    args = parser.parse_args()

    print("=" * 55)
    print("  쿠팡 파트너스 단축 링크 생성기")
    print(f"  파트너스 ID: {COUPANG_ID}")
    print("=" * 55)

    existing = load_links() if not args.force else {}
    print(f"  기존 캐시: {len(existing)}개 ({'무시' if args.force else '유지'})")

    # 새로 생성할 상품 필터링 (캐시에 없거나 fallback인 것 우선)
    to_generate = [
        p for p in PRODUCTS
        if p["query"] not in existing
        or existing[p["query"]].get("method") == "fallback"  # fallback은 재시도
        or args.force
    ]
    print(f"  생성 대상: {len(to_generate)}개")

    if not to_generate:
        print("  모든 링크가 이미 캐싱됨. --force 로 재생성 가능.")
        return

    with sync_playwright() as p:
        # Firefox 우선 (Akamai WAF 우회 가능성)
        browser = None
        for browser_type, launch_opts in [
            (p.firefox,  {"headless": False}),
            (p.chromium, {"headless": False, "args": ["--disable-blink-features=AutomationControlled"]}),
        ]:
            try:
                browser = browser_type.launch(**launch_opts)
                print(f"  브라우저: {browser_type.name}")
                break
            except Exception as e:
                print(f"  {browser_type.name} 실패: {e}")

        if not browser:
            print("  브라우저 실행 실패")
            return

        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"
            if "firefox" in str(type(browser)).lower()
            else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
        )
        context = browser.new_context(user_agent=ua)
        page    = context.new_page()

        # Step 1: 파트너스 로그인
        print("\n🔐 Step 1: 쿠팡 파트너스 로그인")
        logged_in = _login_partners(page)
        if not logged_in:
            print("  ⚠️  로그인 실패 → 방법2(직접 URL)로 fallback")

        # Step 2: 링크 생성
        print(f"\n🔗 Step 2: 링크 생성 ({len(to_generate)}개)")
        new_links = {}
        for i, product in enumerate(to_generate, 1):
            print(f"\n  [{i}/{len(to_generate)}] {product['name']}")
            result = _generate_link(page, product, logged_in)
            new_links[product["query"]] = result
            time.sleep(1.5)  # API 과부하 방지

        browser.close()

    # 캐시와 병합 저장 (새로 생성한 것 우선)
    merged = {**existing, **new_links}
    save_links(merged)

    # 결과 요약
    by_method: dict[str, int] = {}
    for v in new_links.values():
        m = v["method"]
        by_method[m] = by_method.get(m, 0) + 1

    print(f"\n{'='*55}")
    print("  생성 결과")
    print(f"{'='*55}")
    for method, count in sorted(by_method.items()):
        icon = "✅" if method != "fallback" else "⚠️ "
        print(f"  {icon} {method}: {count}개")
    print(f"  저장: {LINKS_FILE} ({len(merged)}개 총)")

    fallback_count = by_method.get("fallback", 0)
    if fallback_count == len(new_links):
        print(
            "\n  ⚠️  모두 fallback URL입니다.\n"
            "     fallback URL은 파트너스 수수료 추적이 되지 않습니다.\n"
            "     파트너스 로그인 후 재시도하거나, 단축 링크를 수동으로 추가하세요."
        )
    elif fallback_count > 0:
        print(f"\n  ⚠️  {fallback_count}개는 fallback. --force 로 재시도 가능.")


if __name__ == "__main__":
    main()
