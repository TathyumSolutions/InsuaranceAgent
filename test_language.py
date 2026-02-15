"""Test language detection"""
from voice.handler import VoiceHandler

# Create a test handler instance
handler = VoiceHandler('test', 'test', None, 'fake-key')

# Test language detection
test_phrases = [
    'Hello, is there anyone online?',
    '¿Es el anime online?', 
    'Hola, ¿y verán alguien?',
    'My member ID is MB123456',
    'Can you help me?',
    'Hello there',
    'Hi, I need help',
    'Insurance eligibility please'
]

print("Language Detection Test:")
print("-" * 50)
for phrase in test_phrases:
    is_non_english = handler._is_non_english(phrase)
    print(f'Phrase: "{phrase}"')
    print(f'  -> Non-English: {is_non_english}')
    print()