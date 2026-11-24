import json
from pathlib import Path

import pyttsx3
import sounddevice as sd
from vosk import Model, KaldiRecognizer, SetLogLevel


def main():
    model_path = (
        Path(__file__).resolve().parent
        / "vosk-model-small-en-us-0.15"
    )

    if not (model_path / "am").is_dir():
        print("Model not found. Run download_model.py first.")
        return

    SetLogLevel(-1)

    print("Loading the speech model...")
    model = Model(str(model_path))

    microphone = sd.query_devices(kind="input")
    sample_rate = int(microphone["default_samplerate"])
    recognizer = KaldiRecognizer(model, sample_rate, json.dumps(["hey iris", "[unk]"]))

    print('Say "Hey Iris", then pause.')
    print("Press Ctrl + C to stop.")

    with sd.RawInputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="int16"
    ) as stream:
        while True:
            recording, overflowed = stream.read(4000)

            if overflowed:
                recognizer.Reset()
                continue

            if recognizer.AcceptWaveform(bytes(recording)):
                result = json.loads(recognizer.Result())
                text = result.get("text", "").strip()

                if text:
                    print("Heard:", text)

                if " hey iris " in f" {text} ":
                    print("Wake phrase detected!")
                    break

    # The microphone closes before Iris speaks.
    engine = pyttsx3.init()
    engine.setProperty("rate", 170)
    engine.say("Yes, I am listening.")
    engine.runAndWait()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nWake test stopped.")
    except sd.PortAudioError as error:
        print("Microphone error:", error)