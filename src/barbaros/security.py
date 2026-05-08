import keyring
from keyring.errors import PasswordDeleteError

class KeySecurityManager(object):
    SERVICE_NAME = "barbaros:providers_api_keys"

    def __init__(self, provider_name: str):
        self.provider_name = provider_name

    def set(self, key: str):
        """Stores an API key in the system keyring."""
        keyring.set_password(KeySecurityManager.SERVICE_NAME, self.provider_name, key)

    def get(self) -> str | None:
        """Retrieves an API key from the system keyring."""
        return keyring.get_password(KeySecurityManager.SERVICE_NAME, self.provider_name)

    def delete(self):
        """Removes an API key from the system keyring."""
        try:
            keyring.delete_password(KeySecurityManager.SERVICE_NAME, self.provider_name)
        except PasswordDeleteError:
            pass  # Already deleted
