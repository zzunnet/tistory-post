"""
Claude 대화 기반 티스토리 자동 포스팅
사용법: python auto_post.py
사전 준비: export ANTHROPIC_API_KEY="sk-ant-..."
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import os
import json
import re
import time

from anthropic import Anthropic
from playwright.sync_api import sync_playwright

# ─────────────────────────────────────────
# 설정 (여기만 수정)
# ─────────────────────────────────────────
KAKAO_EMAIL    = "zzunnet@gmail.com"
KAKAO_PASSWORD = "cks99kak"
BLOG_NAME      = "zzun"                 # zzun.tistory.com
CATEGORY       = "IT / 보안"           # 티스토리 카테고리 (상위 / 하위)

MAX_SESSIONS        = 5    # 참고할 최근 세션 수
MAX_MSG_PER_SESSION = 30   # 세션당 최대 메시지 수
# ─────────────────────────────────────────


# ──────────────────────────────────────────────────
# Step 1. 최근 Claude 대화 수집
# ──────────────────────────────────────────────────
def get_recent_conversations() -> list[str]:
    """최근 Claude 세션에서 텍스트 블록을 수집합니다."""
    try:
        from claude_agent_sdk import list_sessions, get_session_messages
    except ImportError:
        print("⚠️  claude-agent-sdk 미설치: pip install claude-agent-sdk")
        return []

    sessions = list_sessions()
    print(f"  총 Claude 세션 수: {len(sessions)}")

    texts = []
    for session in sessions[:MAX_SESSIONS]:
        try:
            msgs = get_session_messages(session_id=session.session_id)
            for msg in msgs[:MAX_MSG_PER_SESSION]:
                # SessionMessage.message = {'role': ..., 'content': ...}
                raw = getattr(msg, 'message', {}) or {}
                content = raw.get('content', '')

                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            t = block.get('text', '')
                        else:
                            t = getattr(block, 'text', '')
                        if t and len(t.strip()) > 30:
                            texts.append(t.strip()[:1000])
                elif isinstance(content, str) and len(content.strip()) > 30:
                    texts.append(content.strip()[:1000])
        except Exception as e:
            print(f"  세션 오류 ({getattr(session, 'session_id', '?')[:8]}...): {e}")

    print(f"  수집된 텍스트 블록: {len(texts)}개")
    return texts


# ──────────────────────────────────────────────────
# Step 2. Claude Opus 4.6 으로 포스트 생성
# ──────────────────────────────────────────────────
def generate_blog_post(conv_texts: list[str]) -> tuple[str, str, str]:
    """Claude Opus 4.6 (adaptive thinking) 으로 블로그 포스트를 생성합니다."""
    client = Anthropic()

    combined = "\n\n".join(conv_texts[:40])
    if len(combined) > 15000:
        combined = combined[:15000] + "\n\n...(이하 생략)"

    print("  Claude Opus 4.6 스트리밍 중...")

    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system="""당신은 IT·보안·PKI·암호화·개발 분야 전문 기술 블로그 작가입니다.
주어진 Claude 대화 내용을 분석해 핵심 기술 주제를 발굴하고,
실무자·개발자에게 가치 있는 블로그 포스트를 작성하세요.

반드시 아래 JSON 형식으로만 응답하세요 (추가 텍스트 없이):
{
  "title": "흥미롭고 구체적인 제목 (60자 이내)",
  "content": "HTML 본문 (h2/h3/p/ul/li/strong/em/hr/code 태그 사용, 최소 1500자)",
  "tags": "태그1,태그2,...,태그10 (최대 10개, 쉼표 구분)"
}

작성 지침:
- 대화에서 실제로 다룬 기술 주제 기반
- 서론 → 본론(3~4섹션) → 결론 구조
- 독자가 실무에 바로 적용할 수 있는 인사이트 포함
- 전문 용어는 간단한 설명 병기
- 날짜/시간 정보 포함 금지 (포스팅 날짜와 혼동)""",
        messages=[{
            "role": "user",
            "content": f"아래 Claude 대화를 기반으로 블로그 포스트를 작성해주세요:\n\n{combined}"
        }]
    ) as stream:
        response = stream.get_final_message()

    text = next((b.text for b in response.content if b.type == "text"), "")

    json_match = re.search(r'\{[\s\S]*\}', text)
    if not json_match:
        raise ValueError(f"JSON 추출 실패:\n{text[:400]}")

    data = json.loads(json_match.group())
    title   = data['title']
    content = data['content']
    tags    = data['tags']

    print(f"  제목: {title}")
    print(f"  태그: {tags}")
    print(f"  본문: {len(content)}자")
    return title, content, tags


# ──────────────────────────────────────────────────
# Step 3. 티스토리 포스팅
# ──────────────────────────────────────────────────
def _login(page, blog_name: str, email: str, password: str):
    print("  카카오 로그인 중...")
    page.goto(f"https://{blog_name}.tistory.com/manage")
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


def _select_category(page, category: str):
    """발행 패널에서 카테고리(상위/하위)를 선택합니다."""
    try:
        cat_btn = page.locator("button:has-text('선택 안 함')")
        if cat_btn.count() == 0:
            print("  카테고리 버튼 없음, 스킵")
            return

        cat_btn.first.click()
        time.sleep(1.5)

        # "IT / 보안" → parent="IT", child="보안"
        parts = [p.strip() for p in category.split("/")]

        if len(parts) >= 2:
            parent_name, child_name = parts[0], parts[1]

            # 1) 상위 카테고리 클릭 (아코디언 열기)
            parent_locator = page.locator(f"li:has-text('{parent_name}')")
            matched = [li for li in parent_locator.all()
                       if li.inner_text().strip().startswith(parent_name)]
            if matched:
                matched[0].click()
                time.sleep(0.8)

            # 2) 하위 카테고리 클릭
            child_locator = page.locator(f"li:has-text('{child_name}')")
            matched_child = [li for li in child_locator.all()
                             if li.inner_text().strip().startswith(child_name)]
            if matched_child:
                matched_child[0].click()
                time.sleep(0.5)
                print(f"  카테고리 선택: {parent_name} / {child_name}")
            else:
                print(f"  하위 카테고리 '{child_name}' 못찾음, 상위만 선택")
        else:
            # 단일 카테고리
            items = page.locator(f"li:has-text('{parts[0]}')").all()
            if items:
                items[0].click()
                time.sleep(0.5)
                print(f"  카테고리 선택: {parts[0]}")

    except Exception as e:
        print(f"  카테고리 선택 오류: {e}")


def post_to_tistory(title: str, content: str, tags: str, category: str = CATEGORY):
    """Playwright로 티스토리에 공개 발행합니다."""
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

        # 1. 로그인
        _login(page, BLOG_NAME, KAKAO_EMAIL, KAKAO_PASSWORD)

        # 2. 글쓰기 이동
        print("  글쓰기 페이지 이동...")
        page.goto(f"https://{BLOG_NAME}.tistory.com/manage/newpost/")
        page.wait_for_load_state("networkidle")
        time.sleep(3)

        # 3. 제목
        print("  제목 입력...")
        page.wait_for_selector("[placeholder*='제목']", timeout=15000)
        page.click("[placeholder*='제목']")
        page.type("[placeholder*='제목']", title, delay=30)

        # 4. 본문 (TinyMCE + save 동기화)
        print("  본문 입력...")
        time.sleep(2)
        page.wait_for_function(
            "() => typeof tinymce !== 'undefined' && tinymce.editors.length > 0",
            timeout=15000
        )
        content_escaped = (
            content
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
        print(f"  본문 결과: {result}")
        time.sleep(1)

        # 5. 태그
        print("  태그 입력...")
        tag_input = page.locator("input[placeholder*='태그']")
        if tag_input.count() > 0:
            tag_input.click()
            page.type("input[placeholder*='태그']", tags, delay=30)
            page.keyboard.press("Enter")
        time.sleep(1)

        # 6. 발행 패널
        print("  발행 패널 열기...")
        page.click("button:has-text('완료')")
        time.sleep(3)

        # 7. 카테고리
        if category:
            _select_category(page, category)

        # 8. 공개 라디오 선택
        page.evaluate("""
            const radios = document.querySelectorAll('input[type=radio]');
            for (const r of radios) {
                const label = document.querySelector('label[for="' + r.id + '"]');
                if (label && label.innerText.trim() === '공개') { r.click(); break; }
            }
        """)
        time.sleep(1)

        # 9. 발행 버튼 클릭
        btn_texts = [b.inner_text().strip() for b in page.locator("button").all()]
        print(f"  버튼: {[t for t in btn_texts if t and len(t) < 20]}")

        for keyword in ["공개 발행", "발행", "공개 저장"]:
            candidates = page.locator(f"button:has-text('{keyword}')").all()
            visible = [b for b in candidates if "비공개" not in b.inner_text()]
            if visible:
                print(f"  '{keyword}' 클릭")
                visible[0].click()
                time.sleep(3)
                break

        page.wait_for_load_state("networkidle", timeout=15000)
        final_url = page.url
        print(f"  발행 완료! URL: {final_url}")
        browser.close()
        return final_url


# ──────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("  Claude 대화 기반 티스토리 자동 포스팅")
    print("=" * 55)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\n❌ ANTHROPIC_API_KEY 환경변수가 없습니다.")
        print("   아래 명령어로 설정 후 재실행하세요:")
        print("   export ANTHROPIC_API_KEY='sk-ant-...'")
        sys.exit(1)

    # Step 1
    print("\n📥 Step 1: Claude 대화 수집")
    conv_texts = get_recent_conversations()
    if not conv_texts:
        print("  대화 없음 → IT/보안 기본 주제로 진행")
        conv_texts = [
            "IT 보안, PKI, 인증서 관리, 암호화 알고리즘, 양자내성암호(PQC), HSM, 금융 보안"
        ]

    # Step 2
    print("\n✍️  Step 2: 포스트 생성 (Claude Opus 4.6)")
    title, content, tags = generate_blog_post(conv_texts)

    # Step 3
    print("\n🚀 Step 3: 티스토리 포스팅")
    post_to_tistory(title, content, tags)
