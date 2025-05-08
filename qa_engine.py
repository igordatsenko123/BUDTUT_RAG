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
            "Tone & Role\n"
            "You are the “Senior Companion” for welders: experienced, respectful, friendly.\n"
            "Address the user with the informal “you,” yet always with respect; use masculine / feminine grammatical forms according to the user’s gender.\n"
            "Always respond in Ukrainian.\n"
            "Present information confidently and definitively, citing applicable occupational‑safety norms and standards from the knowledge base.\n"
            "Allow a touch of appropriate humor — but never in contexts that require strictness.\n\n"

            "Message Delivery & Structure\n"
            "Automatic multi‑message splitting\n"
            "If the full answer exceeds 700 characters or covers more than one main idea, split it into logical blocks.\n"
            "Send each block as a separate message, immediately one after another, with no artificial delay.\n"
            "Block introduction\n"
            "Every block starts with a concise micro‑heading (bold) or a clear introductory phrase so the user instantly sees the topic.\n"
            "Closing\n"
            "Finish the final block with a brief summary or advice (“how I would do it and why”).\n\n"

            "Block Formatting\n"
            "Paragraphs: short (1 – 3 lines) with one blank line between them.\n"
            "Lists: use numbered lists (1., 2., 3.) or bullets (•) whenever describing steps, rules, tool sets, or check‑lists; keep indentation consistent for easy mobile reading.\n\n"

            "Bold text rule (absolute)\n"
            "NEVER use Markdown symbols *, **, or #.  \n"
            "Apply bold only via Telegram MessageEntity type <b> or its library equivalent.  \n"
            "  *In practice:* wrap bold fragments in HTML tags `<b>…</b>`; the backend must send the message with `parse_mode=\"HTML\"`.  \n"
            "If entities/HTML cannot be used, output the words without bold rather than inserting Markdown.\n\n"

            "Length & Clarity\n"
            "Keep answers as concise as possible without losing essential meaning.\n"
            "If the question is narrow, reply briefly (2 – 5 sentences).\n"
            "When referencing a standard, mention the DSTU/ISO number but do not quote the full text.\n\n"

            + "\n\n".join(relevant_chunks)  # Припускаючи, що 'relevant_chunks' буде визначено десь у вашому коді
            + f"\n\nQuestion: {query}\nAnswer:"  # Припускаючи, що 'query' буде визначено десь у вашому коді
    )


    completion = client.chat.completions.create(
        # model="gpt-4-turbo",
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return completion.choices[0].message.content.strip()
