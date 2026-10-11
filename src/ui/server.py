"""
The App.

Creates the FastAPI app, serves the page, and mounts the static files. Nothing
else — this is the assembly, not the work.

Routers join as their tasks land. Each lives in `src/ui/routes/`, one module
per tab.
"""

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.core.config import APP_NAME, STATIC_DIR
from src.ui.routes import files, performance, setup

app = FastAPI(title=APP_NAME)

# --- ROUTES ---

# Setup first, because it is what a machine with nothing installed needs.
app.include_router(setup.router)
app.include_router(files.router)
app.include_router(performance.router)

# --- PAGE ---


@app.get("/")
def index():
    """Serves the single page app."""
    return FileResponse(STATIC_DIR / "index.html")


# --- STATIC FILES ---


class RevalidatedStatics(StaticFiles):
    """
    Static files the browser must re-check before reusing.

    Notes:
        Without a Cache-Control header a browser caches by its own heuristic,
        and an ES module it has already evaluated stays in the module map even
        across a reload. Someone updates the app, opens it, and gets
        yesterday's JavaScript — which looks like the new feature simply not
        working, with nothing on screen to say why. It cost minicut an hour.

        `no-cache` does not mean "do not store": it means "ask before reusing".
        With the ETag the server already sends, an unchanged file costs one 304
        and no body, which on localhost is free.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


# Mounted last so it cannot shadow the API routes above.
app.mount("/static", RevalidatedStatics(directory=STATIC_DIR), name="static")
