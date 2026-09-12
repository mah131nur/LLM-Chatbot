# AI Knowledge Chatbot - GUI Version

This version adds a Flask web GUI while keeping the existing dataset-driven knowledge modules.

## Features
- Blue modern chatbot dashboard
- Pakistan, Maths, Physics, Programming and General Knowledge routing
- Persistent SQLite chat history
- Analytics dashboard based on real usage data
- User profile/memory using the existing `user_profile.json`
- Browser voice input using Web Speech API (Chrome/Edge recommended)
- File upload and local text extraction for PDF, DOCX, PPTX, XLSX/XLS, CSV, TXT, MD and JSON
- Extractive local file summaries (no LLM/API required)
- Chat export to TXT
- Responsive layout and dark-mode toggle

## Install
Activate your existing venv first, then:

```powershell
pip install -r requirements.txt
```

## Run the GUI

```powershell
python web_app.py
```

Open:

`http://127.0.0.1:5000`

## Keep using the terminal version

```powershell
python app.py
```

## Notes
- Voice recognition is performed by the browser. Chrome/Edge are recommended.
- The current file summarizer is local/extractive. It does not call an external LLM.
- The GUI supports common document/data formats rather than literally every binary file type.
- Existing CSV datasets remain the source of knowledge answers.
