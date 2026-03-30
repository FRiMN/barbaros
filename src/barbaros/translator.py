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

    try:
        response = client.generate(
            model=model, system=system_prompt, prompt=text_prompt, think=False
        )
        return response
    except Exception as e:
        raise RuntimeError(f"Translation failed: {e}")


def ocr_image(image_bytes: bytes, model: str) -> str:
    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    try:
        response = client.generate(
            model=model,
            images=[base64_image],
            prompt="Extract the text in the image.",
            think=False,
        )
        return response.response
    except Exception as e:
        raise RuntimeError(f"OCR failed: {e}")


def ocr_openrouter(image_bytes: bytes, model: str) -> str:
    import requests

    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    image_url = f"data:image/png;base64,{base64_image}"
    model = "nvidia/nemotron-nano-12b-v2-vl:free"

    headers = {
        "Authorization": "Bearer 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",
        "Content-Type": "application/json",
    }
    data = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Extract the text in the image. "
                        "Return only the recognized text without adding any other information.",
                    },
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
        "temperature": 0.1,
    }

    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
        )
        json_resp = response.json()
        print(f"{json_resp=}")
        if "error" in json_resp:
            e = json_resp['error']
            raise RuntimeError(f"OCR failed (code {e['code']}). {e['message']}: {e['metadata']['raw']}")
        response.raise_for_status()
        print(f"{response.elapsed=}")
        return json_resp["choices"][0]["message"]["content"]
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"OCR failed: {e}")


if __name__ == "__main__":
    text_to_translate = input("Enter the text to translate: ")

    response = translate_text(text_to_translate, "ru", "qwen3:8b")
    translated_text = response.response
    seconds = response.total_duration // 1000 / 1000 / 1000

    print(f"Translated text: \n{translated_text}")
    print(f"Translation took {seconds:.2f} seconds.")
