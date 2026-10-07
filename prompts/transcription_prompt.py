"""Short Whisper spelling/context hint, not a chat-style instruction prompt.

Groq documents a 224-token maximum. This compact Hindi hint leaves language
automatic for Hindi/Bhojpuri/English mixtures; it cannot guarantee verbatim dialect.
"""

WHISPER_CONTEXT_PROMPT = (
    "पुलिस बातचीत। हिंदी, भोजपुरी और English शब्द। "
    "नाम, स्थान, तारीख, समय, वाहन नंबर और मोबाइल नंबर।"
)
