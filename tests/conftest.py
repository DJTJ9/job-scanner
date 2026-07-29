"""Session-Defaults für Tests: Fernet-Key für den Boot-Assert in create_app()."""
import os

from cryptography.fernet import Fernet

os.environ.setdefault("JOBSCANNER_FERNET_KEY", Fernet.generate_key().decode())
