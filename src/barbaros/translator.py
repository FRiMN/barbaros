import ollama
import time
from importlib.resources import open_text


def translate_text(text: str) -> str:
    system_prompt = open_text('barbaros.resources', 'translation_agent_prompt.md').read()
    text_prompt = f"""
    Target Language: ru
    Text: {text}
    """
    try:
        response = ollama.chat(model='gemma3:12b', messages=[
            {
                'role': 'system',
                'content': system_prompt,
            },
            {
                'role': 'user',
                'content': text_prompt,
            },
        ])
        # print(f"{response=}")
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
