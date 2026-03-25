import base64

from ollama import Client, GenerateResponse

"""
Interrupt inference: <https://github.com/ollama/ollama/issues/9813>.
"""


client = Client("http://192.168.1.10:11434")


def translate_text(text: str, target_language: str, model: str) -> GenerateResponse:
    from .resources_loader import Resource

    system_prompt = Resource.translation_agent_system_prompt.value

    text_prompt = f"""
    Target Language: {target_language}
    Text: {text}
    """

    response = client.generate(
        model=model, system=system_prompt, prompt=text_prompt, think=False
    )
    return response


def ocr_image(image_bytes: bytes, model: str) -> str:
    from .resources_loader import Resource

    system_prompt = Resource.ocr_agent_system_prompt.value
    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    response = client.generate(
        model=model,
        images=[base64_image],
        system=system_prompt,
        prompt="Extract the text in the image.",
        think=False,
    )
    return response.response


if __name__ == "__main__":
    text_to_translate = input("Enter the text to translate: ")

    response = translate_text(text_to_translate, "ru", "qwen3:8b")
    translated_text = response.response
    seconds = response.total_duration // 1000 / 1000 / 1000

    print(f"Translated text: \n{translated_text}")
    print(f"Translation took {seconds:.2f} seconds.")
