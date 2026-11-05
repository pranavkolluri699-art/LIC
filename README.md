# INSURA — LIC AI Insurance Assistant

INSURA is a web based assistant for LIC policy questions. The project combines a Flask API, a browser interface, retrieval over LIC policy information, Ollama generated answers, optional text to speech, an enrollment conversation, and a customer dashboard.

## Current features

- Ask insurance questions in the chat interface and receive answers grounded in the available LIC policy context.
- Use the browser's speech recognition and audio playback controls where supported.
- Start an enrollment conversation and provide name, age, phone, and email. The current flow writes enrollment data to an Excel workbook and can sync it to the dashboard database.
- View profile, policy, recommendation, notification, document, chat history, and summary information through dashboard endpoints.
- Save chat turns and recommendations for a customer identified by the username supplied by the frontend.

The current login page checks a fixed demo username/password in frontend JavaScript and stores the username in browser local storage; this is not secure authentication. Google signup, payment processing, and direct LIC enrollment integration are not implemented. Calculator outputs are estimates and must not be treated as official quotes. No explanation-level setting is part of this project.

## Architecture diagrams

Six separate UML diagrams are available in [`docs/uml/`](docs/uml/README.md):

1. [Use case](docs/uml/01-use-case.svg)
2. [Class and module view](docs/uml/02-class-module.svg)
3. [Chat sequence](docs/uml/03-chat-sequence.svg)
4. [Enrollment activity](docs/uml/04-enrollment-activity.svg)
5. [Component](docs/uml/05-component.svg)
6. [Deployment](docs/uml/06-deployment.svg)

## Run locally

Requirements: Python 3.10 or later, packages in [`backend/requirements.txt`](backend/requirements.txt), and a local Ollama installation with `llama3.2` and `nomic-embed-text` available. The application expects the policy workbook at `backend/LIC_Policy_Details.xlsx`.

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
ollama pull llama3.2
ollama pull nomic-embed-text
python build_vector_db.py
python app.py
```

The Flask process exposes the API at `http://127.0.0.1:5000` (the root route returns a status response). The HTML pages in `frontend/` are not served by Flask routes in the current code; host them separately and configure their route handling and API origin before using the full interface. SQLite, the vector store, and generated audio are local backend data; enrollment records are written to an Excel workbook by the enrollment module.

## Main project files

- `frontend/` — login, home, assistant, and dashboard pages and scripts.
- `backend/app.py` — Flask application, chat flow, and enrollment conversation.
- `backend/rag.py` and `backend/build_vector_db.py` — policy retrieval and vector index setup.
- `backend/tts.py` — speech audio generation.
- `backend/database.py` and `backend/dashboard_routes.py` — SQLite persistence and dashboard API.
- `backend/recommendation.py` and `backend/enrollment.py` — recommendation and enrollment helpers.
- `backend/LIC_Policy_Details.xlsx` — source policy workbook.
