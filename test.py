from openai import OpenAI

client = OpenAI(
  api_key="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"
)

completion = client.chat.completions.create(
  model="gpt-4o-mini",
  store=True,
  messages=[
    {"role": "user", "content": "write a haiku about ai"}
  ]
)

print(completion.choices[0].message);
