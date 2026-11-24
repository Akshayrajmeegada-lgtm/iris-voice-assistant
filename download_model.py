from pathlib import Path
from urllib.request import urlretrieve
from zipfile import ZipFile

project_folder = Path(__file__).resolve().parent
model_folder = project_folder / "vosk-model-small-en-us-0.15"
zip_path = project_folder / "vosk-model-small-en-us-0.15.zip"

url = (
    "https://alphacephei.com/vosk/models/"
    "vosk-model-small-en-us-0.15.zip"
)

if (model_folder / "am").is_dir() and (model_folder / "conf").is_dir():
    print("The model is already ready.")
else:
    print("Downloading the speech model. Please wait...")
    urlretrieve(url, zip_path)

    print("Extracting the model...")
    with ZipFile(zip_path) as archive:
        archive.extractall(project_folder)

    print("Model ready:", model_folder)