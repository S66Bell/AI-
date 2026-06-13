"""Speech-to-text and text-to-speech, degrading gracefully when unavailable.

Voice is entirely optional. If the optional dependencies (SpeechRecognition,
pyttsx3, PyAudio) aren't installed, `voice_available()` returns False and the
assistant stays text-only.
"""

from __future__ import annotations


def voice_available() -> bool:
    try:
        import pyttsx3  # noqa: F401
        import speech_recognition  # noqa: F401

        return True
    except ImportError:
        return False


class Voice:
    """Thin wrapper over pyttsx3 (TTS) and SpeechRecognition (STT)."""

    def __init__(self) -> None:
        import pyttsx3
        import speech_recognition as sr

        self._engine = pyttsx3.init()
        self._recognizer = sr.Recognizer()
        self._sr = sr

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        self._engine.say(text)
        self._engine.runAndWait()

    def listen(self, timeout: float | None = None) -> str | None:
        """Capture one utterance from the microphone and transcribe it.

        Returns the transcribed text, or None if nothing was understood.
        """
        with self._sr.Microphone() as source:
            self._recognizer.adjust_for_ambient_noise(source, duration=0.4)
            try:
                audio = self._recognizer.listen(source, timeout=timeout)
            except self._sr.WaitTimeoutError:
                return None
        try:
            return self._recognizer.recognize_google(audio)
        except (self._sr.UnknownValueError, self._sr.RequestError):
            return None
