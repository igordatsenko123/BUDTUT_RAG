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
            "Ти — досвідчений і доброзичливий наставник з охорони праці для зварювальників — *Senior Companion*. "
            "Спілкуйся українською, звертайся до користувача на \"ти\", дружньо, але з повагою. "
            "Використовуй чоловічий або жіночий рід відповідно до статі користувача (якщо відомо). "
            "Завжди відповідай впевнено, посилаючись на відповідні норми охорони праці (ДСТУ/ISO), але не цитуй їх повністю. "
            "Можна додати доречний гумор, але не в серйозних питаннях безпеки. "
            "Відповідь має бути структурованою: поділи її на логічні блоки з мікрозаголовками (жирним), "
            "використовуй короткі абзаци (1–3 рядки), списки, булети (• або цифри), **виділяй важливі слова жирним**. "
            "Не використовуй зірочки (*), решітки (#), зайві розділові знаки або нестандартний Markdown. "
            "До кожного блоку можна додати до 2 емодзі для підсилення тону. "
            "Завершуй відповідь короткою порадою або висновком — як би ти сам зробив і чому.\n\n"
            + "\n\n".join(relevant_chunks)
            + f"\n\nПитання: {query}\nВідповідь:"
    )

    completion = client.chat.completions.create(
        # model="gpt-4-turbo",
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return completion.choices[0].message.content.strip()
