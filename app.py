# ============================================================
#                  AI KNOWLEDGE CHATBOT
#         Terminal version (LLM-powered, via Groq + Tavily)
# ============================================================

from src.chatbot_engine import (
    handle_personal_information,
    instant_casual_response,
    is_goodbye,
    get_answer,
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

    answer = get_answer(user_question, history=conversation_history)
    print(f"\n🤖 Bot: {answer}")

    conversation_history.append({"role": "user", "content": user_question})
    conversation_history.append({"role": "assistant", "content": answer})

    # Keep the conversation history from growing without bound.
    conversation_history = conversation_history[-20:]
