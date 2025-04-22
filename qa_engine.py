from openai import OpenAI
import faiss
import numpy as np
from config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)

index = faiss.read_index("faiss_v2.index")
with open("chunks_v2.txt", "r", encoding="utf-8") as f:
    chunks = f.read().split("\n\n-----\n\n")

def get_answer(query, top_k=10):
    q_embed = client.embeddings.create(
        model="text-embedding-3-small",  # или large
        input=query
    ).data[0].embedding

    D, I = index.search(np.array([q_embed], dtype="float32"), top_k)
    relevant_chunks = [chunks[i] for i in I[0]]

    prompt = (
        "Ти – агент із навчання охорони праці зварювальників. Завжди відповідай чітко, стисло і структуровано. Використовуй списки (булети або цифри), виділяй жирним ключові терміни. Пояснюй складне простими словами. Якщо відповідь краще пояснити через схему чи картинку – дай її детальний текстовий опис для генерації зображення. Якщо питання поставлено дуже розмито, попроси уточнити, що саме мається на увазі. Говори як друг, який ідеально знає тему і хоче допомогти: використовуй, дружній, неформальний стиль\n\n"
        + "\n\n".join(relevant_chunks)
        + f"\n\nПитання: {query}\nВідповідь:"
    )

    completion = client.chat.completions.create(
        # model="gpt-4-turbo",
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return completion.choices[0].message.content.strip()
