# Run Frame Echo locally

Use Python 3.13, the version used for development and verification. Extract the repository ZIP before running the commands.

## Start Frame Echo

### macOS

Open a terminal in the repository root and run these commands.

```sh
cd project
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Windows (Command Prompt)

Open the extracted `project` folder in File Explorer. It contains `requirements.txt`. Type `cmd` in the address bar and press Enter to open Command Prompt in that folder. Run each line after the previous one finishes.

```bat
py -3.13 --version
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The version check should show Python 3.13.x. Wait for the terminal to display `Uvicorn running` and leave it open while using Frame Echo.

Open [Frame Echo](http://127.0.0.1:8000) and choose **Try a synthetic demo**, or upload a video and a reference artwork. The **Colour & layout** method is available after the basic installation. Select a result to jump to its time in the uploaded video. The app stores the original video, extracted frames and search exports under project/data/runtime/.

## Optional CLIP image features

Stop the server with Ctrl+C. From the same `project` folder, use the commands for your operating system to install the dependencies, download the model and restart the server.

### macOS

Keep the virtual environment active and run these commands.

```sh
python -m pip install -r requirements-clip.txt
python scripts/download_clip.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Windows (Command Prompt)

Use the virtual environment created in the Windows setup above.

```bat
.\.venv\Scripts\python.exe -m pip install -r requirements-clip.txt
.\.venv\Scripts\python.exe scripts\download_clip.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The downloader fetches the OpenCLIP checkpoint (about 605 MB) from Hugging Face. The [recorded checkpoint](docs/openclip-checkpoint.json) identifies the revision and hash used during development. The downloader resolves the model's currently available revision and records its checksum locally. After restarting the server, refresh the browser and select **CLIP image features** under **How to look**. Follow the [Monet replay instructions](../demo/README.md) to reproduce the demonstration.

## Verification and source layout

Run the test command for your operating system from the `project` folder.

**macOS** (with the virtual environment active)

```sh
python -m unittest discover -s tests -v
```

**Windows (Command Prompt)**

```bat
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The API tests start a local test server. The repository includes the web interface, server, tests, synthetic fixture and development scripts. Some historical experiment scripts require their original research inputs. The [process log](docs/process-log.md) records those experiments and their settings.
