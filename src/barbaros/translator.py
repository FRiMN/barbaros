import ollama

"""
Interrupt inference: <https://github.com/ollama/ollama/issues/9813>.
"""


def translate_text(text: str, target_language: str, model: str) -> ollama.GenerateResponse:
    from .resources_loader import Resource

    system_prompt = Resource.translation_agent_system_prompt.value

    text_prompt = f"""
    Target Language: {target_language}
    Text: {text}
    """

    # response = ollama.chat(model=model, messages=[
    #     {
    #         'role': 'system',
    #         'content': system_prompt,
    #     },
    #     {
    #         'role': 'user',
    #         'content': text_prompt,
    #     },
    # ])
    response = ollama.generate(model=model, system=system_prompt, prompt=text_prompt, think=False)
    return response


if __name__ == "__main__":
    text_to_translate = input("Enter the text to translate: ")

    response = translate_text(text_to_translate, "ru", "qwen3:8b")
    translated_text = response.response
    seconds = response.total_duration // 1000 / 1000 / 1000

    print(f"Translated text: \n{translated_text}")
    print(f"Translation took {seconds:.2f} seconds.")
