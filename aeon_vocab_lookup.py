import json
import os
import re
import time
from html import unescape
from html.parser import HTMLParser
from typing import Any

import requests


def _get_secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    try:
        import streamlit as st

        return str(st.secrets.get(name, "")).strip()
    except Exception:
        return ""


MW_THESAURUS_KEY = _get_secret("MW_THESAURUS_KEY")
MW_DICTIONARY_KEY = _get_secret("MW_DICTIONARY_KEY")
GROQ_API_KEY = _get_secret("GROQ_API_KEY")

GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"

# CAT/GMAT RC tone categories (from exam prep sources)
TONE_CATEGORIES = (
    "Analytical, Critical, Cynical, Descriptive, Dogmatic, Euphemistic, "
    "Humorous, Informative, Introspective, Laudatory, Narrative, Neutral, "
    "Nostalgic, Optimistic, Pessimistic, Provocative, Sarcastic, Speculative"
)

DICT_ENDPOINT = "https://dictionaryapi.com/api/v3/references/collegiate/json/{word}"
THES_ENDPOINT = "https://dictionaryapi.com/api/v3/references/thesaurus/json/{word}"
REQUEST_TIMEOUT_S = 30
AEON_MAX_RETRIES = 3
MAX_WORDS = 25
MAX_SYNS_PER_WORD = 12

WORD_CLEAN_RE = re.compile(r"[^A-Za-z'\- ]+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Meta/trivial terms to never include (from prompt leakage or non-vocabulary)
BLOCKLIST = frozenset({"word", "words", "json", "article", "text", "return"})


def unique_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    output = []
    for item in items:
        clean = (item or "").strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(clean)
    return output


def _is_suggestions_payload(payload: Any) -> bool:
    return isinstance(payload, list) and (len(payload) == 0 or isinstance(payload[0], str))


def clean_mw_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("{bc}", ": ")
    text = re.sub(r"\{sx\|(.*?)\|.*?\}", r"\1", text)
    text = re.sub(r"\{(?:d_link|a_link)\|([^|}]*).*?\}", r"\1", text)
    text = re.sub(r"\{/?(?:wi|it|b|inf|sup|sc|parahw)\}", "", text)
    text = re.sub(r"\{.*?\}", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text.startswith(": "):
        text = text[2:]
    return text


def normalize_candidate_word(word: str) -> str:
    word = WORD_CLEAN_RE.sub("", (word or "").strip())
    word = re.sub(r"\s+", " ", word).strip(" -'")
    return word


class ArticleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._capture_p = False
        self._capture_title = False
        self._current_p: list[str] = []
        self.paragraphs: list[str] = []
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._capture_title = True
        if tag == "p":
            self._capture_p = True
            self._current_p = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._capture_title = False
        if tag == "p" and self._capture_p:
            paragraph = re.sub(r"\s+", " ", "".join(self._current_p)).strip()
            if len(paragraph) >= 80:
                self.paragraphs.append(paragraph)
            self._capture_p = False
            self._current_p = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._capture_title:
            self.title_parts.append(data)
        if self._capture_p:
            self._current_p.append(data)


def extract_json_ld_article(html: str) -> tuple[str, dict[str, Any]]:
    """Extract article body and metadata from JSON-LD. Returns (body, metadata)."""
    script_pattern = re.compile(
        r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        re.IGNORECASE | re.DOTALL,
    )
    matches = script_pattern.findall(html)
    metadata: dict[str, Any] = {}
    body = ""
    for match in matches:
        raw = unescape(match).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        raw_blocks = data if isinstance(data, list) else [data]
        blocks: list[dict] = []
        for b in raw_blocks:
            if isinstance(b, dict):
                if b.get("@graph"):
                    blocks.extend(b["@graph"])
                else:
                    blocks.append(b)
        for block in blocks:
            if not isinstance(block, dict):
                continue
            b = block.get("articleBody")
            if isinstance(b, str) and len(b.strip()) > 500:
                body = re.sub(r"\s+", " ", b).strip()
            if "wordCount" in block:
                metadata["word_count"] = block["wordCount"]
            if "articleSection" in block:
                metadata["section"] = block["articleSection"]
            if "author" in block:
                auth = block["author"]
                if isinstance(auth, list) and auth:
                    auth = auth[0]
                if isinstance(auth, dict) and "name" in auth:
                    metadata["author"] = auth["name"]
                elif isinstance(auth, str):
                    metadata["author"] = auth
            if "datePublished" in block:
                metadata["date_published"] = block["datePublished"]
    return body, metadata


def extract_genre_from_url(url: str) -> str:
    """Infer content type from Aeon URL path."""
    url_lower = url.lower()
    if "/essays/" in url_lower or url_lower.rstrip("/").endswith("/essays"):
        return "Essays"
    if "/ideas/" in url_lower or url_lower.rstrip("/").endswith("/ideas"):
        return "Ideas"
    if "/videos/" in url_lower or url_lower.rstrip("/").endswith("/videos"):
        return "Videos"
    return "Article"


def extract_topics_from_html(html: str) -> list[str]:
    """Extract topic tags from Aeon article page (links to /philosophy/, /culture/, etc.)."""
    topics: list[str] = []
    # Aeon topic links: /philosophy, /psychology, /science, /society, /culture/architecture, etc.
    for m in re.finditer(r'href=["\']/(philosophy|psychology|science|society|culture)(?:/([a-z\-]+))?["\']', html, re.I):
        main, sub = m.group(1), m.group(2)
        if sub:
            topics.append(sub.replace("-", " ").title())
        else:
            topics.append(main.title())
    return unique_preserve_order(topics)[:8]


def fetch_aeon_article(url: str, session: requests.Session) -> dict[str, Any]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://aeon.co/",
    }
    resp = None
    for attempt in range(1, AEON_MAX_RETRIES + 1):
        resp = session.get(url, timeout=REQUEST_TIMEOUT_S, headers=headers)
        if resp.status_code != 429:
            break
        retry_after = resp.headers.get("Retry-After", "").strip()
        try:
            wait_s = max(1, min(15, int(retry_after)))
        except ValueError:
            wait_s = min(15, attempt * 2)
        time.sleep(wait_s)

    if resp is None:
        raise RuntimeError("Failed to fetch the Aeon article.")

    if resp.status_code == 429:
        mirror_url = f"https://r.jina.ai/http://{url.removeprefix('https://').removeprefix('http://')}"
        mirror_resp = session.get(mirror_url, timeout=REQUEST_TIMEOUT_S)
        if mirror_resp.status_code == 429:
            raise RuntimeError(
                "Aeon is rate-limiting requests right now (HTTP 429). "
                "Please wait a few minutes and try again."
            )
        mirror_resp.raise_for_status()
        mirror_text = re.sub(r"\s+", " ", mirror_resp.text).strip()
        if len(mirror_text) < 500:
            raise RuntimeError(
                "Aeon is rate-limiting requests right now (HTTP 429). "
                "Please wait a few minutes and try again."
            )
        word_count = len(mirror_text.split())
        return {
            "title": url,
            "text": mirror_text,
            "word_count": word_count,
            "genre": extract_genre_from_url(url),
            "section": None,
            "author": None,
            "topics": [],
        }

    resp.raise_for_status()
    html = resp.text
    if "Vercel Security Checkpoint" in html:
        # Fallback mirror often bypasses anti-bot interstitial pages for read access.
        mirror_url = f"https://r.jina.ai/http://{url.removeprefix('https://').removeprefix('http://')}"
        mirror_resp = session.get(mirror_url, timeout=REQUEST_TIMEOUT_S)
        mirror_resp.raise_for_status()
        mirror_text = re.sub(r"\s+", " ", mirror_resp.text).strip()
        if len(mirror_text) < 500:
            raise RuntimeError("Could not extract article content because Aeon returned a security checkpoint.")
        word_count = len(mirror_text.split())
        return {
            "title": url,
            "text": mirror_text,
            "word_count": word_count,
            "genre": extract_genre_from_url(url),
            "section": None,
            "author": None,
            "topics": [],
        }

    parser = ArticleTextParser()
    parser.feed(html)

    title = re.sub(r"\s+", " ", "".join(parser.title_parts)).strip()
    text, ld_meta = extract_json_ld_article(html)
    if not text:
        text = "\n\n".join(parser.paragraphs)

    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 500:
        raise RuntimeError("Could not extract enough article text from the Aeon page.")

    word_count = ld_meta.get("word_count") or len(text.split())
    return {
        "title": title,
        "text": text,
        "word_count": word_count,
        "genre": extract_genre_from_url(url),
        "section": ld_meta.get("section"),
        "author": ld_meta.get("author"),
        "date_published": ld_meta.get("date_published"),
        "topics": extract_topics_from_html(html),
    }


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if len(s.strip()) >= 25]


def parse_json_object_from_text(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("Groq returned an empty response.")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        return json.loads(fence_match.group(1))

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])

    raise ValueError(f"Could not parse JSON from Groq response: {text[:300]}")


def extract_message_text(message: Any) -> str:
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, dict):
        content = message.get("content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            chunks: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    txt = part.get("text")
                    if isinstance(txt, str) and txt.strip():
                        chunks.append(txt.strip())
            return "\n".join(chunks).strip()
    return ""


def request_words_from_groq(prompt: str, session: requests.Session, max_tokens: int) -> dict[str, Any]:
    if not GROQ_API_KEY:
        raise RuntimeError("Missing `GROQ_API_KEY` secret.")
    resp = session.post(
        GROQ_CHAT_COMPLETIONS_URL,
        timeout=REQUEST_TIMEOUT_S,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": GROQ_MODEL,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "reasoning_effort": "low",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return a JSON object with a single key named 'words'. "
                        "Do not include explanations. Keep the response short."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        },
    )
    if resp.status_code == 401:
        raise RuntimeError(
            "Groq API key was rejected with 401 Unauthorized. "
            "Verify the `GROQ_API_KEY` secret."
        )
    if resp.status_code == 400:
        raise RuntimeError(f"Groq request failed with 400 Bad Request: {resp.text}")
    resp.raise_for_status()
    return resp.json()


def extract_uncommon_words(article_text: str, session: requests.Session) -> list[str]:
    prompt = (
        "Role: Expert GMAT/CAT Verbal Tutor specializing in Lexical Precision for Indian Engineering Graduates.\n\n"
        "Target Persona: The user is an Indian Undergraduate with an English-medium engineering background.\n\n"
        "Known: They are comfortable with complex technical/business English (e.g., infrastructure, implementation, optimization).\n\n"
        "Goal: Extract \"Tier 3\" academic and literary words that are likely to appear in GMAT/CAT Reading Comprehension (RC) and Critical Reasoning (CR).\n\n"
        "The Extraction Logic (Zipf & Context):\n"
        "Zipf Scale Threshold: Extract words with a Zipf Scale frequency between 2.5 and 4.0.\n"
        "Exclude Zipf 4.5+: (e.g., efficient, significant, problem, develop). These are too basic.\n"
        "Include Zipf 2.5–4.0: (e.g., equivocal, ephemeral, exacerbate, pragmatic, alacrity). These are the \"Sweet Spot\" for high-level exams.\n\n"
        "Exam-Specific Utility: Prioritize words that define:\n"
        "Authorial Intent/Tone: (e.g., ambivalent, biased, detached, skeptical).\n"
        "Logical Relationships: (e.g., notwithstanding, conversely, underscore).\n"
        "Abstract Concepts: (e.g., paradox, anomaly, dichotomy).\n\n"
        "Strict Filtering Rules:\n"
        "NO basic academic words (e.g., analysis, research, concept).\n"
        "NO pure engineering/STEM jargon (e.g., viscosity, semiconductor, algorithm).\n"
        "NO common corporate \"fluff\" (e.g., leverage, synergy, stakeholder).\n"
        "FOCUS on words that carry specific nuance or have \"trap\" secondary meanings (e.g., arrest meaning to stop a process, plastic meaning moldable).\n\n"
        "Return single words only. Preserve original spelling.\n"
        '- Return JSON only: {"words":["word1","word2",...]}\n\n'
        "Article text:\n"
        f"{article_text}"
    )

    payload = request_words_from_groq(prompt, session, max_tokens=4500)
    choices = payload.get("choices") or []
    first = choices[0] if choices else {}
    content = extract_message_text(first.get("message", {}))

    if not content:
        raise RuntimeError(
            "Groq returned an empty response body. "
            "Try again or use a shorter article."
        )

    try:
        data = parse_json_object_from_text(content)
    except (ValueError, json.JSONDecodeError):
        # Fallback: extract quoted words from ["word1","word2",...]
        raw_words = re.findall(r'"([^"]+)"', content)
        data = {"words": raw_words}

    words = []
    for item in data.get("words", []):
        normalized = normalize_candidate_word(str(item))
        if normalized and normalized.lower() not in BLOCKLIST:
            words.append(normalized)
    return unique_preserve_order(words)


def extract_main_idea_and_tone(article_text: str, session: requests.Session) -> dict[str, str]:
    """Use gpt-oss-20b to extract main idea (under 40 words) and CAT/GMAT tone."""
    prompt = (
        "Analyze this article for GMAT/CAT exam prep.\n\n"
        "Reply with exactly two lines, no other text:\n"
        "MAIN_IDEA: <central argument in exactly under 40 words. Write a complete sentence. Do not cut off mid-sentence.>\n"
        f"TONE: <exactly one word from: {TONE_CATEGORIES}>\n\n"
        "Article:\n"
        f"{article_text}"
    )

    resp = session.post(
        GROQ_CHAT_COMPLETIONS_URL,
        timeout=REQUEST_TIMEOUT_S,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": GROQ_MODEL,
            "temperature": 0.2,
            "max_tokens": 300,
            "reasoning_effort": "low",
            "messages": [
                {"role": "system", "content": "Reply with only MAIN_IDEA: and TONE: lines. Nothing else."},
                {"role": "user", "content": prompt},
            ],
        },
    )
    if resp.status_code != 200:
        return {"main_idea": "", "tone": ""}

    payload = resp.json()
    choices = payload.get("choices") or []
    first = choices[0] if choices else {}
    content = extract_message_text(first.get("message", {}))
    if not content:
        return {"main_idea": "", "tone": ""}

    main_idea = ""
    tone = ""
    for line in content.split("\n"):
        line = line.strip()
        if line.upper().startswith("MAIN_IDEA:"):
            main_idea = line.split(":", 1)[-1].strip()
        elif line.upper().startswith("TONE:"):
            tone = line.split(":", 1)[-1].strip()
    return {"main_idea": main_idea, "tone": tone}


def fetch_thesaurus_info(word: str, session: requests.Session) -> tuple[list[str], list[str], list[str]]:
    """Fetch definitions, examples, and synonyms from thesaurus in one call. Returns (definitions, examples, synonyms)."""
    if not MW_THESAURUS_KEY:
        raise RuntimeError("Missing `MW_THESAURUS_KEY` secret.")
    resp = session.get(
        THES_ENDPOINT.format(word=word),
        params={"key": MW_THESAURUS_KEY},
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()
    payload = resp.json()
    if _is_suggestions_payload(payload):
        return [], [], []

    defs: list[str] = []
    examples: list[str] = []
    syns: list[str] = []

    for entry in payload:
        syn_groups = (entry.get("meta") or {}).get("syns")
        if isinstance(syn_groups, list):
            for group in syn_groups:
                if isinstance(group, list):
                    syns.extend(str(item).strip() for item in group if str(item).strip())

    for entry in payload:
        for def_section in entry.get("def") or []:
            for grouping in def_section.get("sseq") or []:
                for item in grouping:
                    if not isinstance(item, list) or len(item) < 2:
                        continue
                    type_label = item[0]
                    data = item[1]
                    targets = []
                    if type_label in {"sense", "bs"}:
                        targets.append(data)
                    elif type_label == "pseq":
                        for p_item in data:
                            if isinstance(p_item, list) and len(p_item) > 1 and p_item[0] in {"sense", "bs"}:
                                targets.append(p_item[1])

                    for sense_data in targets:
                        for dt_item in sense_data.get("dt") or []:
                            if not isinstance(dt_item, list) or len(dt_item) < 2:
                                continue
                            if dt_item[0] == "text":
                                text = clean_mw_text(dt_item[1])
                                if text:
                                    defs.append(text)
                            elif dt_item[0] == "vis":
                                for vis in dt_item[1]:
                                    text = clean_mw_text(vis.get("t", ""))
                                    if text:
                                        examples.append(text)
    return (
        unique_preserve_order(defs)[:3],
        unique_preserve_order(examples)[:2],
        unique_preserve_order(syns)[:MAX_SYNS_PER_WORD],
    )


def fetch_synonyms(word: str, session: requests.Session) -> list[str]:
    if not MW_THESAURUS_KEY:
        raise RuntimeError("Missing `MW_THESAURUS_KEY` secret.")
    resp = session.get(
        THES_ENDPOINT.format(word=word),
        params={"key": MW_THESAURUS_KEY},
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()
    payload = resp.json()
    if _is_suggestions_payload(payload):
        return []

    syns: list[str] = []
    for entry in payload:
        syn_groups = (entry.get("meta") or {}).get("syns")
        if isinstance(syn_groups, list):
            for group in syn_groups:
                if isinstance(group, list):
                    syns.extend(str(item).strip() for item in group if str(item).strip())
        if len(syns) >= MAX_SYNS_PER_WORD:
            break
    return unique_preserve_order(syns)[:MAX_SYNS_PER_WORD]


def fetch_dictionary_info(word: str, session: requests.Session) -> tuple[list[str], list[str]]:
    """Fetch definitions and examples from Merriam-Webster dictionary. Returns (definitions, examples)."""
    if not MW_DICTIONARY_KEY:
        raise RuntimeError("Missing `MW_DICTIONARY_KEY` secret.")
    resp = session.get(
        DICT_ENDPOINT.format(word=word),
        params={"key": MW_DICTIONARY_KEY},
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()
    payload = resp.json()
    if _is_suggestions_payload(payload):
        return [], []

    defs: list[str] = []
    examples: list[str] = []
    for entry in payload:
        for def_section in entry.get("def") or []:
            for grouping in def_section.get("sseq") or []:
                for item in grouping:
                    if not isinstance(item, list) or len(item) < 2:
                        continue
                    type_label = item[0]
                    data = item[1]
                    targets = []
                    if type_label in {"sense", "bs"}:
                        targets.append(data)
                    elif type_label == "pseq":
                        for p_item in data:
                            if isinstance(p_item, list) and len(p_item) > 1 and p_item[0] in {"sense", "bs"}:
                                targets.append(p_item[1])
                    for sense_data in targets:
                        for dt_item in sense_data.get("dt") or []:
                            if not isinstance(dt_item, list) or len(dt_item) < 2:
                                continue
                            if dt_item[0] == "text":
                                text = clean_mw_text(dt_item[1])
                                if text:
                                    defs.append(text)
                            elif dt_item[0] == "vis":
                                for vis in dt_item[1]:
                                    text = clean_mw_text(vis.get("t", ""))
                                    if text:
                                        examples.append(text)
    return unique_preserve_order(defs)[:3], unique_preserve_order(examples)[:2]


def fallback_article_example(word: str, article_sentences: list[str]) -> str:
    pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
    for sentence in article_sentences:
        if pattern.search(sentence):
            return sentence
    return ""


def build_vocab_report(url: str) -> dict[str, Any]:
    with requests.Session() as session:
        article = fetch_aeon_article(url, session)
        analysis = extract_main_idea_and_tone(article["text"], session)
        words = extract_uncommon_words(article["text"], session)
        article_sentences = split_sentences(article["text"])

        entries = []
        for word in words:
            try:
                thesaurus_defs, thesaurus_examples, synonyms = fetch_thesaurus_info(word, session)
            except Exception as exc:
                thesaurus_defs, thesaurus_examples, synonyms = [], [], []
                synonyms = [f"Merriam-Webster thesaurus lookup failed: {exc}"]

            definition = thesaurus_defs[0] if thesaurus_defs else ""
            examples = thesaurus_examples

            if not examples:
                article_example = fallback_article_example(word, article_sentences)
                if article_example:
                    examples = [article_example]

            if not definition or not examples:
                try:
                    dict_defs, dict_examples = fetch_dictionary_info(word, session)
                    if not definition and dict_defs:
                        definition = dict_defs[0]
                    if not examples:
                        if dict_examples:
                            examples = dict_examples
                        elif definition:
                            examples = [f"Definition: {definition}"]
                except Exception:
                    pass

            entries.append(
                {
                    "word": word,
                    "example_usage": examples,
                    "synonyms": synonyms,
                    "definition": definition,
                }
            )

    return {
        "article_url": url,
        "article_title": article["title"],
        "main_idea": analysis.get("main_idea", ""),
        "tone": analysis.get("tone", ""),
        "word_count": article.get("word_count"),
        "genre": article.get("genre"),
        "section": article.get("section"),
        "author": article.get("author"),
        "date_published": article.get("date_published"),
        "topics": article.get("topics") or [],
        "model": GROQ_MODEL,
        "entries": entries,
    }


def print_report(report: dict[str, Any]) -> None:
    print(f"Article: {report['article_title']}")
    print(f"URL: {report['article_url']}")
    if report.get("main_idea"):
        print(f"Main idea: {report['main_idea']}")
    if report.get("tone"):
        print(f"Tone: {report['tone']}")
    meta = []
    if report.get("word_count"):
        meta.append(f"{report['word_count']} words")
    if report.get("genre"):
        meta.append(report["genre"])
    if report.get("section"):
        meta.append(report["section"])
    if report.get("author"):
        meta.append(f"by {report['author']}")
    if report.get("date_published"):
        meta.append(report["date_published"][:10])
    if report.get("topics"):
        meta.append(", ".join(report["topics"]))
    if meta:
        print(" | ".join(meta))
    print()
    for index, entry in enumerate(report["entries"], start=1):
        print(f"{index}. {entry['word']}")
        print("   Example usage:")
        if entry["example_usage"]:
            for example in entry["example_usage"]:
                print(f"   - {example}")
        else:
            print("   - (none found)")

        print("   Synonyms:")
        if entry["synonyms"]:
            print(f"   - {', '.join(entry['synonyms'])}")
        else:
            print("   - (none found)")
        print()


def main() -> None:
    url = input("Enter Aeon article URL: ").strip()
    if not url:
        raise SystemExit("Error: No URL provided.")

    try:
        report = build_vocab_report(url)
    except Exception as exc:
        raise SystemExit(f"Error: {exc}") from exc

    print_report(report)


if __name__ == "__main__":
    main()
