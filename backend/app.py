"""
Insura - AI Insurance Assistant
Flask Backend
"""

import logging
import os
import uuid

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from database import init_db, sync_enrollment_to_db, lookup_policy
from dashboard_routes import dashboard_bp
from enrollment import save_enrollment
from rag import retrieve_policy
from tts import text_to_speech

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("insura.app")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

app.register_blueprint(dashboard_bp)
init_db()

# ---------------------------------------------------------------------------
# In-memory enrollment sessions
# Keys: step, policy_raw, policy_clean, username, name, age, phone, email
# ---------------------------------------------------------------------------

enrollment_sessions: dict[str, dict] = {}

SYSTEM_PROMPT = """
You are Insura, a professional AI Insurance Assistant for LIC (Life Insurance Corporation of India).

Guidelines:
- Be concise, warm, and professional.
- Answer only insurance-related questions.
- Use only the policy context provided; do not invent details.
- When context is missing, say you do not have that information and suggest contacting LIC.
- Recommend relevant LIC policies when asked.
- Keep every response under 120 words so it sounds natural when spoken aloud.
- Do not use bullet points or markdown -- respond in plain, spoken English.
""".strip()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def health():
    return jsonify({"status": "Insura backend is running."})


@app.route("/audio/<path:filename>")
def serve_audio(filename: str):
    logger.info("Serving audio file: %s", filename)
    return send_from_directory(AUDIO_DIR, filename)


@app.route("/chat", methods=["POST"])
def chat():
    data: dict      = request.get_json(silent=True) or {}
    question: str   = data.get("question", "").strip()
    session_id: str = data.get("session_id") or str(uuid.uuid4())
    username: str   = data.get("username", "").strip()

    if not question:
        return jsonify({"error": "question is required"}), 400

    logger.info("[session=%s] User: %s", session_id, question)

    try:
        answer, audio_filename = _process_message(question, session_id, username)
        logger.info("[session=%s] Insura: %s", session_id, answer)
        return jsonify({
            "answer":     answer,
            "audio":      audio_filename,
            "session_id": session_id,
        })
    except Exception as exc:
        logger.exception("[session=%s] Unhandled error: %s", session_id, exc)
        error_msg = "Sorry, something went wrong on my end. Please try again."
        return jsonify({
            "answer":     error_msg,
            "audio":      _safe_tts(error_msg),
            "session_id": session_id,
        }), 500


# ---------------------------------------------------------------------------
# Internal logic
# ---------------------------------------------------------------------------


def _process_message(
    question: str, session_id: str, username: str = ""
) -> tuple[str, str | None]:

    q_lower = question.lower()

    # Persist user turn to dashboard DB
    if username:
        try:
            from database import save_chat_turn
            save_chat_turn(username, session_id, "user", question)
        except Exception as exc:
            logger.warning("Could not save user chat turn: %s", exc)

    # Enrollment trigger
    if _is_enrollment_trigger(q_lower) and session_id not in enrollment_sessions:
        policy_info  = lookup_policy(question)
        clean_policy = policy_info["policy_name"]
        logger.info(
            "[session=%s] Enrollment triggered. raw=%r  clean=%r",
            session_id, question, clean_policy,
        )
        enrollment_sessions[session_id] = {
            "step":         "name",
            "policy_raw":   question,
            "policy_clean": clean_policy,
            "username":     username,
        }
        answer = (
            "I would be happy to help you enroll. "
            "Let us start -- what is your full name?"
        )
        _persist_assistant_turn(username, session_id, answer)
        return answer, _safe_tts(answer)

    # Active enrollment flow
    if session_id in enrollment_sessions:
        answer = _handle_enrollment_step(question, session_id)
        _persist_assistant_turn(username, session_id, answer)
        return answer, _safe_tts(answer)

    # Normal RAG + Ollama query
    answer         = _query_ollama(question)
    audio_filename = _safe_tts(answer)
    _persist_assistant_turn(username, session_id, answer)
    return answer, audio_filename


def _persist_assistant_turn(username: str, session_id: str, answer: str) -> None:
    if not username:
        return
    try:
        from database import save_chat_turn
        save_chat_turn(username, session_id, "assistant", answer)
    except Exception as exc:
        logger.warning("Could not save assistant turn: %s", exc)


def _is_enrollment_trigger(q_lower: str) -> bool:
    keywords = [
        "enroll", "enrollment", "sign up",
        "buy policy", "purchase policy", "apply",
    ]
    return any(kw in q_lower for kw in keywords)


def _handle_enrollment_step(answer_text: str, session_id: str) -> str:
    state = enrollment_sessions[session_id]
    step  = state.get("step")

    if step == "name":
        state["name"] = answer_text
        state["step"] = "age"
        return "Thank you! Could you please tell me your age?"

    if step == "age":
        state["age"]  = answer_text
        state["step"] = "phone"
        return "Got it. What is your phone number?"

    if step == "phone":
        state["phone"] = answer_text
        state["step"]  = "email"
        return "Perfect. And your email address?"

    if step == "email":
        state["email"] = answer_text

        # Use the clean policy name resolved at trigger time
        clean_policy = state.get("policy_clean") or state.get("policy_raw", "")
        policy_raw   = state.get("policy_raw", "")

        logger.info(
            "[enrollment] Saving -- name=%r  policy_clean=%r",
            state.get("name"), clean_policy,
        )

        # 1. Save to customer_enrollments.xlsx
        success = save_enrollment(
            name=state.get("name", ""),
            age=state.get("age", ""),
            phone=state.get("phone", ""),
            email=state.get("email", ""),
            policy=clean_policy,
        )

        # 2. Sync to dashboard SQLite DB
        enrolled_username = state.get("username", "")
        if enrolled_username:
            try:
                sync_enrollment_to_db(
                    username=enrolled_username,
                    name=state.get("name", ""),
                    age=state.get("age", ""),
                    phone=state.get("phone", ""),
                    email=state.get("email", ""),
                    policy_raw=policy_raw,
                )
                logger.info(
                    "[enrollment] Dashboard DB synced for user=%s", enrolled_username
                )
            except Exception as exc:
                logger.warning("Dashboard DB sync failed: %s", exc)
        else:
            logger.warning(
                "[enrollment] username is empty -- dashboard not updated. "
                "Ensure agent.html sends username in the /chat request body."
            )

        del enrollment_sessions[session_id]

        if success:
            return (
                "Your enrollment has been completed successfully! "
                "Our team will reach out to you shortly. "
                "Is there anything else I can help you with?"
            )
        return (
            "I am sorry, there was a problem saving your enrollment. "
            "Please try again later."
        )

    # Fallback
    del enrollment_sessions[session_id]
    return "Enrollment session ended. How else can I help you?"


def _query_ollama(question: str) -> str:
    import ollama
    policy_context = retrieve_policy(question)
    user_content   = f"User question: {question}"
    if policy_context:
        user_content += f"\n\nRelevant policy information:\n{policy_context}"
    response = ollama.chat(
        model="llama3.2",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ],
    )
    return response["message"]["content"].strip()


def _safe_tts(text: str) -> str | None:
    try:
        return text_to_speech(text)
    except Exception as exc:
        logger.error("TTS failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Starting Insura backend on http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=True)
