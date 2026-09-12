# ============================================================
#      AI KNOWLEDGE CHATBOT (LLM-powered, via Groq + Tavily)
# ============================================================
#
# This replaces the old CSV/TF-IDF domain routing with a call
# to Groq's LLM. For questions that look time-sensitive (current
# officeholders, "today", "latest", prices, news, etc.), it first
# does a live web search via Tavily and feeds those results to
# the LLM as context, so answers reflect current information
# instead of only what the model learned during training.
#
# Personal info memory (name/age) and instant greeting/thanks
# responses are kept as-is: they're free, instant, and don't
# need to burn an API call.
# ============================================================

import os
import re
import json

from groq import Groq
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None


# ============================================================
# CONFIGURATION
# ============================================================

PROFILE_FILE = "user_profile.json"

# You can override the model via a GROQ_MODEL environment
# variable without touching code. See console.groq.com/docs/models
# for the current list of available free models.
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

_groq_client = None
_tavily_client = None


def get_groq_client():
    """Lazily create the Groq client so importing this module
    doesn't fail just because GROQ_API_KEY isn't set yet (e.g.
    during local testing of unrelated features)."""
    global _groq_client
    if _groq_client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add it as an environment "
                "variable (locally and on Render) before asking a "
                "knowledge question."
            )
        _groq_client = Groq(api_key=api_key)
    return _groq_client


def get_tavily_client():
    """Lazily create the Tavily client. Returns None (rather than
    raising) if TAVILY_API_KEY isn't set or the package isn't
    installed, so the chatbot still works without web search —
    it just won't have live/current information."""
    global _tavily_client
    if TavilyClient is None:
        return None
    if _tavily_client is None:
        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            return None
        _tavily_client = TavilyClient(api_key=api_key)
    return _tavily_client


# ============================================================
# LOAD / SAVE USER PROFILE
# ============================================================

def load_user_profile():
    if not os.path.exists(PROFILE_FILE):
        return {}
    try:
        with open(PROFILE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_user_profile(profile):
    try:
        with open(PROFILE_FILE, "w", encoding="utf-8") as file:
            json.dump(profile, file, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Could not save profile: {e}")


user_profile = load_user_profile()


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize_text(text):
    text = str(text).lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def name_prefix():
    name = user_profile.get("name")
    if name:
        return f", {name}"
    return ""


# ============================================================
# GREETINGS / THANKS / GOODBYE
# ============================================================

def is_greeting(text):
    text = normalize_text(text)
    greetings = {
        "hi", "hello", "hey", "hii", "hiii", "helo",
        "good morning", "good afternoon", "good evening", "howdy",
    }
    return text in greetings


def is_thanks(text):
    text = normalize_text(text)
    thanks_words = {"thanks", "thank you", "thankyou", "thx", "ty"}
    return text in thanks_words


def is_goodbye(text):
    text = normalize_text(text)
    goodbye_words = {"bye", "goodbye", "good bye", "exit", "quit"}
    return text in goodbye_words


# ============================================================
# PERSONAL INFORMATION
# ============================================================

def handle_personal_information(question):
    text = normalize_text(question)

    if (
        "what do you know about me" in text
        or "what you know about me" in text
        or "tell me what you know about me" in text
    ):
        facts = []
        if user_profile.get("name"):
            facts.append(f"your name is {user_profile['name']}")
        if user_profile.get("age"):
            facts.append(f"you are {user_profile['age']} years old")
        if user_profile.get("studies"):
            facts.append(f"you are studying {user_profile['studies']}")
        if user_profile.get("university"):
            facts.append(f"you study at {user_profile['university']}")
        interests = user_profile.get("interests", [])
        if interests:
            facts.append("you are interested in " + " and ".join(interests))
        if not facts:
            return (
                "I don't know much about you yet. 😊 "
                "You can tell me your name, age, studies, "
                "university, or interests."
            )
        return "Here's what I remember about you: " + ", ".join(facts) + ". 😊"

    return None


# ============================================================
# PROFILE FACT EXTRACTION (LLM-based — replaces rigid regex)
# ============================================================
#
# Instead of matching narrow, hand-written patterns like "my name is
# X" (which breaks on typos, different phrasing, multiple facts in
# one message, or Roman Urdu), this asks the LLM itself to read the
# message and pull out any personal facts as JSON. Much more robust,
# works in any language/phrasing, and can catch several facts from a
# single message at once.

PROFILE_EXTRACTION_PROMPT = (
    "You extract personal profile facts from a single chat message. "
    "The message may be in English, Roman Urdu, or a mix, and may "
    "contain typos or casual phrasing — interpret it flexibly. "
    "Look for: the user's name, age (a whole number), what they are "
    "studying (a degree, subject, or field), their university or "
    "college name, and any hobbies or interests they mention. "
    "Respond with ONLY a compact JSON object containing exactly the "
    "keys that are clearly and explicitly stated in THIS message — "
    "omit any key that isn't mentioned. Valid keys: \"name\", "
    "\"age\" (integer), \"studies\", \"university\", \"interests\" "
    "(a list of strings). If nothing personal is stated, respond "
    "with an empty JSON object: {}. Do not guess or infer anything "
    "that wasn't explicitly said. Never include any text besides "
    "the JSON object itself — no explanation, no markdown fences."
)


def extract_profile_updates_with_llm(message):
    """Reads a single message and returns a dict of any personal
    facts (name/age/studies/university/interests) explicitly stated
    in it — can be empty. Never raises; returns {} on any failure.

    Robustness notes: some reasoning-style models occasionally add
    stray text around the JSON, or get cut off mid-object. This tries
    Groq's strict JSON mode first (forces valid JSON when supported),
    falls back to a plain call if that's rejected, and finally pulls
    out just the {...} substring before parsing either way — so a
    wrapped or slightly malformed response still parses correctly."""
    client = get_groq_client()

    def call_groq(use_json_mode):
        kwargs = dict(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": PROFILE_EXTRACTION_PROMPT},
                {"role": "user", "content": message},
            ],
            temperature=0,
            max_tokens=300,
        )
        if use_json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return client.chat.completions.create(**kwargs)

    raw = None
    try:
        completion = call_groq(use_json_mode=True)
        raw = completion.choices[0].message.content
    except Exception:
        try:
            completion = call_groq(use_json_mode=False)
            raw = completion.choices[0].message.content
        except Exception as e:
            print(f"⚠️ Profile extraction error: {e}")
            return {}

    if not raw:
        return {}

    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()

    # Pull out just the {...} block in case the model added any
    # preamble or trailing text despite instructions not to.
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        raw = match.group(0)

    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"⚠️ Profile extraction error: {e}")
        return {}


def apply_profile_updates(updates):
    """Merges extracted fields into the saved user_profile. Returns
    True if anything actually changed (so the caller can decide
    whether to mention it)."""
    changed = False

    if updates.get("name"):
        name = str(updates["name"]).strip().title()
        if name and user_profile.get("name") != name:
            user_profile["name"] = name
            changed = True

    if updates.get("age") is not None:
        try:
            age = int(updates["age"])
            if 1 <= age <= 120 and user_profile.get("age") != age:
                user_profile["age"] = age
                changed = True
        except (TypeError, ValueError):
            pass

    if updates.get("studies"):
        studies = str(updates["studies"]).strip()
        if studies:
            value = studies.upper() if len(studies) <= 6 else studies.title()
            if user_profile.get("studies") != value:
                user_profile["studies"] = value
                changed = True

    if updates.get("university"):
        university = str(updates["university"]).strip()
        if university:
            value = university.upper() if len(university) <= 6 else university.title()
            if user_profile.get("university") != value:
                user_profile["university"] = value
                changed = True

    if updates.get("interests"):
        raw_interests = updates["interests"]
        if isinstance(raw_interests, str):
            raw_interests = [raw_interests]
        if isinstance(raw_interests, list):
            interests = user_profile.get("interests", [])
            if not isinstance(interests, list):
                interests = []
            for interest in raw_interests:
                interest = str(interest).strip()
                if interest and interest not in interests:
                    interests.append(interest)
                    changed = True
            user_profile["interests"] = interests

    if changed:
        save_user_profile(user_profile)

    return changed


# ============================================================
# INSTANT CASUAL RESPONSES (kept — free, instant, saves API quota)
# ============================================================

def instant_casual_response(question):
    text = normalize_text(question)
    name = name_prefix()

    if is_greeting(text):
        return f"Hello{name}! 👋 How are you doing today?"

    if is_thanks(text):
        return f"You're very welcome{name}! 💛"

    return None


def casual_fallback():
    name = name_prefix()
    return f"I'm here to help{name}! Ask me anything."


# ============================================================
# WEB SEARCH (Tavily) — for time-sensitive / current questions
# ============================================================

# Keywords/patterns that suggest the question needs current,
# real-time information rather than general/static knowledge.
TIME_SENSITIVE_PATTERNS = [
    r"\bcurrent\b", r"\bcurrently\b", r"\bnow\b", r"\btoday\b",
    r"\blatest\b", r"\brecent\b", r"\brecently\b", r"\bthis year\b",
    r"\b20(2[5-9]|3\d)\b",  # years 2025 onward
    r"\bpresident\b", r"\bsadar\b",
    r"\bprime\s*minis?ter\b", r"\bpm of\b", r"\bwazir[ -]?e[ -]?azam\b",
    r"\bceo\b", r"\bwho is the\b", r"\bnews\b",
    r"\bprice of\b", r"\bstock\b", r"\bweather\b",
    r"\bscore\b", r"\bwinner\b", r"\bresult\b",
    r"\bas of\b", r"\bnewest\b", r"\bupcoming\b", r"\bevent\b",
    r"\bkon hai\b", r"\bkaun hai\b", r"\bkon hain\b", r"\bkaun hain\b",
]


def needs_web_search(question):
    text = normalize_text(question)
    return any(re.search(pattern, text) for pattern in TIME_SENSITIVE_PATTERNS)


def search_web(query, max_results=3):
    """Runs a live web search via Tavily. Returns None (never raises)
    if Tavily isn't configured or the search fails — the chatbot
    falls back to answering from the model's own knowledge."""
    client = get_tavily_client()
    if client is None:
        return None
    try:
        return client.search(query, max_results=max_results, include_answer=True)
    except Exception as e:
        print(f"⚠️ Tavily search error: {e}")
        return None


def build_search_context(search_result):
    """Turns a Tavily search response into a short text block the
    LLM can use as grounding context."""
    if not search_result:
        return ""

    parts = []

    if search_result.get("answer"):
        parts.append(f"Quick answer: {search_result['answer']}")

    for result in search_result.get("results", [])[:3]:
        title = result.get("title", "")
        content = (result.get("content", "") or "")[:400]
        if title or content:
            parts.append(f"- {title}: {content}")

    return "\n".join(parts)


# ============================================================
# LLM-POWERED ANSWER
# ============================================================

SYSTEM_PROMPT = (
    "You are a friendly, helpful AI Knowledge Assistant. "
    "Answer clearly and concisely, using simple language. "
    "If the user has shared personal details earlier in the "
    "conversation, you may refer to them naturally. "
    "When live web search results are provided below the "
    "question, treat them as the most current, reliable source "
    "of truth for anything time-sensitive (current officeholders, "
    "recent events, prices, etc.) — prefer them over your own "
    "training knowledge for those details. "
    "When content from a file the user uploaded is provided below "
    "the question, treat it as the document being discussed — use "
    "it to answer questions about the file, summarize it, extract "
    "information from it, or do whatever the user asks with it. "
    "For any math, always write equations and expressions using "
    "LaTeX delimiters: \\( ... \\) for inline math and \\[ ... \\] "
    "for standalone equations. Never use plain square brackets or "
    "parentheses as a substitute for these delimiters. "
    "For multiplication between a number and a unit, prefer the "
    "simple \\cdot command with a space on both sides (e.g. "
    "\"0.0821 \\cdot atm\"), not \\cdotp with no space, since a "
    "command running directly into the following letters breaks "
    "rendering. "
    "Formatting: default to plain, well-organized paragraphs (or a "
    "short bullet list only when the content is genuinely a list of "
    "discrete items). Do not use a markdown table unless the user "
    "explicitly asks for a table, a comparison, or tabular data — "
    "tables should be the exception, not the default. Do not reach "
    "for bullet points as the default response shape either; most "
    "answers read better as normal prose. If the user explicitly "
    "asks for a specific format (a table, bullet points, a plain "
    "paragraph, numbered steps, etc.), always answer in exactly "
    "that format. "
    "Language: if the user writes in Roman Urdu (the Urdu language "
    "written using English/Latin letters, e.g. 'aap kaise hain'), "
    "reply in Roman Urdu the same way — English letters, Urdu "
    "words and grammar — never in Hindi, never in Devanagari "
    "script, and never mixing in Hindi vocabulary. If the user "
    "writes in English, reply in English. If the user explicitly "
    "asks you to translate text from Roman Urdu to English, or "
    "from English to Roman Urdu, perform that translation "
    "accurately regardless of the language rule above. "
    "If live web search results are provided below the question, "
    "you DO have current, real information for this — never say "
    "you lack real-time access or can't verify it in that case; "
    "state the answer plainly and confidently based on those "
    "results. Stay consistent with facts already established "
    "earlier in this same conversation (including from a previous "
    "search) unless new information clearly contradicts them. "
    "If information about the user (name, age, studies, university, "
    "interests) is provided below the question, that is the user's "
    "own saved profile — use it naturally to answer questions about "
    "them (like 'who am I' or 'what do you know about me'), in "
    "whatever language they asked in."
)


DEVANAGARI_PATTERN = re.compile(r"[\u0900-\u097F]")


def fix_devanagari_script(answer):
    """Safety net on top of the system prompt: if the model's answer
    accidentally slipped into Devanagari (Hindi script) instead of
    Roman Urdu, ask it to rewrite the same answer using only Latin
    letters. Only fires when Devanagari is actually detected, so it
    adds no extra cost to normal answers."""
    if not DEVANAGARI_PATTERN.search(answer):
        return answer
    try:
        client = get_groq_client()
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": (
                    "Rewrite the following text entirely using English/"
                    "Latin letters — if it's Urdu, write it as Roman "
                    "Urdu, not Devanagari (Hindi script). Do not use any "
                    "Devanagari characters at all. Keep the meaning, "
                    "facts, and formatting (including any LaTeX or "
                    "markdown) exactly the same — only fix the script."
                )},
                {"role": "user", "content": answer},
            ],
            temperature=0,
            max_tokens=4096,
        )
        rewritten = completion.choices[0].message.content.strip()
        return rewritten if rewritten else answer
    except Exception as e:
        print(f"⚠️ Devanagari-fix error: {e}")
        return answer


def ask_llm(question, history=None, web_context=None, file_context=None, profile_context=None):
    """
    Sends the question (plus optional recent conversation history,
    optional live web search context, optional uploaded-file
    context, and optional saved-profile context) to Groq's LLM API
    and returns the answer as plain text.

    history: optional list of {"role": "user"|"assistant", "content": str}
    dicts representing recent prior turns, oldest first.
    web_context: optional string of live web search results to
    ground the answer in current information.
    file_context: optional string of text extracted from a file the
    user uploaded, so the model can answer questions about it.
    profile_context: optional string of the user's saved profile
    facts (name, age, studies, etc.), so the model can answer
    questions about the user themselves in any phrasing.
    """
    try:
        client = get_groq_client()

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        if history:
            messages.extend(history)

        extra_blocks = []
        if profile_context:
            extra_blocks.append(
                f"[The user's saved profile:]\n{profile_context}"
            )
        if file_context:
            extra_blocks.append(
                f"[Content from a file the user uploaded in this "
                f"conversation:]\n{file_context}"
            )
        if web_context:
            extra_blocks.append(
                f"[Live web search results for context:]\n{web_context}"
            )

        if extra_blocks:
            user_content = question + "\n\n" + "\n\n".join(extra_blocks)
        else:
            user_content = question

        messages.append({"role": "user", "content": user_content})

        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=4096,
        )

        answer = completion.choices[0].message.content.strip()
        answer = fix_devanagari_script(answer)
        return answer

    except Exception as e:
        print(f"⚠️ Groq API error: {e}")
        return (
            "Sorry, I'm having trouble reaching my AI service right now. "
            "Please try again in a moment."
        )


def build_profile_context(profile):
    """Turns the saved user_profile dict into a short text block the
    LLM can use to answer questions about the user themselves —
    regardless of how they phrase the question ('who am I', 'mein
    kon hoon', 'what do you know about me', etc.)."""
    if not profile:
        return None

    parts = []
    if profile.get("name"):
        parts.append(f"Name: {profile['name']}")
    if profile.get("age"):
        parts.append(f"Age: {profile['age']}")
    if profile.get("studies"):
        parts.append(f"Studying: {profile['studies']}")
    if profile.get("university"):
        parts.append(f"University: {profile['university']}")
    interests = profile.get("interests")
    if isinstance(interests, list) and interests:
        parts.append(f"Interests: {', '.join(interests)}")

    return "\n".join(parts) if parts else None


def summarize_file_with_llm(text, filename=""):
    """Asks the LLM for a proper summary of an uploaded file's text,
    instead of the old keyword-based extractive summary — this reads
    more like a ChatGPT-quality summary."""
    label = f" ('{filename}')" if filename else ""
    prompt = (
        f"Summarize the uploaded file{label} in a few clear, well "
        f"organized paragraphs covering its main points."
    )
    return ask_llm(prompt, file_context=text[:8000])


def get_answer(question, history=None, file_context=None, profile_context=None):
    """Main entry point: decides whether this question needs a live
    web search first, then asks the LLM — with whatever combination
    of search, file, and profile context applies — and returns the
    answer."""
    web_context = None

    if needs_web_search(question):
        search_result = search_web(question)
        web_context = build_search_context(search_result)

    return ask_llm(
        question,
        history=history,
        web_context=web_context,
        file_context=file_context,
        profile_context=profile_context,
    )


# ============================================================
# TOPIC CLASSIFICATION (for the analytics dashboard only)
# ============================================================
#
# The LLM answers every question the same way regardless of topic —
# this is only used to label each question for the "Questions by
# Domain" chart in analytics, so usage patterns are visible.

TOPIC_KEYWORDS = {
    "pakistan": [
        "pakistan", "pakistani", "islamabad", "karachi", "lahore",
        "punjab", "sindh", "balochistan", "khyber pakhtunkhwa", "kpk",
        "jinnah", "quaid",
    ],
    "maths": [
        "math", "maths", "mathematics", "algebra", "geometry",
        "equation", "solve for", "calculus", "trigonometry",
        "derivative", "integral", "fraction", "percentage",
        "triangle", "square root", "polynomial", "logarithm",
    ],
    "physics": [
        "physics", "velocity", "force", "gravity", "electron",
        "photon", "quantum", "newton's", "thermodynamics", "voltage",
        "electric current", "acceleration", "momentum", "wavelength",
        "optics", "circuit", "magnetic field",
    ],
    "programming": [
        "programming", "source code", "python", "javascript", "java ",
        "c++", "algorithm", "variable", "for loop", "while loop",
        "array", "database", " api ", "html", "css", " sql ",
        "debug", "syntax error", "compiler", "function(",
    ],
}


def classify_topic(question):
    text = normalize_text(question)
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return topic
    return "general_knowledge"
