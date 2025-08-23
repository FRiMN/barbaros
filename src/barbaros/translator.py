import ollama

"""
Interrupt inference: <https://github.com/ollama/ollama/issues/9813>.
"""


def translate_text(text: str) -> ollama.GenerateResponse:
    from .resources_loader import Resource

    model = "gemma3:12b"
    system_prompt = Resource.translation_agent_system_prompt.value

    text_prompt = f"""
    Target Language: ru
    Text: {text}
    """
    try:
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
        response = ollama.generate(model=model, system=system_prompt, prompt=text_prompt)
        # print(f"{response=}")
        return response
    except Exception as e:
        return f"Error during translation: {e}"


if __name__ == "__main__":
    text_to_translate = input("Enter the text to translate: ")

    response = translate_text(text_to_translate)
    translated_text = response.message.content
    seconds = response.total_duration // 1000 / 1000 / 1000

    print(f"Translated text: \n{translated_text}")
    print(f"Translation took {seconds:.2f} seconds.")
