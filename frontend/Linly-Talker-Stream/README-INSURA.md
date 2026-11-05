# Insura talking-avatar service

Insura remains the policy assistant: Flask `/chat` retrieves from the LIC PDF index and produces the grounded answer and female voice. The browser sends that same audio to this local Linly-Talker-Stream service for lip-sync; Linly's independent LLM and TTS are not used.

## Current setup

The generic fictional female avatar frames are included in `data\avatars\wav2lip_avatar1`. The Python environment and Wav2Lip checkpoint are not included in GitHub: the environment is several gigabytes, and the checkpoint is over 200 MB and is subject to the Wav2Lip pretrained-model restrictions.

Install Python 3.11 and `uv`, then from this folder run:

```powershell
py -3.11 -m pip install uv
uv sync --python 3.11
```

The Wav2Lip checkpoint is stored locally at `models\wav2lip.pth`. It was downloaded from a public third-party Hugging Face mirror and verified against the file page's SHA-256 (`b22d7ac86295df667644b17254dc71250c2600b89e20403e90e58812450bc173`). If you need to restore it, use:

```powershell
cd frontend\Linly-Talker-Stream
New-Item -ItemType Directory -Force models
curl.exe -L --fail -o models\wav2lip.pth https://huggingface.co/CherryOnes/LiveTalking/resolve/main/wav2lip.pth
```

Verify the file hash before running:

```powershell
(Get-FileHash models\wav2lip.pth -Algorithm SHA256).Hash.ToLower()
```

It must print `b22d7ac86295df667644b17254dc71250c2600b89e20403e90e58812450bc173`.

## Start both services

1. From the cloned repository root, start Insura in one PowerShell window: `cd backend; python app.py`. Open `frontend\agent.html` in the browser.
2. In another, start the avatar: `cd frontend\Linly-Talker-Stream; .\start-avatar.ps1`.
3. Open `http://127.0.0.1:5000/`, refresh, and click **Connect avatar**.

The avatar service listens on `127.0.0.1:8010`. The checkpoint originates from the Wav2Lip/LiveTalking model family. Wav2Lip's published disclaimer restricts pretrained model use to research, academic, and personal purposes; commercial use requires separate permission. See the [Wav2Lip disclaimer](https://github.com/Rudrabha/Wav2Lip#disclaimer). The fictional avatar is locally generated; no real person's video is used.
