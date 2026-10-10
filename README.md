# AI Movie Studio — Streamlit starter app

## Features
- Script text box and TXT upload
- Multiple Edge TTS voices with simple character-name routing
- One generated image per scene, with a fallback background if image generation fails
- Optional subtitles, gentle camera zoom, and background music
- Per-scene MP4 files and project-state checkpoint
- Resume button, progress display, error messages, MP4 preview/download

## Important limitations
This starter version makes narrated slideshow-style videos with camera motion. It does **not** generate true AI video footage. True text-to-video requires a separate video generation model/provider and may require an API key or paid credits. The Pollinations image endpoint is an external service and may be slow, rate-limited, or change.

The target duration is an estimate, not a guarantee. The script length and generated speech determine the actual runtime.

## Install locally
Use Python 3.10 or 3.11 if possible.

```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

MoviePy needs FFmpeg. `imageio-ffmpeg` often supplies a usable FFmpeg binary, but if video export fails, install FFmpeg for your operating system and ensure it is available.

## Deploy
For Streamlit Community Cloud, upload `app.py` and `requirements.txt` to a GitHub repository and deploy that repository. Note that cloud limits can make long movies impractical; use a local computer or a dedicated server for longer jobs.

## Suggested next upgrades
1. Use a proper image-generation API with documented limits and a key stored in Streamlit secrets.
2. Add a scene-by-scene editor and character reference images.
3. Add a real text-to-video provider adapter for scenes that need motion.
4. Store checkpoints in persistent disk/object storage if deployed to a cloud service.
5. Add SRT/VTT subtitle export and a project ZIP download.
