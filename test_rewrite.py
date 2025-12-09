import openai
import os

# Use API key from environment
openai.api_key = os.getenv("OPENAI_API_KEY")

# Sample text to rewrite
text_to_rewrite = "This is a simple test. The cat sat on the mat."

# Call ChatCompletion
response = openai.ChatCompletion.create(
    model="gpt-3.5-turbo",
    messages=[{"role": "user", "content": f"Rewrite this text in a storytelling way: {text_to_rewrite}"}]
)

# Print rewritten text
rewritten_text = response['choices'][0]['message']['content']
print("Rewritten text:\n", rewritten_text)
