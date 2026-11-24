import sounddevice as sd
import speech_recognition as sr


recognizer = sr.Recognizer()
recognizer.operation_timeout = 10

try:
    microphone = sd.query_devices(kind="input")
    sample_rate = int(microphone["default_samplerate"])

    with sd.RawInputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="int16"
    ) as stream:
        print("Speak now! Recording for five seconds...")
        recording, overflowed = stream.read(sample_rate * 5)

    if overflowed:
        print("Audio was interrupted. Please run the test again.")
    else:
        print("Recognising your words...")

        audio = sr.AudioData(bytes(recording), sample_rate, 2)
        text = recognizer.recognize_google(audio, language="en-IN")

        print("You said:", text)

except sr.UnknownValueError:
    print("I could not understand. Please try speaking clearly.")
except sr.RequestError as error:
    print("Speech service error:", error)
except TimeoutError:
    print("The speech service took too long. Please try again.")
except sd.PortAudioError as error:
    print("Microphone error:", error)