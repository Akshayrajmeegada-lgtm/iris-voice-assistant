# Iris for Windows

Iris is a voice assistant developed by **AKSHAY**. Say **“Hey Iris”** to bring up the overlay. Iris can speak replies, open apps, search the web, and run several supported actions in one request.

## Install

Use 64-bit Python 3.14 on Windows. Open PowerShell in the Iris folder and run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe .\download_model.py
```

The model downloader needs an internet connection. Wake-word detection runs locally. Follow-up speech recognition uses Google's speech service.

## Run

Test your Windows voice and launch Iris:

```powershell
.\.venv\Scripts\python.exe .\main.py --voice-test
Start-Process -FilePath '.\.venv\Scripts\pythonw.exe' -ArgumentList 'main.py'
```

Say **“Hey Iris, what time is it?”** A panel appears while Iris listens and works. Wait for **Listening** before asking a follow-up. Say **“Go to sleep”** to hide the panel or **“Goodbye”** to quit.

- **“Hey Iris, search for Python tutorials on YouTube and open Notepad.”**
- **“Hey Iris, open Spotify and tell me the time.”**
- **“Hey Iris, who developed you?”**

To see diagnostic messages, quit Iris and run ` .\.venv\Scripts\python.exe .\main.py --console ` in PowerShell. Use `--preview` in place of `--console` to preview the overlay without using the microphone.

## Optional Gemini answers

Create a [Gemini API key in Google AI Studio](https://aistudio.google.com/apikey). Run these commands, paste the key at the hidden prompt, and then launch Iris from the same PowerShell window. Keep your key out of the repository.

```powershell
$key = Read-Host 'Paste your Gemini API key' -AsSecureString
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new('', $key).Password
[Environment]::SetEnvironmentVariable('GEMINI_API_KEY', $env:GEMINI_API_KEY, 'User')
Remove-Variable key
```

Try **“Hey Iris, why is the sky blue?”** followed by **“What about at sunset?”** Iris sends general questions and recent AI conversation text to Gemini. API availability and quotas depend on your Google project.

## Optional WhatsApp control and startup

Install `pywinauto` with `.\.venv\Scripts\python.exe -m pip install pywinauto` to try WhatsApp drafts and calls. The example expects a contact named **Sis**. Windows desktop support depends on the accessibility controls exposed by your version of WhatsApp. Test a draft first. Once you have verified the chat, saying **“Call Sis on WhatsApp”** can place a real call.

Run `.\setup-startup.ps1` to start Iris in the background when you sign in. Run `.\setup-startup.ps1 -Disable` to remove the startup shortcut.
