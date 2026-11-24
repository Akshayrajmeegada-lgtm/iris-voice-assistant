import json
import operator
import os
import re
import subprocess
import sys
import time
import webbrowser
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from itertools import cycle
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import sounddevice as sd
import speech_recognition as sr
from vosk import KaldiRecognizer, Model, SetLogLevel


IRIS_DEVELOPER = "AKSHAY"

PROJECT_FOLDER = Path(__file__).resolve().parent
MODEL_PATH = PROJECT_FOLDER / "vosk-model-small-en-us-0.15"
NOTES_PATH = PROJECT_FOLDER / "iris_notes.txt"

APPS = {
    "calculator": ("Calculator", ["calc.exe"]),
    "notepad": ("Notepad", ["notepad.exe"]),
    "paint": ("Paint", ["mspaint.exe"]),
    "chrome": (
        "Chrome",
        ["chrome.exe"],
    ),
    "whatsapp": (
        "WhatsApp",
        ["explorer.exe", r"shell:AppsFolder\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"],
    ),
    "visual studio code": (
        "Visual Studio Code",
        ["explorer.exe", r"shell:AppsFolder\Microsoft.VisualStudioCode"],
    ),
    "dev c++": ("Dev-C++", ["devcpp.exe"]),
    "file explorer": ("File Explorer", ["explorer.exe"]),
    "settings": ("Settings", ["explorer.exe", "ms-settings:"]),
    "terminal": ("Terminal", ["wt.exe"]),
    "task manager": ("Task Manager", ["taskmgr.exe"]),
}

APP_ALIASES = {
    "google chrome": "chrome",
    "whats app": "whatsapp",
    "whatapp": "whatsapp",
    "visual studio": "visual studio code",
    "vs code": "visual studio code",
    "v s code": "visual studio code",
    "dev c plus plus": "dev c++",
    "dev c plus": "dev c++",
    "dev-c++": "dev c++",
    "dev c": "dev c++",
    "file manager": "file explorer",
    "explorer": "file explorer",
    "windows terminal": "terminal",
}

CODEBOX_LOOKUP = (
    "Get-StartApps | Where-Object { $_.Name -in @('Codebox', 'Code Box') } "
    "| Select-Object -First 1 -ExpandProperty AppID"
)

WEBSITES = {
    "open youtube": ("YouTube", "https://www.youtube.com/"),
    "open wikipedia": ("Wikipedia", "https://en.wikipedia.org/"),
}

NUMBER_WORDS = {
    word: number
    for number, word in enumerate(
        "zero one two three four five six seven eight nine ten".split()
    )
}
MATH_OPERATIONS = {
    "plus": operator.add,
    "+": operator.add,
    "minus": operator.sub,
    "-": operator.sub,
    "times": operator.mul,
    "multiplied by": operator.mul,
    "*": operator.mul,
    "x": operator.mul,
    "divided by": operator.truediv,
    "/": operator.truediv,
}

WAKE_PHRASES = ("hey iris", "hi iris")

STOP_COMMANDS = ("exit", "stop", "goodbye", "stop iris")
COUNT_COMMANDS = ("count my notes", "count notes", "how many notes do i have")
RECENT_COMMANDS = ("read recent notes", "recent notes")
LAST_NOTE_COMMANDS = ("read my last note", "read last note", "last note")
SEARCH_PREFIXES = ("search for", "find me", "look up", "google search for")


@contextmanager
def windows_voice():
    # SAPI must be initialized on the thread that speaks.
    import pythoncom
    from win32com.client import Dispatch

    pythoncom.CoInitialize()
    try:
        voice = Dispatch("SAPI.SpVoice")
        voice.Volume = 100
        voice.Rate = 0
        yield voice
    finally:
        pythoncom.CoUninitialize()


def speak(engine, text):
    print("Iris:", text, flush=True)
    engine.Speak(text, 16)  # Synchronous speech, with markup disabled.


def wait_for_wake(model, sample_rate):
    dictation = KaldiRecognizer(model, sample_rate)
    wake_words = KaldiRecognizer(
        model, sample_rate, json.dumps([*WAKE_PHRASES, "[unk]"])
    )
    print('\nWaiting for "Hi Iris" or "Hey Iris"...', flush=True)

    with sd.RawInputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
    ) as stream:
        while True:
            recording, overflowed = stream.read(4000)
            if overflowed:
                dictation.Reset()
                wake_words.Reset()
                continue

            chunk = bytes(recording)
            if dictation.AcceptWaveform(chunk):
                text = json.loads(dictation.Result()).get("text", "").strip()
                for phrase in WAKE_PHRASES:
                    if text == phrase or text.startswith(phrase + " "):
                        print("Wake phrase detected!")
                        return text[len(phrase):].strip()

            if wake_words.AcceptWaveform(chunk):
                text = json.loads(wake_words.Result()).get("text", "").strip()
                if text in WAKE_PHRASES:
                    print("Wake phrase detected!")
                    return ""


class MicrophoneStream(sr.AudioSource):
    def __init__(self, sample_rate):
        self.SAMPLE_RATE = sample_rate
        self.SAMPLE_WIDTH = 2
        self.CHUNK = max(1, sample_rate // 32)
        self.stream = None
        self.input_stream = None

    def __enter__(self):
        self.input_stream = sd.RawInputStream(
            samplerate=self.SAMPLE_RATE, channels=1, dtype="int16"
        )
        self.input_stream.__enter__()
        self.stream = self
        return self

    def __exit__(self, *exc_info):
        try:
            self.input_stream.__exit__(*exc_info)
        finally:
            self.stream = None
            self.input_stream = None

    def read(self, frames):
        audio, overflowed = self.input_stream.read(frames)
        if overflowed:
            raise RuntimeError("Audio input overflowed.")
        return bytes(audio)


def listen(engine, recognizer, sample_rate, *, follow_up=False):
    for attempt in range(2):
        try:
            with MicrophoneStream(sample_rate) as microphone:
                print("Speak now.", flush=True)
                audio = recognizer.listen(microphone, timeout=8 if follow_up else 4, phrase_time_limit=25)
            print("Recognising your request...")
            return recognizer.recognize_google(audio, language="en-IN")
        except (sr.WaitTimeoutError, sr.UnknownValueError) as error:
            if attempt == 1 or (follow_up and isinstance(error, sr.WaitTimeoutError)):
                raise
            speak(engine, "I did not catch the audio. Please say it again.")


def open_app(engine, name, arguments):
    install_paths = {
        "chrome.exe": Path("Google/Chrome/Application/chrome.exe"),
        "devcpp.exe": Path("Dev-Cpp/devcpp.exe"),
    }
    executable = arguments[0]
    if executable in install_paths:
        for variable in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            base = os.environ.get(variable)
            if base:
                candidate = Path(base) / install_paths[executable]
                if candidate.is_file():
                    executable = str(candidate)
                    break

    try:
        subprocess.Popen([executable, *arguments[1:]])
    except OSError as error:
        print(f"Could not open {name}:", error)
        speak(engine, f"I couldn't open {name}.")
    else:
        speak(engine, f"Opening {name}.")


def save_note(engine, note):
    if not note:
        speak(engine, "Say take a note followed by what you want me to save.")
        return

    try:
        with NOTES_PATH.open("a", encoding="utf-8") as notes_file:
            notes_file.write(note + "\n")
    except OSError as error:
        print("Could not save the note:", error)
        speak(engine, "I couldn't save your note.")
    else:
        speak(engine, "Note saved.")


def get_note_summary():
    recent_notes = deque(maxlen=3)
    count = 0

    try:
        with NOTES_PATH.open(encoding="utf-8") as notes_file:
            for line in notes_file:
                note = line.strip()
                if note:
                    recent_notes.append(note)
                    count += 1
    except FileNotFoundError:
        pass

    return count, recent_notes


def report_notes(engine, command):
    try:
        count, recent_notes = get_note_summary()
    except (OSError, UnicodeError) as error:
        print("Could not read notes:", error)
        speak(engine, "I couldn't read your notes.")
        return

    if count == 0:
        speak(engine, "You don't have any saved notes yet.")
    elif command in COUNT_COMMANDS:
        word = "note" if count == 1 else "notes"
        speak(engine, f"You have {count} saved {word}.")
    elif command in RECENT_COMMANDS:
        speak(engine, "Here are your most recent notes.")
        for number, note in enumerate(recent_notes, start=1):
            speak(engine, f"Note {number}. {note}")
    else:
        speak(engine, f"Your last note is {recent_notes[-1]}")


def get_search_query(command, message):
    for prefix in SEARCH_PREFIXES:
        if command == prefix:
            return ""
        if command.startswith(prefix + " "):
            return message[len(prefix):].strip()

    return None


def search_web(engine, query):
    if not query:
        speak(engine, "Say search for, followed by what you want to find.")
        return

    url = "https://www.google.com/search?" + urlencode({"q": query})
    open_website(engine, url, f"Searching for {query}.")


def open_website(engine, url, success_message):
    try:
        opened = webbrowser.open_new_tab(url)
    except (OSError, webbrowser.Error) as error:
        print("Could not open browser:", error)
        opened = False

    if opened:
        speak(engine, success_message)
    else:
        speak(engine, "I couldn't open your browser.")


def calculate(engine, expression):
    number = r"(?:-?[0-9]{1,12}(?:\.[0-9]{1,12})?|" + "|".join(NUMBER_WORDS) + ")"
    operations = "|".join(map(re.escape, MATH_OPERATIONS))
    match = re.fullmatch(
        rf"({number})\s*({operations})\s*({number})", expression
    )
    if not match:
        speak(engine, "Try saying calculate eight plus five.")
        return

    left, operation, right = match.groups()
    left_value = float(NUMBER_WORDS.get(left, left))
    right_value = float(NUMBER_WORDS.get(right, right))

    try:
        answer = MATH_OPERATIONS[operation](left_value, right_value)
    except ZeroDivisionError:
        speak(engine, "You can't divide by zero.")
    else:
        speak(engine, f"The answer is {answer:.12g}.")


def open_codebox(engine):
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", CODEBOX_LOOKUP],
            capture_output=True,
            text=True,
            check=True,
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as error:
        print("Could not check for Codebox:", error)
        speak(engine, "I couldn't check for Codebox.")
        return

    app_id = result.stdout.strip()
    if app_id:
        open_app(engine, "Codebox", ["explorer.exe", rf"shell:AppsFolder\{app_id}"])
    else:
        speak(engine, "I couldn't find Codebox in the Windows Start menu.")


NOTE_REQUEST = re.compile(
    r"(?:take a note|make a note|write this down|jot this down|remember this for me|save a note|note this down)"
    r"(?:[\s,:-]+(?P<note>.*))?[.!?]?",
    re.IGNORECASE,
)


TASK_SEPARATOR = re.compile(
    r"\s*[,;]\s*(?:and\s+)?(?:then\s+)?|\s+(?:and\s+then|then|and)\s+",
    re.IGNORECASE,
)
POLITE_PREFIX = re.compile(
    r"^(?:(?:please|can you|could you|would you|i want you to)\s+)+",
    re.IGNORECASE,
)
APP_VERB = re.compile(r"^(?:open(?: up)?|opend|opened|launch|start|bring up|pull up|show me)\s+")
ACTION_START = re.compile(
    r"^(?:calculate|search for|look up|find me|google search for|give me|"
    r"tell me (?:the time|the date)|what (?:time|day|date|was my last note|does the clock say)|"
    r"(?:read|count)\b.*\bnotes?\b|how many notes)\b"
)


WHATSAPP_CONTACTS = {"sis": "Sis", "my sister": "Sis", "sister": "Sis"}
WHATSAPP_CALL = re.compile(
    r"^(?:(?:open|opend|launch)\s+whats\s*app\s+(?:and\s+)?(?:then\s+)?)?"
    r"(?:call|voice call|ring)\s+(?P<contact>[\w]+(?: [\w]+){0,3}?)(?:\s+(?:on|in|using)\s+whats\s*app)?$",
    re.IGNORECASE,
)
WHATSAPP_DRAFT = re.compile(
    r"^(?:type|draft|write)\s+(?P<body>.+?)\s+to\s+(?P<contact>[\w]+(?: [\w]+){0,3}?)"
    r"(?:\s+(?:on|in|using)\s+whats\s*app)?[.!?]?$",
    re.IGNORECASE,
)


def wait_for_unique(find, description, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matches = find()
        if len(matches) == 1:
            return matches[0]
        time.sleep(0.25)
    raise RuntimeError(f"I couldn't identify one {description} in WhatsApp.")


def whatsapp_action(engine, alias, draft=None):
    contact = WHATSAPP_CONTACTS.get(alias.strip().lower())
    if contact is None:
        speak(engine, "I don't have that name in my WhatsApp contacts list.")
        return

    try:
        from pywinauto import Desktop
    except ImportError:
        speak(engine, "Install pywinauto in the Iris environment to use WhatsApp commands.")
        return

    try:
        desktop = Desktop(backend="uia")

        def windows():
            return [
                window for window in desktop.windows()
                if window.window_text().strip().casefold() == "whatsapp"
            ]

        if not windows():
            subprocess.Popen(APPS["whatsapp"][1])
        window = wait_for_unique(windows, "WhatsApp window", timeout=20)
        window.set_focus()

        def controls(names, types):
            return [
                item for item in window.descendants()
                if item.element_info.control_type in types
                and item.window_text().strip().casefold() in names
                and item.is_visible() and item.is_enabled()
            ]

        search = wait_for_unique(
            lambda: controls(
                {"search", "search or start new chat", "search or start a new chat", "search a name or number"},
                {"Edit"},
            ),
            "chat search box",
        )
        search_right = search.rectangle().right
        search.set_edit_text(contact)

        result = wait_for_unique(
            lambda: controls({contact.casefold()}, {"ListItem", "DataItem", "Button"}),
            f"chat result named {contact}",
        )
        result.click_input()

        # Require a visible chat title separate from the clickable search result.
        chat_title = wait_for_unique(
            lambda: [
                title for title in controls({contact.casefold()}, {"Header", "HeaderItem", "Text"})
                if title.rectangle().left >= search_right
            ],
            f"chat title named {contact}",
        )

        if draft is not None:
            editor = wait_for_unique(
                lambda: controls({"type a message", "type a message here", "message"}, {"Edit"}),
                "message composer",
            )
            if editor.get_value().strip():
                speak(engine, "There is already a draft in this chat.")
                return
            editor.set_edit_text(draft)
            speak(engine, f"Drafted a message to {contact}.")
            return

        call = wait_for_unique(
            lambda: controls({"voice call", "start voice call", "make a voice call", "audio call"}, {"Button"}),
            "voice call button",
        )
        title_bounds = chat_title.rectangle()
        call_bounds = call.rectangle()
        if call_bounds.left < search_right or abs(call_bounds.mid_point().y - title_bounds.mid_point().y) > 70:
            raise RuntimeError("The call button is outside the verified chat header.")
        call.invoke()
        speak(engine, f"Calling {contact} on WhatsApp.")
    except Exception as error:
        print(f"WhatsApp automation stopped: {type(error).__name__}: {error}")
        speak(engine, "I couldn't finish that WhatsApp action. Check the console for details.")


SITE_SEARCH_PATTERNS = (
    re.compile(
        r"^(?:(?:open|launch)\s+(?:youtube|(?:google )?chrome)\s+(?:and\s+)?(?:then\s+)?)?"
        r"(?:search(?: for)?|look up|find(?: me)?|play)\s+(?P<query>.+?)\s+"
        r"(?:on|in|using)\s+(?P<site>you\s*tube|(?:google )?chrome|google)[.!?]?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:open|launch)\s+(?P<site>you\s*tube|(?:google )?chrome)\s+"
        r"(?:and\s+)?(?:then\s+)?(?:search(?: for)?|look up|find(?: me)?|play)\s+(?P<query>.+)$",
        re.IGNORECASE,
    ),
)


def match_site_search(message):
    for pattern in SITE_SEARCH_PATTERNS:
        match = pattern.fullmatch(message)
        if match:
            return match
    return None


def search_site(engine, site, query):
    site = site.lower().replace(" ", "")
    if site == "youtube":
        url = "https://www.youtube.com/results?" + urlencode({"search_query": query})
        open_website(engine, url, f"Showing YouTube results for {query}.")
    elif site in ("chrome", "googlechrome"):
        url = "https://www.google.com/search?" + urlencode({"q": query})
        open_app(engine, "Chrome", [*APPS["chrome"][1], url])
    else:
        search_web(engine, query)


def open_installed_app(engine, name):
    # Match the spoken name against the Start menu. Never pass speech to PowerShell.
    script = (
        "$ErrorActionPreference = 'Stop'; "
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, encoding="utf-8-sig", check=True, timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        entries = json.loads(result.stdout or "[]") or []
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        print("Start menu lookup failed:", error)
        speak(engine, "I couldn't read the Windows Start menu.")
        return

    if isinstance(entries, dict):
        entries = [entries]

    matches = {
        app["AppID"]: app["Name"]
        for app in entries
        if app["Name"].casefold() == name.casefold()
    }
    if len(matches) == 1:
        app_id, app_name = next(iter(matches.items()))
        open_app(engine, app_name, ["explorer.exe", rf"shell:AppsFolder\{app_id}"])
    elif name.casefold() == "spotify":
        open_website(engine, "https://open.spotify.com/", "Opening the Spotify web player.")
    else:
        speak(engine, f"I couldn't find one Start menu app named {name}. Try its exact name.")


def normalize_request(message):
    return POLITE_PREFIX.sub("", message.strip())


def split_tasks(message):
    request = normalize_request(message)
    if (
        WHATSAPP_DRAFT.fullmatch(request)
        or WHATSAPP_CALL.fullmatch(request.rstrip(".!?"))

    ):
        yield request
        return

    task_start = 0
    opening_apps = False
    for separator in TASK_SEPARATOR.finditer(message):
        current = normalize_request(message[task_start:separator.start()])
        following = normalize_request(message[separator.end():])
        next_piece = TASK_SEPARATOR.split(following, maxsplit=1)[0].lower().rstrip(".!?")
        next_app = APP_ALIASES.get(next_piece, next_piece)
        current_command = current.lower()
        following_command = following.lower()
        explicit = "then" in separator.group().lower()
        app_list = (opening_apps or APP_VERB.match(current_command)) and (
            next_app in APPS or f"open {next_app}" in WEBSITES or next_app in ("codebox", "code box")
        )
        action = (
            APP_VERB.match(following_command)
            or NOTE_REQUEST.fullmatch(next_piece)
            or WHATSAPP_CALL.fullmatch(next_piece)
            or WHATSAPP_DRAFT.fullmatch(next_piece)
            or ACTION_START.match(following_command)
            or next_piece in (*STOP_COMMANDS, "go to sleep", "back to sleep", "help")
        )
        site_search = match_site_search(current + " " + separator.group().strip() + " " + next_piece)
        if site_search and not match_site_search(current):
            continue
        if current and following and (explicit or app_list or action):
            yield current
            opening_apps = bool(app_list)
            task_start = separator.end()
    yield normalize_request(message[task_start:])


CONVERSATION_REPLIES = (
    (r"(?:hi|hey|hello|good morning|good afternoon|good evening)(?: iris)?",
     "Hi! Good to hear you. How's your day going?"),
    (r"(?:how are you(?: doing)?|how's it going|how is it going|and you|what about you)(?: iris)?",
     "I'm doing well. How about you?"),
    (r"(?:i'm|im|i am|doing|it's going|its going) (?:doing |feeling )?(?:good|great|fine|well|okay|ok|pretty good|not bad)(?: thanks)?",
     "I'm glad to hear that. What's on your mind today?"),
    (r"(?:i'm|im|i am|i feel) (?:feeling |a bit |really )?(?:sad|tired|stressed|upset|down)",
     "That sounds like a tough day. Want to talk about it, or would you like help with something?"),
    (r"(?:thank you|thanks|thanks a lot|thank you so much)(?: iris)?",
     "You're welcome. Anything else I can help with?"),
    (r"(?:can we talk|i want to talk|let's chat|lets chat|talk to me)",
     "Sure. How has your day been so far?"),
    (r"(?:what's your name|whats your name|what is your name|who are you)",
     "I'm Iris, your voice assistant. What would you like to do?"),
)


JOKES = cycle((
    "Why did the computer go to the doctor? It had a virus.",
    "Why did the scarecrow win an award? He was outstanding in his field.",
    "What do you call a bear with no teeth? A gummy bear.",
))
PROVERBS = cycle((
    "A stitch in time saves nine. Fixing a small problem early can save you work later.",
    "Actions speak louder than words. What people do matters more than what they promise.",
    "Slow and steady wins the race. Consistent effort can beat a hurried start.",
))


def conversational_reply(command):
    command = " ".join(command.replace("’", "'").replace(",", " ").split())
    if re.fullmatch(
        r"(?:(?:tell me|give me|say|share|crack) (?:a |one |another )?(?:funny )?joke"
        r"|do you know a joke|make me laugh)",
        command,
    ):
        return JOKES
    if re.fullmatch(
        r"(?:(?:tell me|give me|say|share) (?:a |one |another )?(?:proverb|wise saying)"
        r"|do you know a proverb)",
        command,
    ):
        return PROVERBS
    for pattern, reply in CONVERSATION_REPLIES:
        if re.fullmatch(pattern, command):
            return reply
    return None


GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-3.1-flash-lite:generateContent"
)
GEMINI_INSTRUCTIONS = (
    "You are Iris, a friendly Windows voice assistant. Answer naturally in one to three "
    "short sentences by default, in plain text suitable for reading aloud. "
    "Use the recent conversation for context and avoid repeating earlier jokes or proverbs. "
    "If you are unsure, say so. "
    "You can answer questions and chat, but you cannot see or control the user's computer, "
    "open apps, send messages, or verify live information. Do not claim to have done so."
)


def speak_fallback(engine, fallback, diagnostic):
    if fallback is None:
        speak(engine, diagnostic)
    else:
        speak(engine, fallback if isinstance(fallback, str) else next(fallback))


def answer_online(engine, message, conversation, fallback=None):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        speak_fallback(engine, fallback, "I need a Gemini API key to answer general questions. My app commands still work.")
        return

    turn = {"role": "user", "parts": [{"text": message}]}
    payload = {
        "systemInstruction": {"parts": [{"text": GEMINI_INSTRUCTIONS}]},
        "contents": [*conversation, turn],
        "generationConfig": {"maxOutputTokens": 400},
    }
    request = Request(
        GEMINI_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            result = json.load(response)
    except HTTPError as error:
        try:
            details = json.load(error).get("error", {}).get("details", [])
        except (OSError, ValueError):
            details = []
        reasons = {
            item.get("reason") for item in details if isinstance(item, dict)
            and isinstance(item.get("reason"), str)
            and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", item["reason"])
        }
        diagnostic = ", ".join(sorted(reasons)) or "no API error reason"
        print(f"Gemini request failed (HTTP {error.code}; {diagnostic}).", flush=True)
        if error.code in (401, 403) or "API_KEY_INVALID" in reasons:
            reply = "Gemini couldn't authenticate this request. Check your key and project in Google AI Studio."
        elif error.code == 400:
            reply = "Gemini rejected this request. Check the error reason in the console."
        elif error.code == 429:
            reply = "I've reached the Gemini request limit. Please try again later."
        else:
            reply = "Gemini is unavailable right now. Please try again later."
        speak_fallback(engine, fallback, reply)
        return
    except (URLError, TimeoutError, json.JSONDecodeError):
        speak_fallback(engine, fallback, "I couldn't reach Gemini. Check your internet connection and try again.")
        return

    candidates = result.get("candidates") or []
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    answer = " ".join(
        part["text"].strip() for part in parts if part.get("text") and not part.get("thought")
    ).strip()
    if not answer:
        speak_fallback(engine, fallback, "I couldn't get an answer to that. Try asking it a different way.")
        return

    speak(engine, answer)
    conversation.extend((turn, {"role": "model", "parts": [{"text": answer}]}))


def handle_command(engine, message, command, conversation=None):
    command = command.removeprefix("please ").removesuffix(" please").strip()
    app_command = APP_VERB.sub("", command)
    app_command = APP_ALIASES.get(app_command, app_command)
    search_query = get_search_query(command, message)

    note_request = NOTE_REQUEST.fullmatch(message)
    call_request = WHATSAPP_CALL.fullmatch(command)
    draft_request = WHATSAPP_DRAFT.fullmatch(message)
    site_search = match_site_search(message)
    reply = conversational_reply(command)
    if site_search:
        search_site(engine, site_search["site"], site_search["query"])

    elif call_request:
        whatsapp_action(engine, call_request["contact"])

    elif draft_request:
        whatsapp_action(engine, draft_request["contact"], draft_request["body"].strip(' "“”'))

    elif note_request:
        save_note(engine, note_request["note"] or "")

    elif command in COUNT_COMMANDS + RECENT_COMMANDS + LAST_NOTE_COMMANDS + ("what was my last note",):
        report_notes(engine, command)

    elif command == "open notes":
        if NOTES_PATH.is_file():
            open_app(engine, "your notes", ["notepad.exe", str(NOTES_PATH)])
        else:
            speak(engine, "You don't have any saved notes yet.")

    elif command in ("give me the date", "give me today's date", "give me the time"):
        now = datetime.now()
        if "date" in command:
            speak(engine, f"Today is {now:%A, %B} {now.day}, {now.year}.")
        else:
            speak(engine, f"The time is {now:%I:%M %p}")

    elif command == "calculate" or command.startswith("calculate "):
        calculate(engine, command[len("calculate"):].strip())

    elif f"open {app_command}" in WEBSITES:
        name, url = WEBSITES[f"open {app_command}"]
        open_website(engine, url, f"Opening {name}.")

    elif search_query is not None:
        search_web(engine, search_query)

    elif app_command in ("codebox", "code box"):
        open_codebox(engine)

    elif app_command in APPS:
        name, arguments = APPS[app_command]
        open_app(engine, name, arguments)

    elif APP_VERB.match(command):
        open_installed_app(engine, app_command)

    elif re.fullmatch(
        r"what day is (?:it|today)|(?:what(?:'s| is)|tell me|give me) (?:the date|today's date)",
        command.replace("’", "'"),
    ):
        today = datetime.now()
        speak(engine, f"Today is {today:%A, %B} {today.day}, {today.year}.")

    elif re.fullmatch(
        r"what does the clock say|what time is it(?: now)?|(?:what(?:'s| is)|tell me|give me) the (?:current )?time",
        command.replace("’", "'"),
    ):
        current_time = datetime.now().strftime("%I:%M %p")
        speak(engine, "The time is " + current_time)

    elif re.fullmatch(
        r"who (?:made|created|built|developed) (?:you|iris)|who is your developer",
        command,
    ):
        speak(engine, f"I was developed by {IRIS_DEVELOPER}.")

    elif "your name" in command:
        speak(engine, "My name is Iris, your personal assistant.")

    elif command in ("help", "what can you do"):
        speak(
            engine,
            "Ask me to open Chrome, YouTube, WhatsApp, Visual Studio Code, "
            "Dev C plus plus, File Explorer, or a basic Windows app. "
            "I can also save and read notes, search the web, calculate, "
            "call Sis on WhatsApp, draft a WhatsApp message, and tell you the date or time. Ask me to search YouTube or Chrome and open apps by their Start menu name. You can join several requests in one sentence. With Gemini enabled, you can also ask me general questions.",
        )

    elif conversation is not None:
        answer_online(engine, message, conversation, fallback=reply)

    elif reply is not None:
        speak_fallback(engine, reply, "")

    else:
        speak(engine, "I'm not sure how to respond to that yet. Could you ask in a different way?")


def main(on_status=None):
    if not (MODEL_PATH / "am").is_dir():
        if on_status is not None:
            raise RuntimeError("Speech model not found. Run download_model.py first.")
        print("Speech model not found. Run download_model.py first.")
        return

    SetLogLevel(-1)
    print("Loading Iris. Please wait...")
    model = Model(str(MODEL_PATH))

    microphone = sd.query_devices(kind="input")
    sample_rate = int(microphone["default_samplerate"])

    with windows_voice() as engine:
        run_voice_session(model, sample_rate, engine, on_status)


def run_voice_session(model, sample_rate, engine, on_status):
    recognizer = sr.Recognizer()
    recognizer.operation_timeout = 10
    recognizer.pause_threshold = 0.65

    if on_status is None:
        speak(engine, "Iris is ready. Say Hi Iris or Hey Iris to wake me.")

    while True:
        if on_status is not None:
            on_status("idle")
        pending_request = wait_for_wake(model, sample_rate)
        if on_status is not None:
            on_status("working" if pending_request else "listening")
        if not pending_request:
            speak(engine, "Hi! I’m listening.")

        conversation = deque(maxlen=8)
        follow_up = False
        while True:
            try:
                message = pending_request or listen(
                    engine, recognizer, sample_rate, follow_up=follow_up
                ).strip()
                pending_request = ""
                if on_status is not None:
                    on_status("working")
                print("You:", message)
                sleep_requested = False
                for task in split_tasks(message):
                    command = task.lower().rstrip(".!?").strip()
                    command = command.removesuffix(" please").strip()
                    if not command:
                        continue

                    if command in STOP_COMMANDS:
                        speak(engine, "Goodbye!")
                        return
                    if command in ("go to sleep", "back to sleep"):
                        speak(engine, "Say Hi Iris or Hey Iris when you need me.")
                        sleep_requested = True
                        break

                    handle_command(engine, task, command, conversation)

                if sleep_requested:
                    break
                follow_up = True
                if on_status is not None:
                    on_status("listening")

            except sr.WaitTimeoutError:
                if not follow_up:
                    speak(engine, "I missed that. Say Hi Iris to try again.")
                break

            except sr.UnknownValueError:
                speak(engine, "I missed that. Say Hi Iris to try again.")
                break

            except (sr.RequestError, TimeoutError) as error:
                print("Recognition service error:", error)
                speak(engine, "I could not reach the speech service.")
                break

            except RuntimeError as error:
                print("Recording error:", error)
                speak(engine, "Recording was interrupted. Please try again.")
                break



def run_overlay():
    import math
    import queue
    import threading
    import tkinter.messagebox as fallback_dialog

    try:
        from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
        from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient
        from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QWidget
    except ImportError:
        fallback_dialog.showerror(
            "Iris", r'Install the interface with .\.venv\Scripts\python.exe -m pip install PySide6-Essentials'
        )
        return

    events = queue.SimpleQueue()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)

    class Overlay(QWidget):
        def __init__(self):
            super().__init__(
                None,
                Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint,
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setFixedSize(392, 120)
            self.status = "listening"
            self.phase = 0.0

            title = QLabel("Iris", self)
            title.setGeometry(124, 29, 200, 33)
            title.setStyleSheet("color: #f5f8ff; background: transparent;")
            title.setFont(QFont("Segoe UI Variable Display", 22, QFont.Weight.DemiBold))

            self.caption = QLabel(self)
            self.caption.setGeometry(126, 66, 224, 24)
            self.caption.setFont(QFont("Segoe UI Variable Text", 11))

            exit_button = QPushButton("×", self)
            exit_button.setGeometry(337, 26, 31, 30)
            exit_button.setAccessibleName("Quit Iris")
            exit_button.setToolTip("Quit Iris")
            exit_button.setCursor(Qt.CursorShape.PointingHandCursor)
            exit_button.setStyleSheet("""
                QPushButton { color: #dce5f5; background: #202b42; border: 1px solid #32405c;
                               border-radius: 9px; font-size: 18px; }
                QPushButton:hover { color: white; background: #354462; }
            """)
            exit_button.clicked.connect(app.quit)

            self.animation = QTimer(self)
            self.animation.setTimerType(Qt.TimerType.PreciseTimer)
            self.animation.timeout.connect(self.animate)

        def animate(self):
            self.phase = (self.phase + 0.045) % math.tau
            self.update()

        def show_status(self, status):
            if status == "idle":
                self.animation.stop()
                self.hide()
                return
            self.status = status
            listening = status == "listening"
            self.caption.setText("Listening…" if listening else "Working on it…")
            self.caption.setStyleSheet(
                "background: transparent; color: " + ("#a7eaff" if listening else "#d8c4ff")
            )
            if not self.isVisible():
                screen = app.screenAt(QCursor.pos()) or app.primaryScreen()
                area = screen.availableGeometry()
                self.move(area.right() - self.width() - 21, area.bottom() - self.height() - 20)
                self.show()
                self.animation.start(16)
            self.update()

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            no_pen = Qt.PenStyle.NoPen

            painter.setPen(no_pen)
            for offset, alpha in ((9, 20), (7, 29), (5, 43)):
                painter.setBrush(QBrush(QColor(3, 6, 15, alpha)))
                painter.drawRoundedRect(QRectF(9 - offset / 2, 9, 374 + offset, 97 + offset), 30, 30)

            panel = QLinearGradient(15, 6, 355, 119)
            panel.setColorAt(0, QColor(28, 43, 68, 245))
            panel.setColorAt(0.54, QColor(17, 26, 46, 247))
            panel.setColorAt(1, QColor(22, 22, 47, 242))
            painter.setBrush(QBrush(panel))
            painter.setPen(QPen(QBrush(QColor(133, 158, 217, 93)), 1))
            painter.drawRoundedRect(QRectF(6, 5, 380, 103), 29, 29)

            listening = self.status == "listening"
            accent = QColor("#65e8ff" if listening else "#c59aff")
            center = QPointF(65, 57)
            glow = QRadialGradient(center, 53)
            glow.setColorAt(0, QColor(accent.red(), accent.green(), accent.blue(), 117))
            glow.setColorAt(0.69, QColor(accent.red(), accent.green(), accent.blue(), 70))
            glow.setColorAt(1, QColor(accent.red(), accent.green(), accent.blue(), 0))
            painter.setPen(no_pen)
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(center, 53, 53)

            body = QRadialGradient(QPointF(55, 41), 55)
            body.setColorAt(0, QColor("#314f81"))
            body.setColorAt(0.55, QColor("#18284d"))
            body.setColorAt(1, QColor("#10182f"))
            painter.setBrush(QBrush(body))
            painter.setPen(QPen(QBrush(QColor(146, 176, 233, 117)), 1))
            painter.drawEllipse(center, 32, 32)

            orbit = QRectF(27, 19, 76, 76)
            start_angle = round(math.degrees(self.phase) * 16)
            painter.setPen(QPen(QBrush(accent), 2.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(orbit, start_angle, 110 * 16)
            painter.setPen(QPen(QBrush(QColor("#9488ff")), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(orbit, start_angle + 180 * 16, 56 * 16)

            painter.setPen(QPen(QBrush(accent), 3.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for index in range(5):
                x = 49 + index * 8
                height = 4 + (10 - abs(index - 2) * 2) * (
                    0.5 + 0.5 * math.sin(self.phase * 3 + index * 0.86)
                )
                painter.drawLine(QPointF(x, 57 - height), QPointF(x, 57 + height))

    overlay = Overlay()

    def run_voice():
        try:
            main(lambda state: events.put((state, "")))
        except Exception as error:
            events.put(("error", str(error)))
        finally:
            events.put(("exit", ""))

    def poll():
        while True:
            try:
                state, detail = events.get_nowait()
            except queue.Empty:
                return
            if state == "exit":
                app.quit()
                return
            if state == "error":
                poll_timer.stop()
                QMessageBox.critical(None, "Iris", detail)
                app.quit()
                return
            overlay.show_status(state)

    poll_timer = QTimer()
    poll_timer.timeout.connect(poll)
    poll_timer.start(33)
    if "--preview" in sys.argv:
        overlay.show_status("listening")
        demo_timer = QTimer()
        demo_timer.timeout.connect(
            lambda: overlay.show_status("working" if overlay.status == "listening" else "listening")
        )
        demo_timer.start(2400)
    else:
        threading.Thread(target=run_voice, daemon=True, name="Iris voice").start()
    app.exec()


if __name__ == "__main__":
    for stream in ("stdout", "stderr"):
        if getattr(sys, stream) is None:
            setattr(sys, stream, open(os.devnull, "w", encoding="utf-8"))
    try:
        if "--voice-test" in sys.argv:
            with windows_voice() as engine:
                speak(engine, "Hello! I'm Iris. You can hear my voice now.")
        elif "--console" in sys.argv:
            main()
        else:
            run_overlay()
    except KeyboardInterrupt:
        print("\nIris stopped.")
    except sd.PortAudioError as error:
        print("Microphone error:", error)