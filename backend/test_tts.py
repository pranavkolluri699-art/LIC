from tts import text_to_speech

try:
    filename = text_to_speech("Hello, this is a test.")
    print("Created:", filename)
except Exception as e:
    print("Error:", e)