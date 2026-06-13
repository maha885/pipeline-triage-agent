import os, time
from openai import OpenAI, RateLimitError
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    base_url=f"{os.getenv('FOUNDRY_ENDPOINT').rstrip('/')}/openai/v1",
    api_key=os.getenv("FOUNDRY_API_KEY"),
)

for attempt in range(5):
    try:
        resp = client.chat.completions.create(
            model=os.getenv("FOUNDRY_MODEL_NAME"),
            messages=[{"role": "user", "content": "Say hello in one word."}],
        )
        print(resp.choices[0].message.content)
        break
    except RateLimitError as e:
        print(f"Attempt {attempt+1}: rate limited, waiting...")
        print(e)
        time.sleep(15)