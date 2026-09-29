# Entry point. Vercel and `flask run` both look for the `app` object here.
from classtracker import create_app

app = create_app()
