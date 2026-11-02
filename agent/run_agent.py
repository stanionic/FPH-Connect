"""Point d'entrée de l'agent pour PyInstaller (les imports relatifs de fph_agent/__main__.py exigent un paquet)."""
import sys

from fph_agent.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
