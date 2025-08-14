import ollama
import time

def translate_text(text):
    system_prompt = open('translation_agent_prompt.txt').read()
    try:
        response = ollama.chat(model='gemma3:12b', messages=[
            {
                'role': 'system',
                'content': system_prompt,
            },
            {
                'role': 'user',
                # 'content': f"Translate the following text to Russian: {text}",
                'content': f"Переведи на русский язык следующий текст: {text}",
            },
        ])
        return response['message']['content']
    except Exception as e:
        return f"Error during translation: {e}"

if __name__ == "__main__":
    text_to_translate = input("Enter the text to translate: ")
    start_time = time.time()
    translated_text = translate_text(text_to_translate)
    end_time = time.time()
    print(f"Translated text: \n{translated_text}")
    print(f"Translation took {end_time - start_time:.2f} seconds.")
