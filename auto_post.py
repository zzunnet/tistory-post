"""
Claude·Gemini 대화 기반 티스토리 자동 포스팅 (Gemini 2.0 Flash)
사용법: python auto_post.py
사전 준비: .env 파일에 GEMINI_API_KEY, KAKAO_EMAIL, KAKAO_PASSWORD 설정
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import os
import glob
import hashlib
import json
import re
import time
import urllib.parse
from pathlib import Path
from dotenv import load_dotenv
import requests

load_dotenv()  # .env 파일에서 키 로드

from google import genai
from playwright.sync_api import sync_playwright

# ─────────────────────────────────────────
# 설정 (여기만 수정)
# ─────────────────────────────────────────
KAKAO_EMAIL    = os.environ["KAKAO_EMAIL"]
KAKAO_PASSWORD = os.environ["KAKAO_PASSWORD"]
BLOG_NAME      = "zzun"                 # zzun.tistory.com
DEFAULT_CATEGORY = "IT/개발"           # 카테고리 미결정 시 기본값

# 블로그에 실제 존재하는 카테고리 목록 (자동 선택에 활용)
BLOG_CATEGORIES = [
    "IT/개발", "IT/보안", "IT/면접",
    "일상",
    "여러가지/경제",
    "여행",
    "리뷰/잡화", "리뷰/놀이시설", "리뷰/영화", "리뷰/장난감",
    "사진",
]

MAX_SESSIONS        = 5    # 참고할 최근 Claude 세션 수
MAX_MSG_PER_SESSION = 30   # 세션당 최대 메시지 수
MAX_GEMINI_SESSIONS = 5    # 참고할 최근 Gemini 세션 수
MAX_POSTS           = 3    # 1회 실행 시 발행할 포스트 수
POSTED_LOG_FILE     = "posted_topics.json"   # 발행 기록 파일
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
# 발행 기록 관리 (중복 방지)
# ──────────────────────────────────────────────────
def load_posted_topics() -> list[str]:
    """이전에 발행된 주제 목록을 불러옵니다."""
    if os.path.exists(POSTED_LOG_FILE):
        try:
            return json.loads(Path(POSTED_LOG_FILE).read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_posted_topic(topic: str):
    """발행된 주제를 기록합니다 (최근 100개 유지)."""
    topics = load_posted_topics()
    if topic not in topics:
        topics.append(topic)
    Path(POSTED_LOG_FILE).write_text(
        json.dumps(topics[-100:], ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# ──────────────────────────────────────────────────
# 이미지 검색 (Wikipedia API → Picsum fallback)
# ──────────────────────────────────────────────────
def _picsum_url(keyword: str, width: int = 800, height: int = 420) -> str:
    """키워드를 시드로 결정론적 Picsum 이미지 URL 반환 (최후 fallback용)."""
    seed = int(hashlib.md5(keyword.encode()).hexdigest(), 16) % 1000
    return f"https://picsum.photos/seed/{seed}/{width}/{height}"


def _unsplash_url(query: str, width: int = 800, height: int = 420) -> str | None:
    """Unsplash Source API로 키워드 기반 관련 이미지 URL 반환.
    실제 요청을 보내 최종 리다이렉트 URL을 확인한 뒤 반환합니다.
    """
    keywords = ",".join(query.split()[:5])  # 최대 5단어
    encoded = urllib.parse.quote(keywords)
    url = f"https://source.unsplash.com/{width}x{height}/?{encoded}"
    try:
        r = requests.get(url, timeout=8, allow_redirects=True,
                         headers={"User-Agent": "tistory-autopost/1.0"})
        if r.status_code == 200 and "image" in r.headers.get("content-type", ""):
            return r.url  # 실제 이미지 URL (리다이렉트 후)
    except Exception:
        pass
    return None


# Commons 검색에서 제외할 비관련 파일명 패턴 (지도, 차트, 다이어그램 등)
_COMMONS_SKIP_PATTERNS = {
    "map", "world", "distribution", "chart", "graph", "flag",
    "locator", "globe", "diagram", "template", "blank",
}


def fetch_image_url(query: str) -> str:
    """검색어로 관련 이미지 URL을 가져옵니다.
    우선순위: Commons 파일 → Wikipedia 직접 조회 → Wikipedia 검색 → Unsplash → Picsum
    """
    hdrs = {"User-Agent": "tistory-autopost/1.0"}
    query_keywords = set(query.lower().split())

    def _wiki_img_by_title(api_url: str, title: str) -> str | None:
        """Wikipedia 문서 제목으로 대표 이미지 URL 반환 (리다이렉트 추적)."""
        try:
            r = requests.get(api_url, params={
                "action": "query", "titles": title, "redirects": 1,
                "prop": "pageimages", "pithumbsize": 800, "format": "json",
            }, timeout=6, headers=hdrs)
            for page in r.json().get("query", {}).get("pages", {}).values():
                if page.get("pageid", -1) != -1:
                    src = page.get("thumbnail", {}).get("source")
                    if src:
                        # 지도/차트 썸네일은 제외
                        src_lower = src.lower()
                        if any(p in src_lower for p in _COMMONS_SKIP_PATTERNS):
                            return None
                        return src
        except Exception:
            pass
        return None

    def _commons_img(query: str) -> str | None:
        """Wikimedia Commons 파일 검색으로 이미지 URL 반환."""
        try:
            r = requests.get("https://commons.wikimedia.org/w/api.php", params={
                "action": "query", "list": "search",
                "srsearch": query, "srnamespace": "6",  # 파일 네임스페이스
                "srlimit": 10, "format": "json",
            }, timeout=6, headers=hdrs)
            results = r.json().get("query", {}).get("search", [])
            if not results:
                return None

            # 관련성 정렬: 제목에 쿼리 키워드 많이 포함된 것 우선
            scored = []
            for hit in results:
                title_lower = hit["title"].lower()
                # 비관련 파일 제외 (지도, 차트, 다이어그램 등)
                if any(p in title_lower for p in _COMMONS_SKIP_PATTERNS):
                    continue
                score = len(query_keywords & set(title_lower.split()))
                scored.append((score, hit))
            scored.sort(key=lambda x: x[0], reverse=True)

            for _, hit in scored:
                file_title = hit["title"]
                # 비미디어 파일 제외 (.pdf, .tiff, .ogg 등)
                ext = file_title.rsplit(".", 1)[-1].lower()
                if ext not in ("jpg", "jpeg", "png", "gif", "webp", "svg"):
                    continue
                r2 = requests.get("https://commons.wikimedia.org/w/api.php", params={
                    "action": "query", "titles": file_title,
                    "prop": "imageinfo", "iiprop": "url", "iiurlwidth": "800",
                    "format": "json",
                }, timeout=6, headers=hdrs)
                for page in r2.json().get("query", {}).get("pages", {}).values():
                    ii = page.get("imageinfo", [])
                    if ii:
                        url = ii[0].get("thumburl") or ii[0].get("url", "")
                        if url and url.startswith("http"):
                            return url
        except Exception as e:
            print(f"      Commons 검색 오류: {e}")
        return None

    # 1단계: Wikimedia Commons 파일 직접 검색 (영화 포스터, 로고, 랜드마크 등)
    src = _commons_img(query)
    if src:
        print(f"    이미지(Commons): {query[:30]} → {src[:70]}...")
        return src

    # 2단계: Wikipedia 문서 직접 조회 (정확한 제목)
    for api_url in [
        "https://en.wikipedia.org/w/api.php",
        "https://ko.wikipedia.org/w/api.php",
    ]:
        try:
            src = _wiki_img_by_title(api_url, query)
            if src:
                print(f"    이미지(Wikipedia 직접): {query[:30]} → {src[:70]}...")
                return src

            # 3단계: Wikipedia 검색 fallback
            r = requests.get(api_url, params={
                "action": "query", "list": "search",
                "srsearch": query, "srlimit": 5, "format": "json",
            }, timeout=6, headers=hdrs)
            results = r.json().get("query", {}).get("search", [])
            sorted_r = sorted(
                results,
                key=lambda h: len(query_keywords & set(h["title"].lower().split())),
                reverse=True
            )
            for hit in sorted_r:
                src = _wiki_img_by_title(api_url, hit["title"])
                if src:
                    print(f"    이미지(Wikipedia 검색): {hit['title'][:30]} → {src[:70]}...")
                    return src
        except Exception as e:
            print(f"    Wikipedia 검색 오류 ({api_url.split('/')[2][:15]}): {e}")

    # 4단계: Unsplash (키워드 기반 실제 관련 사진)
    src = _unsplash_url(query)
    if src:
        print(f"    이미지(Unsplash): {query[:30]} → {src[:70]}...")
        return src

    # 최종 fallback: Picsum
    url = _picsum_url(query)
    print(f"    이미지 fallback (Picsum): {url}")
    return url


def build_content_with_images(content_html: str, image_queries: list[str]) -> str:
    """본문 HTML의 h2 섹션 뒤에 image_queries에 맞는 이미지를 삽입합니다.
    image_queries: Gemini가 제안한 섹션별 이미지 검색어 목록
    """
    parts = re.split(r'(<h2[^>]*>.*?</h2>)', content_html, flags=re.IGNORECASE)
    if not image_queries:
        return content_html

    # h2가 없으면 본문 앞에 첫 번째 이미지만 삽입
    if len(parts) <= 1:
        img_url = fetch_image_url(image_queries[0])
        return (
            f'<figure style="text-align:center;margin:24px 0;">'
            f'<img src="{img_url}" alt="{image_queries[0]}" '
            f'style="max-width:100%;border-radius:10px;" /></figure>\n'
        ) + content_html

    result = []
    h2_count = 0
    # 모든 h2 섹션에 이미지 삽입 (image_queries가 충분하면), 최대 4개
    for part in parts:
        result.append(part)
        if re.match(r'<h2', part, re.IGNORECASE):
            h2_count += 1
            # 쿼리 순환 사용: 쿼리 수보다 h2가 많으면 쿼리를 재활용
            query = image_queries[(h2_count - 1) % len(image_queries)]
            img_url = fetch_image_url(query)
            alt = re.sub(r'<[^>]+>', '', part).strip()[:40]
            result.append(
                f'<figure style="text-align:center;margin:20px 0 28px;">'
                f'<img src="{img_url}" alt="{alt}" '
                f'style="max-width:100%;border-radius:10px;" /></figure>\n'
            )
    return "".join(result)


# ──────────────────────────────────────────────────
# 공통: Gemini 호출 헬퍼
# ──────────────────────────────────────────────────
def _claude_fallback_call(prompt: str) -> str:
    """Gemini quota 소진 시 Claude API (claude-haiku-4-5)로 fallback 호출."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 없음")
    import anthropic
    print("    [claude-haiku-4-5] fallback 호출 중...")
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def _gemini_call(client, prompt: str) -> str:
    """quota 소진 시 Gemini 모델 순서로 호출, 모두 실패 시 65초 대기 후 재시도."""
    models = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-2.5-flash"]
    max_rounds = 3  # 전체 모델 순환 최대 횟수
    for round_no in range(max_rounds):
        all_quota = True
        for model_name in models:
            try:
                print(f"    [{model_name}] 호출 중...")
                resp = client.models.generate_content(model=model_name, contents=prompt)
                return resp.text.strip()
            except Exception as e:
                err = str(e)
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    print(f"    [{model_name}] quota 소진, 다음 모델 시도...")
                    continue
                elif "404" in err or "NOT_FOUND" in err:
                    print(f"    [{model_name}] 모델 없음, 스킵")
                    continue
                else:
                    raise
        # 이번 라운드 모든 모델 quota 소진 → 잠시 대기 후 재시도
        if round_no < max_rounds - 1:
            wait_sec = 65
            print(f"    모든 모델 quota 소진 → {wait_sec}초 대기 후 재시도 ({round_no+1}/{max_rounds-1})...")
            time.sleep(wait_sec)
    # 모든 재시도 실패 → Claude fallback
    print("    모든 Gemini quota 소진 → Claude API fallback")
    return _claude_fallback_call(prompt)


def _parse_json(text: str) -> dict:
    """마크다운 제거 후 JSON 파싱. 실패 시 정규식 fallback."""
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$', '', text, flags=re.MULTILINE)
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        raise ValueError(f"JSON 추출 실패:\n{text[:400]}")
    raw = m.group()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # content 필드 안의 HTML을 별도 추출 후 재조립
    try:
        title_m   = re.search(r'"title"\s*:\s*"([^"]*)"', raw)
        # content: "..." 사이를 greedy로 추출 (tags 앞까지)
        content_m = re.search(r'"content"\s*:\s*"([\s\S]*?)"\s*,\s*"tags"', raw)
        tags_m    = re.search(r'"tags"\s*:\s*"([^"]*)"', raw)
        cat_m     = re.search(r'"category"\s*:\s*"([^"]*)"', raw)
        iq_m      = re.search(r'"image_queries"\s*:\s*(\[[^\]]*\])', raw)

        if title_m and content_m and tags_m:
            content_str = content_m.group(1).replace('\\"', '"')
            img_queries = []
            if iq_m:
                try:
                    img_queries = json.loads(iq_m.group(1))
                except Exception:
                    pass
            return {
                "title":         title_m.group(1),
                "content":       content_str,
                "tags":          tags_m.group(1),
                "category":      cat_m.group(1) if cat_m else "IT/개발",
                "image_queries": img_queries,
            }
    except Exception:
        pass

    raise ValueError(f"JSON 파싱 실패:\n{raw[:400]}")


# ──────────────────────────────────────────────────
# Step 2a. 대화에서 독립 주제 목록 추출
# ──────────────────────────────────────────────────
def analyze_topics(conv_texts: list[str], n: int = MAX_POSTS,
                   previously_posted: list[str] | None = None) -> list[dict]:
    """대화 전체를 분석해 블로그 포스트로 쓸 만한 독립 주제 n개를 반환합니다.
    previously_posted: 이미 발행된 주제 목록 (유사 주제 제외용)
    반환: [{"topic": "...", "focus": "...", "category": "IT/개발|IT/보안"}, ...]
    """
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    combined = "\n\n".join(conv_texts[:60])
    if len(combined) > 18000:
        combined = combined[:18000] + "\n\n...(이하 생략)"

    avoid_section = ""
    if previously_posted:
        avoid_list = "\n".join(f"- {t}" for t in previously_posted[-30:])
        avoid_section = f"""
이미 포스팅된 주제 (이것과 유사하거나 겹치는 주제는 절대 선택 금지):
{avoid_list}
"""

    cat_list = "\n".join(f"- {c}" for c in BLOG_CATEGORIES)

    # 비IT 카테고리를 최소 몇 개 요구할지 계산
    non_it_required = max(1, n - 1)  # IT계열은 최대 1개, 나머지는 비IT

    prompt = f"""당신은 광고 수익과 트래픽을 최적화하는 블로그 편집장입니다.
아래 대화 기록을 분석해 Google AdSense 수익과 검색 유입에 유리한 블로그 포스트 주제 {n}개를 선정하세요.

[필수 조건 — 반드시 지킬 것]
1. {n}개 모두 서로 다른 카테고리여야 합니다
2. IT 관련 카테고리(IT/개발·IT/보안·IT/면접)는 합쳐서 최대 1개만 허용
3. 나머지 {non_it_required}개는 비IT 카테고리(일상·여행·리뷰·스크랩북·사진)에서 선택
4. AdSense CPC가 높고 검색량이 많은 주제를 우선 선택하세요
   고수익 카테고리 예시: 재테크/투자, 여행 후기, 제품 리뷰, 육아, 건강, 맛집
   고트래픽 주제 예시: "XX 후기", "XX 추천", "XX 비교", "XX 방법"
5. 비IT 주제는 대화에서 직접 언급 없어도 됩니다 — 필자의 라이프스타일에서 자유롭게 추론하세요
6. 순수 JSON 배열만 반환 (마크다운·설명 없이)
7. 각 항목: {{"topic": "주제명(20자 이내)", "focus": "이 포스트에서 집중할 핵심 내용(100자 이내)", "category": "아래 목록 중 정확히 하나"}}
8. 개인 이름, 회사명, 이메일, API 키, 비밀번호 등 개인·기밀 정보 관련 주제 금지{avoid_section}

[카테고리 정의]
{cat_list}

카테고리별 기준 및 고수익 주제 예시:
- IT/개발: 소스코드, 라이브러리, 배포 기술 (최대 1개)
- IT/보안: 암호화, PKI, 보안 취약점
- IT/면접: 개발자 면접, 이력서 팁
- 일상: 개발자 루틴, 생산성 도구, 취미 생활 → "직장인 재테크 루틴", "개발자 부업 방법"
- 여러가지/경제: 주식, 부동산, 재테크 → "ETF 투자 방법", "청약 당첨 전략" (CPC 높음)
- 여행: 여행지 후기, 맛집, 숙박 → "XX 여행 코스", "항공권 싸게 사는 법"
- 리뷰/잡화: 전자기기, 생활용품 → "XX 한달 사용 후기", "가성비 XX 추천"
- 리뷰/영화: 최신 영화·드라마 → "XX 결말 해석", "OTT 추천 영화"
- 리뷰/놀이시설: 테마파크, 전시회 → "롯데월드 어른 후기", "전시회 관람 팁"
- 리뷰/장난감: 레고, 피규어, 보드게임 → "XX 구매 후기", "어른 취미 레고 추천"
- 사진: 스마트폰 사진, 촬영 팁

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

    category_str = topic.get('category', 'IT/개발')

    # 대화에서 YouTube 채널/영상 URL 추출 (있으면 프롬프트에 전달)
    yt_urls = re.findall(
        r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w\-]{11}[^\s]*',
        "\n".join(combined.split("\n")[:200])
    )
    yt_section = ""
    if yt_urls:
        yt_section = (
            "\n\n참고할 수 있는 YouTube 링크 (관련 있으면 본문 iframe 또는 링크로 자연스럽게 포함):\n"
            + "\n".join(yt_urls[:3])
        )

    prompt = f"""당신은 다양한 분야의 블로그 작가입니다.
아래 지정된 주제 하나에만 집중하여 블로그 포스트를 작성하세요.

[작성 주제]
- 주제명: {topic.get('topic', '')}
- 핵심 포커스: {topic.get('focus', '')}
- 카테고리: {category_str}

[중요 규칙]
1. 순수 JSON 객체만 반환 (마크다운 코드블록 없이)
2. content 필드의 HTML 안에서 큰따옴표(") 사용 금지 → 작은따옴표(') 사용
3. content 필드의 HTML 안에서 역슬래시(\\) 사용 금지
4. JSON 이외의 텍스트 일절 없이
5. 위 주제 외 다른 주제 내용 포함 금지
6. 실제 사람 이름, 이메일 주소, API 키, 비밀번호, 인증 토큰 등 개인정보·기밀정보 절대 포함 금지

반환 형식:
{{"title": "제목 (60자 이내)", "content": "HTML 본문 (h2/h3/p/ul/li/strong/em/code 태그, 최소 1500자, 큰따옴표 금지)", "tags": "태그1,태그2,...,태그10", "category": "{category_str}", "image_queries": ["섹션1 이미지 검색어(영어)", "섹션2 이미지 검색어(영어)"]}}

image_queries 작성 기준:
- 반드시 영어로 작성 (Wikimedia Commons + Wikipedia + Unsplash 검색용)
- Wikimedia Commons/Wikipedia에 실제 존재하는 이미지 우선 (고유명사·공식 명칭)
  → 없으면 Unsplash에서 키워드 사진으로 대체하므로, 구체적 사물/장면 묘사도 OK
- 지도(map), 차트(chart), 도표(diagram), 국기(flag) 류는 절대 사용 금지
  (이유: 검색 결과에 세계지도·국가지도가 나와 내용과 무관한 이미지가 됨)
- 카테고리별 예시:
  리뷰/영화: "Parasite (film)", "Avengers Endgame", "Squid Game"
  여행: "Gyeongbokgung", "Jeju Island", "Anfield", "Tokyo Shibuya crossing"
  IT/개발: "Python (programming language)", "Docker (software)", "FastAPI"
  일상: "Standing desk", "mechanical keyboard workspace", "coffee laptop desk"
  재테크/경제: "stock market trading screen", "gold coins investment", "piggy bank savings", "korean won banknote"
  세금/절세: "tax return documents form", "calculator pen notebook finance", "income tax paperwork"
  리뷰/잡화: "MacBook Pro", "Sony WH-1000XM5", "iPhone 15"
  리뷰/놀이시설: "Lotte World", "Universal Studios Japan"
  리뷰/영화: "movie theater popcorn", "film clapperboard", "cinema screen"
  사진/카메라: "camera lens photography", "DSLR camera"
- 한국 고유 주제(연말정산·청약·재테크 등)는 구체적 영문 고유명사 대신
  해당 개념을 잘 나타내는 사물/장면 묘사 영어 키워드를 사용하세요
  예: 연말정산 → "tax return documents form", "calculator coins money desk"
      청약 → "apartment building exterior", "housing lottery"
      재테크 → "investment portfolio stock", "gold bars finance"
- 4개 제공 (각 h2 섹션마다 1개씩 삽입)
- 각 쿼리는 해당 섹션 내용과 직접 관련된 키워드여야 함
- 같은 쿼리 반복 금지, 섹션마다 다른 관점의 이미지 제공

작성 지침:
- 서론 → 본론(3~4섹션, 각 섹션은 <h2> 태그로 시작) → 결론 구조
- 카테고리 {category_str}에 어울리는 톤과 내용 (IT 카테고리면 기술적, 여행/일상이면 감성적·실용적)
- 독자에게 실질적으로 도움이 되는 인사이트 포함
- 날짜/시간 정보 포함 금지{yt_section}

=== 참고 대화 내용 ===
{combined}"""

    text = _gemini_call(client, prompt)
    data = _parse_json(text)

    title         = data['title']
    content       = data['content']
    tags          = data['tags']
    category      = data.get('category', category_str)
    image_queries = data.get('image_queries') or []

    # image_queries가 없으면 주제명으로 fallback
    if not image_queries:
        image_queries = [topic.get('topic', title), topic.get('topic', title) + " illustration"]

    print(f"  제목: {title}")
    print(f"  카테고리: {category}")
    print(f"  태그: {tags[:60]}")
    print(f"  이미지 검색어: {image_queries}")

    # 본문에 이미지 삽입
    print(f"  이미지 검색 중...")
    content = build_content_with_images(content, image_queries)

    print(f"  본문: {len(content)}자 (이미지 포함)")
    return title, content, tags, category, image_queries


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
    티스토리 드롭다운 구조:
      - 상위 카테고리: aria-label="IT"
      - 하위 카테고리: aria-label="- 보안"  (대시+공백 접두사)
    "IT/보안" → 먼저 "- 보안" 시도, 실패 시 "IT" 시도
    "일상" → "일상" 직접 시도
    """
    try:
        # 카테고리 버튼 찾기
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

        parts = [p.strip() for p in category.split("/")]
        # 시도할 aria-label 후보: 하위 → 상위 → 전체명 순
        if len(parts) >= 2:
            candidates = [f"- {parts[1]}", parts[1], parts[0], category]
        else:
            candidates = [parts[0]]

        clicked_label = None
        for label in candidates:
            clicked = page.evaluate(
                """
                (label) => {
                    const el = document.querySelector('[role="option"][aria-label="' + label + '"]');
                    if (el) { el.click(); return true; }
                    return false;
                }
                """,
                label
            )
            if clicked:
                clicked_label = label
                break

        time.sleep(0.5)
        if clicked_label:
            print(f"  카테고리 선택: '{clicked_label}'")
        else:
            print(f"  카테고리 항목 없음: '{category}' (후보: {candidates})")

    except Exception as e:
        print(f"  카테고리 선택 오류: {e}")


def _download_image(url: str) -> str | None:
    """URL에서 이미지를 임시 파일로 다운로드. 경로 반환, 실패 시 None."""
    import tempfile
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "tistory-autopost/1.0"})
        if r.status_code == 200 and "image" in r.headers.get("content-type", ""):
            suffix = ".jpg" if "jpeg" in r.headers.get("content-type", "") else ".png"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(r.content)
                return f.name
    except Exception as e:
        print(f"    이미지 다운로드 실패: {e}")
    return None


def post_to_tistory(title: str, content: str, tags: str,
                    category: str = "IT/개발", thumbnail_url: str | None = None):
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

        # 8b. 대표이미지 업로드
        # 구조: div.box_thumb > div.inner_box > input.inp_g[type=file]
        tmp_thumb = None
        if thumbnail_url:
            tmp_thumb = _download_image(thumbnail_url)
        if tmp_thumb:
            try:
                print("  대표이미지 업로드 시도...")
                # box_thumb 안의 file input에 직접 파일 설정 (클릭 불필요)
                file_inp = page.locator(".box_thumb input[type='file']")
                if file_inp.count() == 0:
                    # fallback: 모든 file input 중 마지막
                    file_inp = page.locator("input[type='file']").last
                file_inp.set_input_files(tmp_thumb)
                time.sleep(2)
                print("  대표이미지 업로드 완료")
            except Exception as e:
                print(f"  대표이미지 업로드 오류: {e}")
            finally:
                import os as _os
                if _os.path.exists(tmp_thumb):
                    _os.unlink(tmp_thumb)

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

    # Step 2a: 주제 목록 추출 (이전 발행 주제 중복 제외)
    posted_topics = load_posted_topics()
    print(f"\n🔍 Step 2a: 주제 분석 ({MAX_POSTS}개 추출, 기발행 {len(posted_topics)}개 제외)")
    topics = analyze_topics(conv_texts, n=MAX_POSTS, previously_posted=posted_topics)

    # Step 2b + 3: 주제별 포스트 생성 & 발행
    results = []
    for i, topic in enumerate(topics, 1):
        print(f"\n{'='*55}")
        print(f"  [{i}/{len(topics)}] 주제: {topic.get('topic','')}")
        print(f"{'='*55}")

        print(f"\n✍️  Step 2b: 포스트 생성")
        try:
            title, content, tags, category, image_queries = generate_blog_post(topic, conv_texts)
        except Exception as e:
            print(f"  ❌ 생성 실패: {e}")
            results.append({"topic": topic.get("topic"), "status": "생성실패", "url": None})
            continue

        # 첫 번째 이미지 검색어로 대표이미지 URL 결정
        thumbnail_url = fetch_image_url(image_queries[0]) if image_queries else None

        print(f"\n🚀 Step 3: 티스토리 포스팅")
        try:
            url = post_to_tistory(title, content, tags, category, thumbnail_url=thumbnail_url)
            save_posted_topic(topic.get("topic", title))
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
