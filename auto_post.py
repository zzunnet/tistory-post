"""
Claude·Gemini 대화 기반 티스토리 자동 포스팅 (Gemini 2.0 Flash)
사용법: python auto_post.py
사전 준비: .env 파일에 GEMINI_API_KEY, KAKAO_EMAIL, KAKAO_PASSWORD 설정
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import os
import glob
import json
import re
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()  # .env 파일에서 키 로드

from google import genai
from playwright.sync_api import sync_playwright

# ─────────────────────────────────────────
# 설정 (여기만 수정)
# ─────────────────────────────────────────
KAKAO_EMAIL    = os.environ["KAKAO_EMAIL"]
KAKAO_PASSWORD = os.environ["KAKAO_PASSWORD"]
BLOG_NAME      = "zzun"                 # zzun.tistory.com
CATEGORY       = "IT / 보안"           # 티스토리 카테고리 (상위 / 하위)

MAX_SESSIONS        = 5    # 참고할 최근 Claude 세션 수
MAX_MSG_PER_SESSION = 30   # 세션당 최대 메시지 수
MAX_GEMINI_SESSIONS = 5    # 참고할 최근 Gemini 세션 수
MAX_POSTS           = 3    # 1회 실행 시 발행할 포스트 수
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
# Step 1b. 최근 Gemini CLI 대화 수집
# ──────────────────────────────────────────────────
def get_gemini_conversations() -> list[str]:
    """~/.gemini/tmp/*/chats/*.json 에서 최근 Gemini 대화를 수집합니다."""
    gemini_dir = Path.home() / ".gemini" / "tmp"
    if not gemini_dir.exists():
        print("  Gemini 대화 디렉터리 없음, 스킵")
        return []

    # 모든 session JSON 파일을 수정 시각 최신순으로 정렬
    session_files = sorted(
        gemini_dir.glob("*/chats/session-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    print(f"  Gemini 세션 파일: {len(session_files)}개 발견")

    texts = []
    for session_file in session_files[:MAX_GEMINI_SESSIONS]:
        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
            messages = data.get("messages", [])
            for msg in messages:
                msg_type = msg.get("type", "")
                if msg_type not in ("user", "gemini"):
                    continue
                content = msg.get("content", "")
                if isinstance(content, list):
                    for block in content:
                        t = block.get("text", "") if isinstance(block, dict) else str(block)
                        if t and len(t.strip()) > 30:
                            texts.append(t.strip()[:1000])
                elif isinstance(content, str) and len(content.strip()) > 30:
                    texts.append(content.strip()[:1000])
        except Exception as e:
            print(f"  Gemini 세션 오류 ({session_file.name}): {e}")

    print(f"  Gemini 수집 텍스트 블록: {len(texts)}개")
    return texts


# ──────────────────────────────────────────────────
# 공통: Gemini 호출 헬퍼
# ──────────────────────────────────────────────────
def _gemini_call(client, prompt: str) -> str:
    """quota 소진 시 fallback 모델 순서로 Gemini 호출. 응답 텍스트 반환."""
    models = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-2.5-flash"]
    for model_name in models:
        try:
            print(f"    [{model_name}] 호출 중...")
            resp = client.models.generate_content(model=model_name, contents=prompt)
            return resp.text.strip()
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                print(f"    [{model_name}] quota 소진, 다음 모델 시도...")
                continue
            raise
    raise RuntimeError("모든 Gemini 모델 quota 소진. 내일 다시 시도하세요.")


def _parse_json(text: str) -> dict:
    """마크다운 제거 후 JSON 파싱. 실패 시 정규식 fallback."""
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$', '', text, flags=re.MULTILINE)
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        raise ValueError(f"JSON 추출 실패:\n{text[:400]}")
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        raw = m.group()
        title_m   = re.search(r'"title"\s*:\s*"([^"]*)"', raw)
        content_m = re.search(r'"content"\s*:\s*"([\s\S]*?)"\s*,\s*"tags"', raw)
        tags_m    = re.search(r'"tags"\s*:\s*"([^"]*)"', raw)
        if title_m and content_m and tags_m:
            return {
                "title":    title_m.group(1),
                "content":  content_m.group(1).replace('\\"', '"'),
                "tags":     tags_m.group(1),
                "category": "IT/개발",
            }
        raise ValueError(f"JSON 파싱 실패:\n{raw[:400]}")


# ──────────────────────────────────────────────────
# Step 2a. 대화에서 독립 주제 목록 추출
# ──────────────────────────────────────────────────
def analyze_topics(conv_texts: list[str], n: int = MAX_POSTS) -> list[dict]:
    """대화 전체를 분석해 블로그 포스트로 쓸 만한 독립 주제 n개를 반환합니다.
    반환: [{"topic": "...", "focus": "...", "category": "IT/개발|IT/보안"}, ...]
    """
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    combined = "\n\n".join(conv_texts[:60])
    if len(combined) > 18000:
        combined = combined[:18000] + "\n\n...(이하 생략)"

    prompt = f"""당신은 IT 기술 블로그 편집장입니다.
아래 대화 기록을 읽고, 각각 독립적인 블로그 포스트로 쓸 수 있는 기술 주제를 정확히 {n}개 추출하세요.

규칙:
1. 주제는 서로 완전히 다른 영역이어야 합니다 (중복 금지)
2. 대화에서 실제로 다룬 내용 기반 (추측 금지)
3. 순수 JSON 배열만 반환 (마크다운·설명 없이)
4. 각 항목: {{"topic": "주제명(20자 이내)", "focus": "이 포스트에서 집중할 핵심 내용(100자 이내)", "category": "IT/개발 또는 IT/보안"}}

카테고리:
- IT/보안: 암호화, PQC, HSM, PKI, 인증서, 보안 취약점, 금융보안
- IT/개발: 프로그래밍, 자동화, 웹개발, 디버깅, 라이브러리, API, 도구

=== 대화 내용 ===
{combined}"""

    print("  주제 분석 중...")
    text = _gemini_call(client, prompt)
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$', '', text, flags=re.MULTILINE)
    arr_m = re.search(r'\[[\s\S]*\]', text)
    if not arr_m:
        raise ValueError(f"주제 JSON 배열 추출 실패:\n{text[:400]}")
    topics = json.loads(arr_m.group())
    print(f"  추출된 주제 {len(topics)}개:")
    for i, t in enumerate(topics, 1):
        print(f"    {i}. [{t.get('category','')}] {t.get('topic','')} — {t.get('focus','')[:50]}")
    return topics[:n]


# ──────────────────────────────────────────────────
# Step 2b. 특정 주제로 블로그 포스트 생성
# ──────────────────────────────────────────────────
def generate_blog_post(topic: dict, conv_texts: list[str]) -> tuple[str, str, str, str]:
    """하나의 주제(topic dict)에 집중한 블로그 포스트를 생성합니다.
    반환: (title, content, tags, category)
    """
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    # 주제와 관련 있는 텍스트 블록만 우선 선별 (키워드 포함 여부)
    keyword = topic.get("topic", "")
    relevant = [t for t in conv_texts if any(w in t for w in keyword.split())]
    combined_texts = (relevant or conv_texts)[:30]
    combined = "\n\n".join(combined_texts)
    if len(combined) > 12000:
        combined = combined[:12000] + "\n\n...(이하 생략)"

    prompt = f"""당신은 IT·보안·개발 분야 전문 기술 블로그 작가입니다.
아래 지정된 주제 하나에만 집중하여 블로그 포스트를 작성하세요.

[작성 주제]
- 주제명: {topic.get('topic', '')}
- 핵심 포커스: {topic.get('focus', '')}
- 카테고리: {topic.get('category', 'IT/개발')}

[중요 규칙]
1. 순수 JSON 객체만 반환 (마크다운 코드블록 없이)
2. content 필드의 HTML 안에서 큰따옴표(") 사용 금지 → 작은따옴표(') 사용
3. content 필드의 HTML 안에서 역슬래시(\\) 사용 금지
4. JSON 이외의 텍스트 일절 없이
5. 위 주제 외 다른 주제 내용 포함 금지

반환 형식:
{{"title": "제목 (60자 이내)", "content": "HTML 본문 (h2/h3/p/ul/li/strong/em/code 태그, 최소 1500자, 큰따옴표 금지)", "tags": "태그1,태그2,...,태그10", "category": "{topic.get('category', 'IT/개발')}"}}

작성 지침:
- 서론 → 본론(3~4섹션) → 결론 구조
- 독자가 실무에 바로 적용할 수 있는 인사이트
- 전문 용어는 간단한 설명 병기
- 날짜/시간 정보 포함 금지

=== 참고 대화 내용 ===
{combined}"""

    text = _gemini_call(client, prompt)
    data = _parse_json(text)

    title    = data['title']
    content  = data['content']
    tags     = data['tags']
    category = data.get('category', topic.get('category', 'IT/개발'))

    print(f"  제목: {title}")
    print(f"  카테고리: {category}")
    print(f"  태그: {tags[:60]}")
    print(f"  본문: {len(content)}자")
    return title, content, tags, category


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
    """에디터 상단 카테고리 드롭다운에서 카테고리를 선택합니다.
    티스토리: 상위='IT', 하위='- 보안' (대시+공백 접두사)
    """
    try:
        # 에디터 상단 카테고리 버튼 — 버튼 목록에서 "카테고리" 포함된 첫 버튼
        cat_btn = None
        for btn in page.locator("button").all():
            try:
                if "카테고리" in btn.inner_text():
                    cat_btn = btn
                    break
            except Exception:
                continue
        if cat_btn is None:
            print("  카테고리 버튼 없음, 스킵")
            return

        cat_btn.click()
        time.sleep(1.5)

        # 드롭다운: div[role="option"][aria-label="..."] 구조
        # 하위 카테고리("- 보안")가 이미 목록에 있으므로 바로 클릭
        # "IT/보안" → label = "- 보안"
        parts = [p.strip() for p in category.split("/")]
        if len(parts) >= 2:
            label = f"- {parts[1]}"
        else:
            label = parts[0]

        clicked = page.evaluate(f"""
            () => {{
                const el = document.querySelector('[role="option"][aria-label="{label}"]');
                if (el) {{ el.click(); return true; }}
                return false;
            }}
        """)
        time.sleep(0.5)
        if clicked:
            print(f"  카테고리 선택: '{label}'")
        else:
            print(f"  카테고리 항목 없음: '{label}'")

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

        # 5. 카테고리 선택 (에디터 상단, 발행 패널 열기 전)
        if category:
            print("  카테고리 선택...")
            _select_category(page, category)

        # 6. 태그
        print("  태그 입력...")
        tag_input = page.locator("input[placeholder*='태그']")
        if tag_input.count() > 0:
            tag_input.click()
            page.type("input[placeholder*='태그']", tags, delay=30)
            page.keyboard.press("Enter")
        time.sleep(1)

        # 7. 발행 패널
        print("  발행 패널 열기...")
        page.click("button:has-text('완료')")
        time.sleep(3)

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

        # 발행 후 글 목록 또는 글 URL로 이동 대기
        try:
            page.wait_for_url(
                lambda url: "newpost" not in url,
                timeout=10000
            )
        except Exception:
            pass
        page.wait_for_load_state("networkidle", timeout=10000)
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

    if not os.environ.get("GEMINI_API_KEY"):
        print("\n❌ GEMINI_API_KEY 환경변수가 없습니다.")
        print("   .env 파일에 GEMINI_API_KEY=... 를 추가하세요.")
        sys.exit(1)

    # Step 1: 대화 수집 (Claude + Gemini)
    print("\n📥 Step 1: Claude 대화 수집")
    conv_texts = get_recent_conversations()

    print("\n📥 Step 1b: Gemini 대화 수집")
    conv_texts += get_gemini_conversations()

    if not conv_texts:
        print("  대화 없음 → 기본 주제로 진행")
        conv_texts = ["IT 개발, 자동화, Python, 웹개발, 디버깅, API 연동, 보안"]

    print(f"\n  총 수집 블록: {len(conv_texts)}개 (Claude + Gemini)")

    # Step 2a: 주제 목록 추출
    print(f"\n🔍 Step 2a: 주제 분석 ({MAX_POSTS}개 추출)")
    topics = analyze_topics(conv_texts, n=MAX_POSTS)

    # Step 2b + 3: 주제별 포스트 생성 & 발행
    results = []
    for i, topic in enumerate(topics, 1):
        print(f"\n{'='*55}")
        print(f"  [{i}/{len(topics)}] 주제: {topic.get('topic','')}")
        print(f"{'='*55}")

        print(f"\n✍️  Step 2b: 포스트 생성")
        try:
            title, content, tags, category = generate_blog_post(topic, conv_texts)
        except Exception as e:
            print(f"  ❌ 생성 실패: {e}")
            results.append({"topic": topic.get("topic"), "status": "생성실패", "url": None})
            continue

        print(f"\n🚀 Step 3: 티스토리 포스팅")
        try:
            url = post_to_tistory(title, content, tags, category)
            results.append({"topic": topic.get("topic"), "status": "발행완료", "url": url})
        except Exception as e:
            print(f"  ❌ 포스팅 실패: {e}")
            results.append({"topic": topic.get("topic"), "status": "포스팅실패", "url": None})

        if i < len(topics):
            print("\n  다음 포스트까지 5초 대기...")
            time.sleep(5)

    # 결과 요약
    print(f"\n{'='*55}")
    print("  발행 결과 요약")
    print(f"{'='*55}")
    for r in results:
        status_icon = "✅" if r["status"] == "발행완료" else "❌"
        print(f"  {status_icon} [{r['status']}] {r['topic']}")
        if r["url"]:
            print(f"       {r['url']}")
