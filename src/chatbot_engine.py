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
from dotenv import load_dotenv
import os

load_dotenv()
import os
import re
import json

from groq import Groq

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

    # --------------------------------------------------------
    # Ask what is already saved
    # --------------------------------------------------------
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

    # --------------------------------------------------------
    # Automatically learn profile information from normal chat.
    # Several fields can be saved from ONE message.
    # --------------------------------------------------------
    learned = []

    name_match = re.search(r"\bmy name is\s+([a-zA-Z][a-zA-Z .'-]{0,50})", text, re.IGNORECASE)
    if name_match:
        name = name_match.group(1).strip(" .'-").split()[0].capitalize()
        user_profile["name"] = name
        learned.append(f"your name is {name}")

    age_match = re.search(r"\bmy age is\s+(\d+)\b", text, re.IGNORECASE)
    if not age_match:
        age_match = re.search(r"\bi am\s+(\d+)\s*(?:years?\s*old)?\b", text, re.IGNORECASE)
    if age_match:
        age = int(age_match.group(1))
        if 1 <= age <= 120:
            user_profile["age"] = age
            learned.append(f"you're {age} years old")

    # Common degree names, including BSCS, BS, BCS, MS, MBA, etc.
    degree_patterns = [
        r"\b(?:my degree is|i(?:'m| am) studying|i(?:'m| am) doing|i(?:'m| am) pursuing|i study|i do)\s+(?:a|an)\s+([a-z][a-z0-9+.#& -]{1,60}?)(?=\s+(?:at|from|and|in)\s+|[.!?]|$)",
        r"\b(?:i(?:'m| am)\s+(?:a|an)\s+)?(bs\s*cs|bscs|bcs|bs|bsc|be|bba|bcom|ba|bse|ms|msc|mcs|mba|ma|mphil|phd|doctorate)\s+(?:student|degree)\b",
        r"\b(?:my degree is|i(?:'m| am) studying|i(?:'m| am) doing|i(?:'m| am) pursuing|i study|i do)\s+(bs\s*cs|bscs|bcs|bs|bsc|be|bba|bcom|ba|bse|ms|msc|mcs|mba|ma|mphil|phd|doctorate)(?=\s+(?:at|from|and|in)\s+|[.!?]|$)",
    ]
    studies = None
    for pattern in degree_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            studies = match.group(1).strip(" ,")
            break
    if studies:
        # Keep common abbreviations readable and preserve longer degree names.
        studies = studies.upper() if len(studies) <= 8 else studies.title()
        user_profile["studies"] = studies
        learned.append(f"you're studying {studies}")

    # University / college / institute. Handles phrases such as:
    # "I study at COMSATS University Islamabad" and
    # "my university is COMSATS University Islamabad".
    university = None
    uni_match = re.search(
        r"\b(?:my university is|my uni is|my college is|my institute is)\s+(.+?)(?=\s+(?:and|where)\s+|[.!?]|$)",
        text,
        re.IGNORECASE,
    )
    if not uni_match:
        uni_match = re.search(
            r"\b(?:at|from)\s+(.+?)(?=\s+(?:and|where|with)\s+|[.!?]|$)",
            text,
            re.IGNORECASE,
        )
    if uni_match:
        candidate = uni_match.group(1).strip(" ,")
        # Don't accidentally save the degree when the sentence is "studying BSCS at...".
        candidate = re.sub(r"^(?:the\s+)?(?:university|college|institute)\s+", "", candidate, flags=re.IGNORECASE).strip()
        if re.search(r"\b(?:university|college|institute|campus|comsats|nust|fast|lums|iba|giki)\b", candidate, re.IGNORECASE):
            university = candidate
    if university:
        user_profile["university"] = university.title()
        learned.append(f"you study at {user_profile['university']}")

    # Interests: "I'm interested in AI and coding", "my interests are coding,
    # video editing", "I like programming and gaming", etc.
    interests_match = re.search(
        r"\b(?:my interests? (?:are|is)|i(?:'m| am) interested in|i like|i love)\s+(.+?)(?:[.!?]|$)",
        text,
        re.IGNORECASE,
    )
    if interests_match:
        raw_interests = interests_match.group(1).strip()
        raw_interests = re.sub(r"\s+and\s+", ",", raw_interests, flags=re.IGNORECASE)
        interests = [item.strip().title() for item in raw_interests.split(",") if item.strip()]
        if interests:
            user_profile["interests"] = interests
            learned.append("your interests are " + ", ".join(interests))

    if learned:
        save_user_profile(user_profile)
        return "Got it! 😊 I'll remember " + "; ".join(learned) + "."

    # --------------------------------------------------------
    # Direct questions about saved profile fields
    # --------------------------------------------------------
    if re.search(r"\b(?:what is|what's|tell me)\s+(?:my\s+)?(?:degree|studies)\b", text):
        studies = user_profile.get("studies")
        return f"You're studying {studies}. 🎓" if studies else "You haven't told me your degree/studies yet."

    if re.search(r"\b(?:what is|what's|tell me)\s+(?:my\s+)?(?:university|uni)\b", text):
        university = user_profile.get("university")
        return f"You study at {university}. 🏫" if university else "You haven't told me your university yet."

    if re.search(r"\b(?:what are|what's|tell me)\s+(?:my\s+)?interests?\b", text):
        interests = user_profile.get("interests", [])
        return f"Your interests are {', '.join(interests)}. ❤️" if interests else "You haven't told me your interests yet."

    return None


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
    r"\bpresident\b", r"\bprime minister\b", r"\bpm of\b",
    r"\bceo\b", r"\bwho is the\b", r"\bnews\b",
    r"\bprice of\b", r"\bstock\b", r"\bweather\b",
    r"\bscore\b", r"\bwinner\b", r"\bresult\b",
    r"\bas of\b", r"\bnewest\b", r"\bupcoming\b", r"\bevent\b",
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
    "Never join a LaTeX command directly to a unit or word: write "
    "\\cdot\\mathrm{atm} or \\cdot \\mathrm{atm}, not \\cdotpatm. "
    "Use valid KaTeX commands and keep a space or a second backslash "
    "between commands and following text."
)


def ask_llm(question, history=None, web_context=None, file_context=None):
    """
    Sends the question (plus optional recent conversation history,
    optional live web search context, and optional uploaded-file
    context) to Groq's LLM API and returns the answer as plain text.

    history: optional list of {"role": "user"|"assistant", "content": str}
    dicts representing recent prior turns, oldest first.
    web_context: optional string of live web search results to
    ground the answer in current information.
    file_context: optional string of text extracted from a file the
    user uploaded, so the model can answer questions about it.
    """
    try:
        client = get_groq_client()

        profile_context = ""
        if user_profile:
            profile_context = (
                "\n\n[Saved user profile — use only when relevant to the user's request:]\n"
                + json.dumps(user_profile, ensure_ascii=False)
            )

        messages = [{"role": "system", "content": SYSTEM_PROMPT + profile_context}]

        if history:
            messages.extend(history)

        extra_blocks = []
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
            max_tokens=1024,
        )

        return completion.choices[0].message.content.strip()

    except Exception as e:
        print(f"⚠️ Groq API error: {e}")
        return (
            "Sorry, I'm having trouble reaching my AI service right now. "
            "Please try again in a moment."
        )


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


def get_answer(question, history=None, file_context=None):
    """Main entry point: decides whether this question needs a live
    web search first, then asks the LLM — with whatever combination
    of search and/or file context applies — and returns the answer."""
    web_context = None

    if needs_web_search(question):
        search_result = search_web(question)
        web_context = build_search_context(search_result)

    return ask_llm(
        question,
        history=history,
        web_context=web_context,
        file_context=file_context,
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
