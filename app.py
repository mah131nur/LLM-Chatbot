# ============================================================
#                  AI KNOWLEDGE CHATBOT
#         Terminal version (LLM-powered, via Groq + Tavily)
# ============================================================

from src.chatbot_engine import (
    handle_personal_information,
    instant_casual_response,
    is_goodbye,
    get_answer,
    extract_profile_updates_with_llm,
    apply_profile_updates,
    build_profile_context,
    user_profile,
)

print("\n=======================================================")
print("             🤖 AI KNOWLEDGE CHATBOT")
print("=======================================================")
print("🧠 Powered by an AI language model (Groq) with live web search")
print("🧠 Personal information is saved in user_profile.json")
print("Type 'bye' to exit.")
print("=======================================================")

conversation_history = []

while True:
    try:
        user_question = input("\n👤 You: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n🤖 Goodbye! 👋")
        break

    if not user_question:
        continue
    if is_goodbye(user_question):
        print("\n🤖 Goodbye! 👋 Take care and have a great day! 😊")
        break

    personal_answer = handle_personal_information(user_question)
    if personal_answer:
        print(f"\n🤖 Bot: {personal_answer}")
        continue

    instant_answer = instant_casual_response(user_question)
    if instant_answer:
        print(f"\n🤖 Bot: {instant_answer}")
        continue

    profile_updates = extract_profile_updates_with_llm(user_question)
    updated_profile = apply_profile_updates(profile_updates) if profile_updates else False

    question_for_llm = user_question
    if updated_profile:
        learned = ", ".join(
            f"{key}: {value}" for key, value in profile_updates.items() if value
        )
        question_for_llm = (
            f"{user_question}\n\n"
            f"(System note, not part of the user's message: you just "
            f"learned and saved these details about the user — {learned}. "
            f"Acknowledge this warmly and naturally as part of your reply, "
            f"in the same language and tone as their message, then still "
            f"help with anything else they asked, if anything.)"
        )

    answer = get_answer(
        question_for_llm,
        history=conversation_history,
        profile_context=build_profile_context(user_profile),
    )
    print(f"\n🤖 Bot: {answer}")

    conversation_history.append({"role": "user", "content": user_question})
    conversation_history.append({"role": "assistant", "content": answer})

    # Keep the conversation history from growing without bound.
    conversation_history = conversation_history[-20:]
