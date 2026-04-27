"""
쿠팡 파트너스 단축 링크 생성기 (네트워크 가로채기 방식)

동작 방식:
  1. 브라우저를 열어 partners.coupang.com 접속
  2. 사용자가 직접 로그인 후 Enter
  3. '바로가기 링크' 메뉴로 이동
  4. 스크립트가 URL 자동 입력 & 생성 버튼 클릭
  5. 네트워크 요청을 가로채서 실제 API 엔드포인트 & 응답 형식 파악
  6. 이후 상품들은 파악된 API를 직접 호출하여 단축 링크 생성
  7. 결과를 coupang_links.json에 저장

사용법:
  python gen_coupang_links.py           # 생성 (기존 캐시 유지, fallback 재시도)
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
from playwright.sync_api import sync_playwright, Request, Response

load_dotenv(dotenv_path=".env")

COUPANG_ID = "AF5718399"
LINKS_FILE = "coupang_links.json"

# ─────────────────────────────────────────
# 링크 생성 대상 상품 (카테고리별 3개, 총 33개)
# ─────────────────────────────────────────
PRODUCTS = [
    # IT/개발
    {"name": "무선 기계식 키보드",      "query": "무선 기계식 키보드",              "category": "IT/개발"},
    {"name": "모니터암 듀얼",           "query": "모니터암 듀얼 스탠드",             "category": "IT/개발"},
    {"name": "USB-C 멀티허브",          "query": "USB C타입 허브 멀티포트",          "category": "IT/개발"},
    # IT/보안
    {"name": "보안 암호화 USB",         "query": "보안 암호화 USB 드라이브",         "category": "IT/보안"},
    {"name": "웹캠 프라이버시 커버",    "query": "웹캠 슬라이드 커버",               "category": "IT/보안"},
    {"name": "ipTIME 와이파이6",        "query": "iptime 공유기 와이파이6",           "category": "IT/보안"},
    # IT/면접
    {"name": "코딩 인터뷰 완전분석",    "query": "코딩 인터뷰 완전분석 책",          "category": "IT/면접"},
    {"name": "노트북 거치대",           "query": "노트북 거치대 접이식 알루미늄",     "category": "IT/면접"},
    {"name": "화이트보드 마커세트",     "query": "화이트보드 마커 세트",              "category": "IT/면접"},
    # 일상
    {"name": "스탠리 보온 텀블러",      "query": "스탠리 텀블러 보온 보냉",           "category": "일상"},
    {"name": "무선 블루투스 이어폰",    "query": "무선 이어폰 블루투스 노이즈캔슬링", "category": "일상"},
    {"name": "각도조절 독서대",         "query": "독서대 책상 각도조절",              "category": "일상"},
    # 여러가지/경제
    {"name": "재테크 베스트셀러 책",    "query": "재테크 투자 책 베스트셀러",         "category": "여러가지/경제"},
    {"name": "가계부 다이어리",         "query": "가계부 다이어리 2025",              "category": "여러가지/경제"},
    {"name": "전자책 리더기",           "query": "크레마 카르타 전자책 리더기",       "category": "여러가지/경제"},
    # 여행
    {"name": "경량 여행용 캐리어",      "query": "여행 캐리어 20인치 경량",           "category": "여행"},
    {"name": "여행 파우치 세트",        "query": "여행 파우치 세트 방수",             "category": "여행"},
    {"name": "항공기 목베개",           "query": "여행 목베개 비행기 쿠션",           "category": "여행"},
    # 리뷰/잡화
    {"name": "대용량 보조배터리",       "query": "보조배터리 대용량 20000mAh",        "category": "리뷰/잡화"},
    {"name": "에어팟 프로 케이스",      "query": "에어팟 프로 케이스",                "category": "리뷰/잡화"},
    {"name": "차량용 무선충전 거치대",  "query": "차량용 핸드폰 거치대 무선충전",     "category": "리뷰/잡화"},
    # 리뷰/놀이시설
    {"name": "방수 피크닉 돗자리",      "query": "피크닉 돗자리 방수 대형",           "category": "리뷰/놀이시설"},
    {"name": "경량 캠핑 의자",          "query": "캠핑 의자 경량 접이식",             "category": "리뷰/놀이시설"},
    {"name": "선크림 SPF50+",           "query": "선크림 자외선차단 SPF50 PA",        "category": "리뷰/놀이시설"},
    # 리뷰/영화
    {"name": "블루투스 홈시어터",       "query": "홈시어터 블루투스 스피커 사운드바", "category": "리뷰/영화"},
    {"name": "미니 빔프로젝터",         "query": "미니 빔프로젝터 가정용 휴대용",     "category": "리뷰/영화"},
    {"name": "팝콘 메이커",             "query": "팝콘 기계 가정용 에어팝",           "category": "리뷰/영화"},
    # 리뷰/장난감
    {"name": "어른 취미 레고",          "query": "레고 어른 취미 추천 테크닉",        "category": "리뷰/장난감"},
    {"name": "가족 보드게임",           "query": "보드게임 가족 추천",                "category": "리뷰/장난감"},
    {"name": "애니메이션 피규어",       "query": "피규어 애니메이션 컬렉션",          "category": "리뷰/장난감"},
    # 사진
    {"name": "경량 카메라 삼각대",      "query": "카메라 삼각대 경량 여행",           "category": "사진"},
    {"name": "카메라 백팩",             "query": "카메라 가방 백팩 방수",             "category": "사진"},
    {"name": "ND 렌즈 필터",            "query": "카메라 렌즈 ND 필터 세트",          "category": "사진"},
]


# ─────────────────────────────────────────
# 캐시 파일 관리
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
# fallback: 쿠팡 검색 URL
# ─────────────────────────────────────────
def _fallback_url(query: str) -> str:
    q = urllib.parse.quote(query)
    return f"https://www.coupang.com/np/search?q={q}&channel=user&subChannel=user"


# ─────────────────────────────────────────
# 네트워크 가로채기로 실제 API 엔드포인트 탐지
# ─────────────────────────────────────────
def _intercept_and_generate(page, products: list[dict]) -> dict:
    """
    '바로가기 링크' 페이지에서 URL 입력 → 생성 버튼 클릭 시
    발생하는 실제 API 요청을 가로채서:
      1. 실제 엔드포인트 URL, 헤더, 요청 형식 파악
      2. 이후 모든 상품에 동일 API 재사용
    """
    captured: dict = {"endpoint": None, "req_body": None, "resp_body": None,
                      "headers": None, "method": "POST"}
    results: dict = {}

    # ── 네트워크 이벤트 리스너 등록 ──────────────────────
    def on_request(req: Request):
        if "link.coupang.com" in (req.post_data or "") or (
            "partners.coupang.com" in req.url
            and req.method in ("POST", "GET")
            and any(k in req.url for k in ("short", "link", "banner", "url", "generate"))
        ):
            if not captured["endpoint"]:
                captured["endpoint"] = req.url
                captured["method"]   = req.method
                captured["headers"]  = dict(req.headers)
                try:
                    captured["req_body"] = json.loads(req.post_data or "{}")
                except Exception:
                    captured["req_body"] = req.post_data

    def on_response(resp: Response):
        if captured["endpoint"] and resp.url == captured["endpoint"]:
            try:
                body = resp.json()
                if captured["resp_body"] is None:
                    captured["resp_body"] = body
            except Exception:
                pass

    page.on("request", on_request)
    page.on("response", on_response)

    # ── 바로가기 링크 페이지 이동 ────────────────────────
    print("  '바로가기 링크' 메뉴 탐색 중...")
    barogangi_url = None
    for url in [
        "https://partners.coupang.com/#/barogangi",
        "https://partners.coupang.com/#/bannerLink",
        "https://partners.coupang.com/#/shortUrl",
        "https://partners.coupang.com/barogangi",
        "https://partners.coupang.com/bannerLink",
    ]:
        try:
            page.goto(url, timeout=15000)
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            # URL 입력 필드가 있으면 올바른 페이지
            for sel in [
                "input[placeholder*='URL']",
                "input[placeholder*='링크']",
                "input[placeholder*='주소']",
                "input[placeholder*='url' i]",
                "input[type='url']",
                "textarea[placeholder*='URL']",
            ]:
                try:
                    el = page.wait_for_selector(sel, timeout=3000)
                    if el and el.is_visible():
                        barogangi_url = url
                        print(f"  바로가기 링크 페이지 발견: {url}")
                        break
                except Exception:
                    continue
            if barogangi_url:
                break
        except Exception:
            continue

    if not barogangi_url:
        # 페이지를 찾지 못했으면 사용자에게 직접 이동 요청
        print()
        print("  ┌─────────────────────────────────────────────────────┐")
        print("  │  '바로가기 링크' 메뉴를 직접 열어주세요.             │")
        print("  │  (파트너스 대시보드 → 바로가기 링크 / 배너 링크)    │")
        print("  │  해당 페이지로 이동 후 Enter를 누르세요.             │")
        print("  └─────────────────────────────────────────────────────┘")
        input("  Enter: ")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

    # ── 첫 번째 상품으로 API 탐지 ────────────────────────
    first_product = products[0]
    search_url = f"https://www.coupang.com/np/search?q={urllib.parse.quote(first_product['query'])}"

    print(f"  첫 번째 상품으로 API 탐지: {first_product['name']}")

    # URL 입력 필드 탐색 및 입력
    input_sel = None
    for sel in [
        "input[placeholder*='URL']",
        "input[placeholder*='링크']",
        "input[placeholder*='주소']",
        "input[placeholder*='url' i]",
        "input[type='url']",
        "textarea[placeholder*='URL']",
    ]:
        try:
            el = page.wait_for_selector(sel, timeout=3000)
            if el and el.is_visible():
                input_sel = sel
                break
        except Exception:
            continue

    if not input_sel:
        print("  URL 입력 필드를 찾을 수 없음.")
        print()
        print("  ┌────────────────────────────────────────────────────────┐")
        print("  │  URL 입력 필드에 아래 URL을 직접 붙여넣고 '생성' 클릭  │")
        print(f"  │  {search_url[:55]}  │")
        print("  │  생성된 링크가 화면에 표시되면 Enter를 누르세요.       │")
        print("  └────────────────────────────────────────────────────────┘")
        input("  Enter: ")
    else:
        page.fill(input_sel, search_url)
        time.sleep(0.5)

        # 생성 버튼 클릭
        btn_clicked = False
        for btn_sel in [
            "button:has-text('단축 URL 생성')",
            "button:has-text('URL 생성')",
            "button:has-text('생성')",
            "button:has-text('만들기')",
            "button:has-text('확인')",
            "button[type='submit']",
        ]:
            try:
                page.click(btn_sel, timeout=3000)
                btn_clicked = True
                print(f"  생성 버튼 클릭: {btn_sel}")
                break
            except Exception:
                continue

        if not btn_clicked:
            print("  생성 버튼을 못 찾음 → 직접 클릭해주세요")
            input("  생성 완료 후 Enter: ")

        time.sleep(3)

    # ── 결과 추출 (가로채기 성공 여부 확인) ──────────────
    if captured["endpoint"]:
        print(f"  API 탐지 성공: {captured['endpoint']}")
        print(f"  응답 형식: {str(captured['resp_body'])[:100]}")
        short_link = _extract_short_link_from_response(captured["resp_body"])
        if short_link:
            results[first_product["query"]] = {
                "name": first_product["name"], "query": first_product["query"],
                "category": first_product["category"], "url": short_link, "method": "api"
            }
            print(f"  ✅ {first_product['name']} → {short_link}")
    else:
        # 가로채기 실패 → 페이지에서 직접 추출
        short_link = page.evaluate("""
            () => {
                for (const el of document.querySelectorAll(
                    'input[value*="link.coupang.com"], a[href*="link.coupang.com"]'
                )) { return el.value || el.href; }
                const m = document.body.innerText.match(
                    /https:\\/\\/link\\.coupang\\.com\\/[^\\s"'<>]+/
                );
                return m ? m[0] : null;
            }
        """)
        if short_link:
            results[first_product["query"]] = {
                "name": first_product["name"], "query": first_product["query"],
                "category": first_product["category"], "url": short_link, "method": "ui"
            }
            print(f"  ✅ {first_product['name']} → {short_link} (UI 추출)")
        else:
            print("  API 탐지 실패 → fallback")

    # ── 나머지 상품들 처리 ────────────────────────────────
    remaining = products[1:]

    if captured["endpoint"] and captured["resp_body"] is not None:
        # 탐지된 API를 직접 호출
        print(f"\n  탐지된 API로 나머지 {len(remaining)}개 생성 중...")
        for product in remaining:
            q = urllib.parse.quote(product["query"])
            target_url = f"https://www.coupang.com/np/search?q={q}"

            # 요청 본문 구성 (첫 번째 요청 형식 참고)
            if isinstance(captured["req_body"], dict):
                req_body = {
                    k: target_url if v == search_url else v
                    for k, v in captured["req_body"].items()
                }
            else:
                req_body = {"url": target_url}

            resp_text = page.evaluate("""
                async (endpoint, body, hdrs) => {
                    try {
                        const resp = await fetch(endpoint, {
                            method: 'POST',
                            headers: {...hdrs, 'Content-Type': 'application/json'},
                            credentials: 'include',
                            body: JSON.stringify(body)
                        });
                        if (!resp.ok) return null;
                        return await resp.text();
                    } catch(e) { return null; }
                }
            """, captured["endpoint"], req_body, captured["headers"] or {})

            if resp_text:
                try:
                    resp_data = json.loads(resp_text)
                    short_link = _extract_short_link_from_response(resp_data)
                    if short_link:
                        results[product["query"]] = {
                            "name": product["name"], "query": product["query"],
                            "category": product["category"], "url": short_link, "method": "api"
                        }
                        print(f"  ✅ [api] {product['name']} → {short_link}")
                        time.sleep(0.8)
                        continue
                except Exception:
                    pass

            # API 실패 → fallback
            fb = _fallback_url(product["query"])
            results[product["query"]] = {
                "name": product["name"], "query": product["query"],
                "category": product["category"], "url": fb, "method": "fallback"
            }
            print(f"  ⚠️  [fallback] {product['name']}")
            time.sleep(0.5)
    else:
        # API 탐지 실패 → UI로 나머지 처리
        print(f"\n  API 미탐지 → UI로 나머지 {len(remaining)}개 처리...")
        for product in remaining:
            q = urllib.parse.quote(product["query"])
            target_url = f"https://www.coupang.com/np/search?q={q}"

            short_link = None

            if input_sel:
                try:
                    # 입력 필드 비우고 새 URL 입력
                    page.fill(input_sel, "")
                    page.fill(input_sel, target_url)
                    time.sleep(0.3)

                    # 생성 버튼 클릭
                    for btn_sel in [
                        "button:has-text('단축 URL 생성')",
                        "button:has-text('URL 생성')",
                        "button:has-text('생성')",
                        "button:has-text('만들기')",
                        "button[type='submit']",
                    ]:
                        try:
                            page.click(btn_sel, timeout=2000)
                            break
                        except Exception:
                            continue
                    time.sleep(2)

                    # 결과 추출
                    short_link = page.evaluate("""
                        () => {
                            for (const el of document.querySelectorAll(
                                'input[value*="link.coupang.com"], a[href*="link.coupang.com"]'
                            )) { return el.value || el.href; }
                            const m = document.body.innerText.match(
                                /https:\\/\\/link\\.coupang\\.com\\/[^\\s"'<>]+/
                            );
                            return m ? m[0] : null;
                        }
                    """)
                except Exception as e:
                    print(f"    UI 오류: {e}")

            if short_link:
                results[product["query"]] = {
                    "name": product["name"], "query": product["query"],
                    "category": product["category"], "url": short_link, "method": "ui"
                }
                print(f"  ✅ [ui] {product['name']} → {short_link}")
            else:
                fb = _fallback_url(product["query"])
                results[product["query"]] = {
                    "name": product["name"], "query": product["query"],
                    "category": product["category"], "url": fb, "method": "fallback"
                }
                print(f"  ⚠️  [fallback] {product['name']}")

            time.sleep(0.5)

    page.remove_listener("request", on_request)
    page.remove_listener("response", on_response)
    return results


def _extract_short_link_from_response(data) -> str | None:
    """API 응답에서 link.coupang.com URL 추출."""
    if not data:
        return None

    def _search(obj):
        if isinstance(obj, str) and "link.coupang.com" in obj:
            return obj
        if isinstance(obj, dict):
            for v in obj.values():
                r = _search(v)
                if r:
                    return r
        if isinstance(obj, list):
            for item in obj:
                r = _search(item)
                if r:
                    return r
        return None

    return _search(data)


# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="쿠팡 파트너스 단축 링크 생성기")
    parser.add_argument("--force", action="store_true", help="기존 캐시 무시하고 전체 재생성")
    args = parser.parse_args()

    print("=" * 55)
    print("  쿠팡 파트너스 단축 링크 생성기 (네트워크 가로채기)")
    print(f"  파트너스 ID: {COUPANG_ID}")
    print("=" * 55)

    existing = load_links() if not args.force else {}
    print(f"  기존 캐시: {len(existing)}개 ({'무시' if args.force else '유지'})")

    # 생성 대상: 캐시에 없거나 fallback인 것
    to_generate = [
        p for p in PRODUCTS
        if p["query"] not in existing
        or existing[p["query"]].get("method") == "fallback"
        or args.force
    ]
    print(f"  생성 대상: {len(to_generate)}개")

    if not to_generate:
        print("  모든 링크 캐싱됨. --force 로 재생성 가능.")
        return

    with sync_playwright() as p:
        browser = None
        for browser_type, opts in [
            (p.firefox,  {"headless": False}),
            (p.chromium, {"headless": False, "args": ["--disable-blink-features=AutomationControlled"]}),
        ]:
            try:
                browser = browser_type.launch(**opts)
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
        page = context.new_page()

        # Step 1: 수동 로그인
        print("\n🔐 Step 1: 쿠팡 파트너스 로그인")
        print("  파트너스 사이트 접속 중...")
        page.goto("https://partners.coupang.com/", timeout=30000)
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        cur_url = page.url
        body_text = page.evaluate("() => document.body.innerText.slice(0, 300)")

        if "partners.coupang.com" in cur_url and "login" not in cur_url.lower() \
                and "Access Denied" not in body_text:
            print("  이미 로그인된 상태")
        else:
            print()
            print("  ┌──────────────────────────────────────────────────────┐")
            print("  │  브라우저에서 쿠팡 파트너스에 직접 로그인해 주세요.  │")
            print("  │  로그인 완료 후 이 터미널에서 Enter를 누르세요.       │")
            print("  └──────────────────────────────────────────────────────┘")
            input("  로그인 완료 후 Enter: ")
            page.wait_for_load_state("networkidle")
            time.sleep(2)

        # Step 2: 링크 생성 (네트워크 가로채기)
        print(f"\n🔗 Step 2: 링크 생성 ({len(to_generate)}개)")
        new_links = _intercept_and_generate(page, to_generate)

        browser.close()

    # 캐시 병합 저장
    merged = {**existing, **new_links}
    save_links(merged)

    # 결과 요약
    by_method: dict[str, int] = {}
    for v in new_links.values():
        m = v.get("method", "fallback")
        by_method[m] = by_method.get(m, 0) + 1

    print(f"\n{'='*55}")
    print("  생성 결과")
    print(f"{'='*55}")
    for method, count in sorted(by_method.items()):
        icon = "✅" if method != "fallback" else "⚠️ "
        print(f"  {icon} {method}: {count}개")
    print(f"  저장: {LINKS_FILE} ({len(merged)}개 총)")

    fallback_count = by_method.get("fallback", 0)
    api_count = len(new_links) - fallback_count
    if api_count > 0:
        print(f"\n  🎉 {api_count}개 파트너스 단축 링크 생성 완료!")
        print(f"  이제 'python insert_coupang.py --fix 200' 을 실행해 블로그 링크를 교체하세요.")
    else:
        print("\n  ⚠️  모두 fallback. 파트너스 로그인 상태를 확인 후 재시도하세요.")


if __name__ == "__main__":
    main()
