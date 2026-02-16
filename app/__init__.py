from fastapi.templating import Jinja2Templates
import os

# Resolve templates directory relative to the project root (one level up from app/)
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(_project_root, "templates"))
