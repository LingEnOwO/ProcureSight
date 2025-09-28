from fastapi.openapi.utils import get_openapi
from apps.api.main import app
import json, pathlib

spec = get_openapi(
    title=app.title,
    version=app.version,
    description=app.description,
    routes=app.routes,
)
pathlib.Path("openapi.json").write_text(json.dumps(spec, indent=2))
print("Wrote openapi.json")