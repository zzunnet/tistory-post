"""
Tistory 자동 발행 스크립트
사용법: python tistory_post.py
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

from playwright.sync_api import sync_playwright
import time

# ─────────────────────────────────────────
# ✏️  여기만 수정하세요
# ─────────────────────────────────────────
KAKAO_EMAIL    = "zzunnet@gmail.com"   # 카카오 로그인 이메일
KAKAO_PASSWORD = "cks99kak"           # 카카오 로그인 비밀번호
BLOG_NAME      = "zzun"               # zzun.tistory.com

TITLE = "HSM이 PQC 전환의 병목이 되는 이유 — CA 운영자 시각에서"

TAGS = "PQC,양자내성암호,HSM,Thales Luna,PKI,FIPS140,인증서,암호전환,금융보안,ML-DSA"

# 카테고리 이름 (빈 문자열이면 선택 안 함)
# 관리 페이지의 카테고리명과 정확히 일치해야 합니다
CATEGORY = ""

# HTML로 변환된 본문 (마크다운 → HTML)
CONTENT = """
<p><em>2026.04.24 · PKI·인증서 · 읽는 데 약 7분</em></p>

<p>양자내성암호(PQC) 전환을 준비하다 보면 가장 먼저 막히는 지점이 있다. NIST 표준도 나왔고, 알고리즘도 골랐는데 — HSM이 문제다.</p>
<p>CA 운영자 입장에서 솔직하게 정리해본다.</p>

<h2>HSM은 왜 PQC 전환에서 병목이 되는가</h2>

<p>PKI 인프라에서 HSM은 단순한 키 저장소가 아니다. CA의 개인키를 보호하고, 서명 연산을 수행하고, FIPS 140-2/3 인증을 통해 규제 요건을 충족시키는 핵심 신뢰 앵커다. 문제는 이 HSM이 PQC 알고리즘 앞에서 예상치 못한 여러 제약을 드러낸다는 점이다.</p>

<h3>1. 펌웨어 업그레이드만으로는 안 되는 경우가 많다</h3>

<p>벤더들은 "펌웨어 업그레이드로 PQC 지원 가능"이라고 홍보한다. 틀린 말은 아니다. Thales Luna 7의 경우 특정 펌웨어 버전 이상에서 ML-KEM, ML-DSA를 지원한다.</p>
<p>그런데 실제로 운영 환경에 적용하려면 몇 가지 전제가 따라온다.</p>
<ul>
<li><strong>기존 FIPS 인증서 번호가 바뀐다.</strong> 펌웨어를 올리면 새 CMVP 인증서로 전환되는데, 기관에 따라 이 변경 자체가 감사 이슈가 된다.</li>
<li><strong>기존 키 슬롯 구조가 영향을 받을 수 있다.</strong> 마이그레이션 전 전체 백업과 복구 테스트가 선행되어야 한다.</li>
<li><strong>HA(고가용성) 구성을 유지하면서 롤링 업그레이드가 가능한지</strong> 사전에 벤더와 확인해야 한다. 문서에는 나오지 않는 부분이다.</li>
</ul>

<h3>2. PQC 키 크기가 HSM 성능에 직접 타격을 준다</h3>

<p>RSA-2048 서명 연산과 ML-DSA-65 서명 연산의 연산량은 차원이 다르다. ML-DSA의 공개키는 약 1,952바이트, 서명은 약 3,293바이트다. ECDSA P-256과 비교하면 각각 수십 배 크다.</p>
<p>CA처럼 초당 수백~수천 건의 인증서를 발급하는 환경에서는 HSM의 서명 처리량(TPS)이 직접적인 병목이 된다. 단순히 알고리즘을 교체하는 것이 아니라, <strong>HSM 수량 증설 또는 부하 분산 구조 재설계</strong>가 따라올 수 있다.</p>
<p>OCSP 응답 서명도 마찬가지다. 실시간 유효성 검증을 위해 대량의 서명을 처리하는 OCSP 서버에서는 이 성능 저하가 사용자 체감으로 이어진다.</p>

<h3>3. PQC CMVP 인증 제품이 아직 적다</h3>

<p>FIPS 140-3 인증을 받은 HSM 제품 중 PQC 알고리즘을 공식 지원하는 제품은 2026년 현재도 손에 꼽는다. 규제 환경이 엄격한 금융권에서는 "지원한다"와 "CMVP 인증된 모듈에서 지원한다"는 전혀 다른 의미다.</p>
<p>국내의 경우 KCMVP 인증 제품군에서 PQC 알고리즘 지원이 추가되려면 국산 KpqC 알고리즘(SMAUG-T, HAETAE 등)의 표준화 완료와 검증 체계 구축이 선행되어야 한다. 이 타임라인이 아직 확정되지 않았다는 점이 국내 금융기관 입장에서 가장 불확실한 부분이다.</p>

<h3>4. 전환 기간 동안 이중 운영이 불가피하다</h3>

<p>PQC로 완전히 전환하기 전까지는 기존 RSA/ECC 인프라와 PQC 인프라를 동시에 운영해야 한다. 하이브리드 인증서(Hybrid Certificate)를 발급하려면 두 알고리즘의 키를 모두 HSM에서 관리해야 하고, 이는 키 슬롯, 성능, 관리 복잡도 모든 면에서 부담이 두 배가 된다.</p>
<p>이 이중 운영 기간이 얼마나 길어질지는 클라이언트 생태계(브라우저, OS, 애플리케이션)의 PQC 지원 속도에 달려 있다. 보수적으로 보면 2030년까지는 이 상태가 이어진다.</p>

<h2>그래서 지금 뭘 해야 하나</h2>

<p>HSM이 병목이라고 해서 PQC 전환을 미뤄야 한다는 뜻이 아니다. 오히려 병목을 일찍 파악할수록 대응 시간이 생긴다.</p>

<p><strong>현재 HSM 인벤토리부터 점검한다.</strong> 보유 중인 HSM 모델과 펌웨어 버전, 현재 CMVP 인증서 번호를 정리하고 벤더의 PQC 지원 로드맵과 대조해본다. Thales의 경우 Customer Portal에서 제품별 PQC 지원 계획을 확인할 수 있다.</p>

<p><strong>성능 테스트 환경을 먼저 구성한다.</strong> 운영 환경에 바로 적용하기 전에 테스트 HSM에서 ML-DSA 서명 TPS를 측정해본다. 현재 운영 부하 기준으로 어느 시점에서 성능이 문제가 될지 예측할 수 있다.</p>

<p><strong>소프트웨어 레이어부터 준비한다.</strong> HSM이 준비되기 전이라도 BouncyCastle, OpenSSL 3.x 등 PQC를 지원하는 암호 라이브러리로 애플리케이션 레이어를 먼저 전환해둘 수 있다. HSM이 소프트웨어 폴백(fallback)을 허용하는 구간 동안 전환 테스트가 가능하다.</p>

<hr>

<p>PQC 전환은 알고리즘 교체가 아니라 인프라 전체의 재설계에 가깝다. HSM은 그 인프라에서 가장 느리게 움직이는 레이어다. 그래서 가장 먼저 들여다봐야 한다.</p>

<p><em>이 글은 금융권 PKI 운영 실무 경험을 바탕으로 작성했습니다. 특정 벤더 제품의 사양은 버전에 따라 다를 수 있으며, 도입 전 반드시 벤더와 확인하시기 바랍니다.</em></p>
"""
# ─────────────────────────────────────────

def post_to_tistory():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()

        # 1. 카카오 로그인
        print("🔐 로그인 중...")
        page.goto(f"https://{BLOG_NAME}.tistory.com/manage")
        page.wait_for_load_state("networkidle")

        page.click(".link_kakao_id")
        page.wait_for_url("**/accounts.kakao.com/**", timeout=15000)
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        # 이메일/비밀번호 입력
        for sel in ["#loginId--1", "input[name='loginId']", "input[type='email']"]:
            try:
                page.wait_for_selector(sel, timeout=3000)
                page.click(sel)
                page.type(sel, KAKAO_EMAIL, delay=50)
                break
            except Exception:
                continue

        for sel in ["#password--2", "input[name='password']", "input[type='password']"]:
            try:
                page.wait_for_selector(sel, timeout=3000)
                page.click(sel)
                page.type(sel, KAKAO_PASSWORD, delay=50)
                break
            except Exception:
                continue

        page.click('button[type="submit"]')
        # tistory.com이 HOST인 URL 도달까지 대기
        # (kakao URL에 tistory.com이 쿼리파라미터로 포함되어 있으므로 람다로 정확히 판별)
        page.wait_for_url(
            lambda url: "tistory.com" in url and "kakao.com" not in url,
            timeout=60000
        )
        page.wait_for_load_state("networkidle", timeout=20000)
        print("✅ 로그인 완료 —", page.url)

        # 2. 글쓰기 페이지 이동
        print("✍️  글쓰기 페이지 이동...")
        page.goto(f"https://{BLOG_NAME}.tistory.com/manage/newpost/")
        page.wait_for_load_state("networkidle")
        time.sleep(3)

        # 3. 제목 입력
        print("📝 제목 입력...")
        page.wait_for_selector("[placeholder*='제목']", timeout=15000)
        page.click("[placeholder*='제목']")
        page.type("[placeholder*='제목']", TITLE, delay=30)

        # 4. 본문 입력 — TinyMCE JS API + save() 동기화
        print("📄 본문 입력...")
        time.sleep(2)

        # TinyMCE 초기화 대기
        page.wait_for_function("() => typeof tinymce !== 'undefined' && tinymce.editors.length > 0", timeout=15000)

        content_escaped = CONTENT.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
        result = page.evaluate(f"""
            () => {{
                const editor = tinymce.get(0) || tinymce.editors[0];
                if (!editor) return 'editor not found';
                editor.setContent(`{content_escaped}`);
                editor.save();           // textarea 동기화 (핵심)
                editor.fire('change');
                editor.fire('input');
                return 'ok: ' + editor.getContent().length + ' chars';
            }}
        """)
        print(f"본문 입력 결과: {result}")
        time.sleep(1)

        # 5. 태그 입력
        print("🏷️  태그 입력...")
        tag_input = page.locator("input[placeholder*='태그']")
        if tag_input.count() > 0:
            tag_input.click()
            page.type("input[placeholder*='태그']", TAGS, delay=30)
            page.keyboard.press("Enter")
        time.sleep(1)

        # 6. 발행 패널 열기
        print("🚀 발행 중...")
        page.screenshot(path="before_submit.png")
        page.click("button:has-text('완료')")
        time.sleep(3)
        page.screenshot(path="after_complete_btn.png")

        # 7. 카테고리 선택 (CATEGORY가 설정된 경우)
        if CATEGORY:
            print(f"📂 카테고리 선택: {CATEGORY}")
            try:
                # 홈주제(카테고리) 버튼 클릭
                cat_btn = page.locator("button:has-text('선택 안 함')")
                if cat_btn.count() > 0:
                    cat_btn.first.click()
                    time.sleep(1)
                    page.screenshot(path="category_dropdown.png")
                    # 카테고리 옵션 클릭
                    cat_option = page.locator(f"li:has-text('{CATEGORY}'), a:has-text('{CATEGORY}')")
                    if cat_option.count() > 0:
                        cat_option.first.click()
                        time.sleep(1)
                        print(f"카테고리 '{CATEGORY}' 선택 완료")
                    else:
                        print(f"카테고리 '{CATEGORY}'를 찾지 못했습니다. 카테고리 없이 진행합니다.")
            except Exception as e:
                print(f"카테고리 선택 실패: {e}")
        else:
            # CATEGORY가 비어있으면 사용 가능한 카테고리 목록 출력
            try:
                cat_btn = page.locator("button:has-text('선택 안 함')")
                if cat_btn.count() > 0:
                    cat_btn.first.click()
                    time.sleep(1)
                    page.screenshot(path="category_dropdown.png")
                    options = page.locator("li[class*='category'], li[class*='item'], .dropdown li, .list_category li").all()
                    if options:
                        print("사용 가능한 카테고리:")
                        for opt in options:
                            print(f"  - {opt.inner_text().strip()}")
                    # 닫기
                    page.keyboard.press("Escape")
                    time.sleep(1)
            except Exception:
                pass

        # 8. 공개 라디오 버튼 선택 (JavaScript)
        page.evaluate("""
            const radios = document.querySelectorAll('input[type=radio]');
            for (const r of radios) {
                const label = document.querySelector('label[for="' + r.id + '"]');
                if (label && label.innerText.trim() === '공개') {
                    r.click();
                    break;
                }
            }
        """)
        time.sleep(1)
        page.screenshot(path="after_public_select.png")

        # 9. 발행 버튼 클릭
        btns = page.locator("button").all()
        btn_texts = [b.inner_text().strip() for b in btns]
        print(f"버튼 목록: {[t for t in btn_texts if t]}")

        for keyword in ["공개 발행", "발행", "공개 저장"]:
            btn = page.locator(f"button:has-text('{keyword}')")
            visible_btns = [b for b in btn.all() if "비공개" not in b.inner_text()]
            if visible_btns:
                print(f"'{keyword}' 버튼 클릭")
                visible_btns[0].click()
                time.sleep(3)
                break

        page.screenshot(path="after_submit.png")
        page.wait_for_load_state("networkidle", timeout=15000)
        print(f"✅ 발행 완료! URL: {page.url}")
        browser.close()

if __name__ == "__main__":
    post_to_tistory()
