import requests

api_key = "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"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

payload = {
    "model": "llama-3.3-70b-versatile",  # Modelo funcionando
    "messages": [
        {"role": "user", "content": "Oi, apenas um teste rápido"}
    ],
    "max_tokens": 50
}

response = requests.post(
    "https://api.groq.com/openai/v1/chat/completions", 
    json=payload, 
    headers=headers
)

print(f"Status: {response.status_code}")
print(f"Resposta: {response.text}")