# models_check.py
import requests

api_key = "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"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

response = requests.get("https://api.groq.com/openai/v1/models", headers=headers)

print(f"Status: {response.status_code}")
if response.status_code == 200:
    models = response.json()
    print("\n📋 MODELOS DISPONÍVEIS:")
    for model in models['data']:
        print(f"  • {model['id']}")
else:
    print(f"Erro: {response.text}")