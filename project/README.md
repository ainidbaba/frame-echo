# Run Frame Echo locally

Use Python 3.13, the version used for development and verification. Open a terminal in the repository root.

~~~sh
cd project
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
~~~

On Windows PowerShell, enter the project folder and set up the environment with these commands. Then run the installation and start commands above.

~~~powershell
cd project
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
~~~

Open [Frame Echo](http://127.0.0.1:8000) and choose **Try a synthetic demo**, or upload a video and a reference artwork. The **Colour & layout** method is available after the basic installation. Select a result to jump to its time in the uploaded video. The app stores the original video, extracted frames and search exports under project/data/runtime/.

## Optional CLIP image features

Stop the server with Ctrl+C, keep the virtual environment active, and run these commands from the project folder.

~~~sh
python -m pip install -r requirements-clip.txt
python scripts/download_clip.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
~~~

The downloader fetches the OpenCLIP checkpoint (about 605 MB) from Hugging Face. The [recorded checkpoint](docs/openclip-checkpoint.json) identifies the revision and hash used during development. The downloader resolves the model's currently available revision and records its checksum locally. After restarting the server, **CLIP image features** should be available. Follow the [Monet replay instructions](../demo/README.md) to reproduce the demonstration.

## Verification and source layout

~~~sh
python -m unittest discover -s tests -v
~~~

The API tests start a local test server. The repository includes the web interface, server, tests, synthetic fixture and development scripts. Some historical experiment scripts require their original research inputs. The [process log](docs/process-log.md) records those experiments and their settings.
