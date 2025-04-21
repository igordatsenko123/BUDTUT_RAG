from openai import OpenAI
from config import OPENAI_API_KEY
import faiss
import numpy as np
import os
import tiktoken

client = OpenAI(api_key=OPENAI_API_KEY)

def split_text(text, max_tokens=800, overlap=100):
    """Разбивает текст на чанки по количеству токенов с перекрытием"""
    enc = tiktoken.get_encoding("cl100k_base")
    words = text.split()

    chunks = []
    start = 0

    while start < len(words):
        chunk = []
        token_count = 0
        i = start

        while i < len(words):
            tokens = len(enc.encode(words[i]))
            if token_count + tokens > max_tokens:
                break
            chunk.append(words[i])
            token_count += tokens
            i += 1

        chunks.append(" ".join(chunk))
        start += max(1, len(chunk) - overlap)

    return chunks

def embed_text(chunks):
    embeddings = []
    for i, chunk in enumerate(chunks):
        print(f"  → Эмбеддинг чанка {i+1}/{len(chunks)}...")
        resp = client.embeddings.create(
            model="text-embedding-3-small",
            input=chunk
        )
        embeddings.append(resp.data[0].embedding)
    return embeddings

def save_faiss(chunks, embeddings, path="faiss_v2.index"):
    dim = len(embeddings[0])
    index = faiss.IndexFlatL2(dim)
    index.add(np.array(embeddings).astype("float32"))
    faiss.write_index(index, path)

    with open("chunks_v2.txt", "w", encoding="utf-8") as f:
        f.write("\n\n-----\n\n".join(chunks))

# ===== Основной код =====
all_chunks = []
all_embeddings = []

for filename in os.listdir("data"):
    if filename.endswith(".txt"):
        print(f"📄 Обрабатывается файл: {filename}")
        with open(os.path.join("data", filename), "r", encoding="utf-8") as f:
            text = f.read()

        chunks = split_text(text, max_tokens=800, overlap=100)
        embeddings = embed_text(chunks)

        all_chunks.extend(chunks)
        all_embeddings.extend(embeddings)

save_faiss(all_chunks, all_embeddings)
print("✅ Векторная база v2 успешно обновлена!")
