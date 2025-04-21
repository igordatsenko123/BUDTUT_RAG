from docx import Document
import os
import re

def clean_text(text):
    # Удаляем повторяющиеся пробелы, табы, переносы строк
    text = re.sub(r"\s+", " ", text)
    # Убираем лишние пробелы вокруг знаков препинания
    text = re.sub(r"\s([.,!?;:])", r"\1", text)
    return text.strip()

def extract_clean_text(docx_path):
    doc = Document(docx_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    raw_text = "\n\n".join(paragraphs)
    return clean_text(raw_text)

def process_folder(input_folder="raw_docx", output_folder="data"):
    os.makedirs(output_folder, exist_ok=True)
    for filename in os.listdir(input_folder):
        if filename.endswith(".docx"):
            print(f"Обработка: {filename}")
            input_path = os.path.join(input_folder, filename)
            output_name = filename.replace(".docx", "_clean.txt")
            output_path = os.path.join(output_folder, output_name)

            clean = extract_clean_text(input_path)

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(clean)

    print("✅ Очистка завершена.")

# Запуск
if __name__ == "__main__":
    process_folder()
