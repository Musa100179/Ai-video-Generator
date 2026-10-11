import asyncio
import json
import math
import os
import random
import re
import shutil
import tempfile
import time
from pathlib import Path
from io import BytesIO

import streamlit as st
import requests
from PIL import Image, ImageDraw, ImageFont
from gtts import gTTS   # <-- CHANGED: using gTTS instead of edge_tts

try:
    from moviepy import (
        ImageClip, AudioFileClip, VideoFileClip, concatenate_videoclips,
        CompositeAudioClip
    )
    MOVIEPY_V2 = True
except ImportError:
    from moviepy.editor import (
        ImageClip, AudioFileClip, VideoFileClip, concatenate_videoclips,
        CompositeAudioClip
    )
    MOVIEPY_V2 = False


# --------------------------- APP CONFIG ---------------------------
st.set_page_config(
    page_title="AI Movie Studio",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_TITLE = "🎬 AI Movie Studio"
DEFAULT_VOICES = {
    "Narrator — Aria (US female)": "en-US-AriaNeural",
    "Narrator — Guy (US male)": "en-US-GuyNeural",
    "Grandpa — Davis (US male)": "en-US-DavisNeural",
    "Hero — Jason (US male)": "en-US-JasonNeural",
    "Princess — Jenny (US female)": "en-US-JennyNeural",
    "Cute — Ana (US female)": "en-US-AnaNeural",
    "Urdu male — Asad": "ur-PK-AsadNeural",
    "Urdu female — Uzma": "ur-PK-UzmaNeural",
    "Hindi male — Madhur": "hi-IN-MadhurNeural",
    "Hindi female — Swara": "hi-IN-SwaraNeural",
}
STYLES = [
    "Cinematic realistic, dramatic lighting, film still",
    "3D animated family adventure, vibrant cinematic colors",
    "Detailed anime film, expressive characters",
    "Pakistani village, warm natural colors, realistic",
    "Epic fantasy, magical atmosphere, cinematic lighting",
    "Historical adventure, natural textures, cinematic",
]


# --------------------------- COMPAT HELPERS ---------------------------
def set_duration(clip, duration):
    return clip.with_duration(duration) if hasattr(clip, "with_duration") else clip.set_duration(duration)

def set_audio(clip, audio):
    return clip.with_audio(audio) if hasattr(clip, "with_audio") else clip.set_audio(audio)

def set_position(clip, position):
    return clip.with_position(position) if hasattr(clip, "with_position") else clip.set_position(position)

def set_start(clip, start):
    return clip.with_start(start) if hasattr(clip, "with_start") else clip.set_start(start)

def resize_clip(clip, size):
    return clip.resized(new_size=size) if hasattr(clip, "resized") else clip.resize(newsize=size)

def subclip(clip, start, end):
    return clip.subclipped(start, end) if hasattr(clip, "subclipped") else clip.subclip(start, end)

def write_clip(clip, path, **kwargs):
    return clip.write_videofile(str(path), **kwargs)


# --------------------------- STORY HELPERS ---------------------------
def parse_script(raw_text):
    """Each non-empty line becomes a scene; long paragraphs split by sentence."""
    lines = [line.strip() for line in raw_text.replace("\r", "").split("\n") if line.strip()]
    if len(lines) <= 2:
        lines = [s.strip() for s in re.split(r"(?<=[.!?؟])\s+", raw_text) if s.strip()]

    scenes = []
    for line in lines:
        if len(line) <= 420:
            scenes.append(line)
            continue
        sentences = re.split(r"(?<=[.!?؟])\s+", line)
        buffer = ""
        for sentence in sentences:
            if buffer and len(buffer) + len(sentence) + 1 > 360:
                scenes.append(buffer)
                buffer = sentence
            else:
                buffer = f"{buffer} {sentence}".strip()
        if buffer:
            scenes.append(buffer)
    return scenes


def strip_character(line):
    match = re.match(r"^\s*([^:：]{1,35})\s*[:：]\s*(.*)$", line)
    return match.group(2).strip() if match else line.strip()


def detect_voice(line, narrator, hero, villain, extra):
    match = re.match(r"^\s*([^:：]{1,35})\s*[:：]", line)
    character = match.group(1).lower().strip() if match else ""
    if any(word in character for word in ("lion", "sher", "villain", "bad guy", "monster")):
        return villain
    if any(word in character for word in ("hero", "boy", "prince", "protagonist")):
        return hero
    if any(word in character for word in ("rabbit", "khargosh", "friend", "girl", "princess")):
        return extra
    return narrator


def image_prompt_for_scene(text, style, visual_anchor):
    return f"{style}. {visual_anchor}. Scene: {text[:240]}. Wide cinematic composition, 16:9, no words, no subtitles, coherent character design"


# --------------------------- IMAGE / AUDIO ---------------------------
@st.cache_data(show_spinner=False, max_entries=100)
def fetch_image(prompt, seed, width, height):
    encoded = requests.utils.quote(prompt[:700], safe="")
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={width}&height={height}&seed={seed}&nologo=true"
    )
    try:
        response = requests.get(url, timeout=(10, 90))
        response.raise_for_status()
        if len(response.content) > 8_000:
            Image.open(BytesIO(response.content)).verify()
            return response.content
    except Exception:
        return None
    return None


def make_fallback_image(text, width, height, seed):
    rng = random.Random(seed)
    palettes = [
        ((12, 28, 45), (66, 105, 140)),
        ((42, 18, 28), (185, 92, 64)),
        ((16, 48, 39), (99, 150, 92)),
        ((27, 24, 54), (103, 90, 155)),
    ]
    top, bottom = rng.choice(palettes)
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(height - 1, 1)
        color = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        draw.line((0, y, width, y), fill=color)
    draw.ellipse(
        (int(width * .68), int(height * .08), int(width * .83), int(height * .35)),
        fill=(245, 211, 137)
    )
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", max(18, int(height * .027)))
    except OSError:
        font = ImageFont.load_default()
    short = text[:100]
    words, lines, current = short.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > 32:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    y = int(height * .68)
    for line in lines[:3]:
        draw.text((int(width * .06), y), line, font=font, fill="white", stroke_width=2, stroke_fill="black")
        y += int(height * .05)
    return image


def add_subtitles(image, text):
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(16, int(height * .035)))
    except OSError:
        font = ImageFont.load_default()

    words = text.split()
    lines, current = [], ""
    max_chars = 46 if width >= 1000 else 34
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars:
            if current:
                lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    lines = lines[:3]

    line_height = int(height * .052)
    box_height = line_height * len(lines) + 22
    y0 = height - box_height - int(height * .035)
    draw.rounded_rectangle(
        (int(width * .035), y0, int(width * .965), y0 + box_height),
        radius=12, fill=(0, 0, 0, 175)
    )
    y = y0 + 10
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font, stroke_width=1)
        x = (width - (box[2] - box[0])) // 2
        draw.text((x, y), line, font=font, fill="white", stroke_width=1, stroke_fill="black")
        y += line_height
    return image


# --------------------------- AUDIO (gTTS) ---------------------------
def generate_speech(text, voice, output_path, rate):
    """Generate MP3 using Google Text-to-Speech (works on Streamlit Cloud)."""
    tts = gTTS(text=text, lang="en", slow=False)
    tts.save(str(output_path))


# --------------------------- VIDEO HELPERS ---------------------------
def make_scene_clip(image_path, audio_path, output_path, width, height, zoom, fps):
    audio = AudioFileClip(str(audio_path))
    duration = max(0.5, float(audio.duration))
    image_clip = ImageClip(str(image_path))
    image_clip = set_duration(image_clip, duration)

    if zoom:
        if hasattr(image_clip, "resized"):
            image_clip = image_clip.resized(lambda t: 1.0 + 0.035 * (t / max(duration, .1)))
        else:
            image_clip = image_clip.resize(lambda t: 1.0 + 0.035 * (t / max(duration, .1)))
        image_clip = set_position(image_clip, ("center", "center"))
        try:
            from moviepy.video.fx import Crop
            image_clip = image_clip.with_effects([Crop(width=width, height=height, x_center=width/2, y_center=height/2)])
        except Exception:
            try:
                from moviepy.video.fx.all import crop
                image_clip = crop(image_clip, width=width, height=height, x_center=width/2, y_center=height/2)
            except Exception:
                pass

    image_clip = set_audio(image_clip, audio)
    write_clip(
        image_clip, output_path, fps=fps, codec="libx264", audio_codec="aac",
        logger=None, preset="ultrafast", threads=2
    )
    image_clip.close()
    audio.close()
    return duration


def save_project_state(project_dir, state):
    tmp = project_dir / "project_state.tmp"
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(project_dir / "project_state.json")


def get_clip_duration(path):
    clip = VideoFileClip(str(path))
    try:
        return float(clip.duration or 0)
    finally:
        clip.close()


# --------------------------- UI ---------------------------
st.title(APP_TITLE)
st.caption("Create narrated story videos with AI-generated scene images, voice casting, subtitles, music, and MP4 export.")

with st.sidebar:
    st.header("🎙️ Voice casting")
    voice_names = list(DEFAULT_VOICES.keys())
    narrator_name = st.selectbox("Narrator voice", voice_names, index=0)
    hero_name = st.selectbox("Hero voice", voice_names, index=3)
    villain_name = st.selectbox("Villain voice", voice_names, index=1)
    extra_name = st.selectbox("Other character voice", voice_names, index=5)
    narrator_voice = DEFAULT_VOICES[narrator_name]
    hero_voice = DEFAULT_VOICES[hero_name]
    villain_voice = DEFAULT_VOICES[villain_name]
    extra_voice = DEFAULT_VOICES[extra_name]

    st.divider()
    st.header("🎨 Movie settings")
    style = st.selectbox("Visual style", STYLES, index=0)
    visual_anchor = st.text_area(
        "Character / world consistency notes",
        value="Keep the same character appearance, colors, clothing, and environment in every scene.",
        height=85,
        help="Describe the main characters here to help keep scenes visually consistent."
    )
    resolution_label = st.selectbox("Resolution", ["1280 × 720 (HD)", "854 × 480 (faster)"], index=0)
    width, height = (1280, 720) if resolution_label.startswith("1280") else (854, 480)
    target_minutes = st.number_input("Target movie length (minutes)", min_value=1, max_value=240, value=10, step=1)
    speech_rate = st.slider("Narration speed", min_value=-30, max_value=30, value=0, step=5)
    fps = st.selectbox("Frame rate", [24, 25, 30], index=0)
    enable_subtitles = st.checkbox("Burn subtitles into scenes", value=True)
    enable_zoom = st.checkbox("Add gentle camera zoom", value=True)
    retries = st.slider("Retries per failed image/audio", 0, 3, 1)
    st.caption("Long videos need substantial CPU, RAM, storage, and generation time.")

story_tab, scenes_tab, about_tab = st.tabs(["📝 Story", "🎞️ Scene plan", "ℹ️ Notes"])

with story_tab:
    st.subheader("Paste your script")
    st.caption("Recommended format: one scene per line. Example: Narrator: The sun rose over the village.")
    story_text = st.text_area(
        "Story script",
        height=260,
        placeholder="Narrator: One morning, a young hero entered a mysterious forest.\nHero: I must find the lost treasure.\nVillain: You will never find it!",
        label_visibility="collapsed",
        key="story_text",
    )
    uploaded_script = st.file_uploader("Or upload a .txt script", type=["txt"], key="script_file")
    if uploaded_script is not None:
        try:
            story_text = uploaded_script.getvalue().decode("utf-8", errors="replace")
            st.info("Uploaded script loaded for this run.")
        except Exception:
            st.error("Could not read this text file.")

    music_file = st.file_uploader(
        "Optional background music (.mp3, .wav, .m4a)", type=["mp3", "wav", "m4a"], key="music_file"
    )
    st.caption("Only use music and images you have permission to use. Generated images depend on an external service.")

with scenes_tab:
    st.subheader("Scene preview")
    preview_scenes = parse_script(story_text) if story_text.strip() else []
    if preview_scenes:
        st.write(f"**{len(preview_scenes)} scenes detected**")
        for idx, scene in enumerate(preview_scenes[:12], start=1):
            with st.expander(f"Scene {idx}: {strip_character(scene)[:80]}"):
                st.write(scene)
        if len(preview_scenes) > 12:
            st.caption(f"Showing first 12 of {len(preview_scenes)} scenes.")
        words = sum(len(strip_character(s).split()) for s in preview_scenes)
        estimated_seconds = words / 2.4
        c1, c2, c3 = st.columns(3)
        c1.metric("Scenes", len(preview_scenes))
        c2.metric("Script words", words)
        c3.metric("Estimated narration", f"{estimated_seconds/60:.1f} min")
        if estimated_seconds < target_minutes * 60 * .75:
            st.warning("Your script may be much shorter than the target duration. Add more story text for a longer movie.")
    else:
        st.info("Paste a story in the Story tab to see its scene plan.")

with about_tab:
    st.markdown("""
    **What this app does**
    - Generates narration with Google TTS (gTTS).
    - Requests a separate image for each scene and uses a gradient fallback if image generation fails.
    - Adds optional subtitles and gentle camera movement.
    - Saves per-scene files and a checkpoint so completed scenes can be reused on a later run.
    - Combines scenes into an MP4 for preview and download.

    **Important limitations**
    - This version uses still images with camera motion, not fully generated AI video footage.
    - The free image endpoint is an external community service and can be slow, rate-limited, or unavailable.
    - gTTS depends on network access to Google Translate.
    - Streamlit Community Cloud may not have enough memory, runtime, or disk space for long movies. For long projects, run locally or on a server with FFmpeg and enough storage.
    - A target length is an estimate. The final runtime follows the generated narration unless you add more script or use a separate timing/editing stage.
    """)

project_root = Path("movie_projects")
project_root.mkdir(exist_ok=True)

if "movie_bytes" not in st.session_state:
    st.session_state.movie_bytes = None
if "last_project_dir" not in st.session_state:
    st.session_state.last_project_dir = None
if "generation_errors" not in st.session_state:
    st.session_state.generation_errors = []

col_generate, col_resume = st.columns([3, 1])
with col_generate:
    generate_clicked = st.button("🚀 Generate movie", type="primary", use_container_width=True)
with col_resume:
    resume_clicked = st.button("♻️ Resume", use_container_width=True, help="Reuse completed scene files in the most recent project.")

if generate_clicked or resume_clicked:
    if len(story_text.strip()) < 20:
        st.error("Please enter a longer story before generating.")
        st.stop()

    scenes = parse_script(story_text)
    project_id = f"project_{int(time.time())}" if generate_clicked else None
    if resume_clicked and st.session_state.last_project_dir:
        project_dir = Path(st.session_state.last_project_dir)
        if not project_dir.exists():
            st.error("The previous project folder was not found. Click Generate movie to start a new project.")
            st.stop()
    else:
        project_id = project_id or f"project_{int(time.time())}"
        project_dir = project_root / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

    scene_dir = project_dir / "scenes"
    audio_dir = project_dir / "audio"
    image_dir = project_dir / "images"
    for folder in (scene_dir, audio_dir, image_dir):
        folder.mkdir(parents=True, exist_ok=True)

    st.session_state.last_project_dir = str(project_dir)
    st.session_state.generation_errors = []
    progress = st.progress(0)
    status = st.empty()
    log_area = st.empty()
    log_lines = []
    completed_paths = []

    state_file = project_dir / "project_state.json"
    state = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    state.update({
        "scene_count": len(scenes),
        "target_minutes": target_minutes,
        "resolution": [width, height],
        "style": style,
        "updated_at": time.time(),
    })
    save_project_state(project_dir, state)

    for index, scene in enumerate(scenes):
        scene_number = index + 1
        audio_path = audio_dir / f"scene_{index:04d}.mp3"
        image_path = image_dir / f"scene_{index:04d}.jpg"
        clip_path = scene_dir / f"scene_{index:04d}.mp4"
        clean_text = strip_character(scene)
        voice = detect_voice(scene, narrator_voice, hero_voice, villain_voice, extra_voice)

        if clip_path.exists() and clip_path.stat().st_size > 20_000 and resume_clicked:
            completed_paths.append(clip_path)
            progress.progress(scene_number / len(scenes))
            status.text(f"Reusing saved scene {scene_number}/{len(scenes)}")
            continue

        status.text(f"Generating scene {scene_number}/{len(scenes)}")
        log_lines.append(f"Scene {scene_number}: {clean_text[:90]}")
        log_area.code("\n".join(log_lines[-12:]))

        # --- AUDIO (gTTS - synchronous) ---
        audio_ok = audio_path.exists() and audio_path.stat().st_size > 1000
        if not audio_ok:
            for attempt in range(retries + 1):
                try:
                    generate_speech(clean_text, voice, audio_path, speech_rate)
                    audio_ok = audio_path.exists() and audio_path.stat().st_size > 1000
                    if audio_ok:
                        break
                except Exception as exc:
                    if attempt == retries:
                        st.session_state.generation_errors.append(f"Scene {scene_number} audio: {exc}")
                    time.sleep(0.5 * (attempt + 1))
        if not audio_ok:
            st.warning(f"Skipping scene {scene_number}: narration could not be generated.")
            progress.progress(scene_number / len(scenes))
            continue

        image_ok = image_path.exists() and image_path.stat().st_size > 5000
        if not image_ok:
            prompt = image_prompt_for_scene(clean_text, style, visual_anchor)
            image_bytes = None
            for attempt in range(retries + 1):
                image_bytes = fetch_image(prompt, index + 1000 + attempt, width, height)
                if image_bytes:
                    break
                time.sleep(0.5 * (attempt + 1))
            try:
                if image_bytes:
                    img = Image.open(BytesIO(image_bytes)).convert("RGB").resize((width, height))
                else:
                    img = make_fallback_image(clean_text, width, height, index)
                if enable_subtitles:
                    img = add_subtitles(img, clean_text)
                img.save(image_path, "JPEG", quality=90, optimize=True)
                image_ok = True
            except Exception as exc:
                st.session_state.generation_errors.append(f"Scene {scene_number} image: {exc}")
                image_ok = False
        if not image_ok:
            st.warning(f"Skipping scene {scene_number}: image could not be created.")
            progress.progress(scene_number / len(scenes))
            continue

        try:
            make_scene_clip(image_path, audio_path, clip_path, width, height, enable_zoom, fps)
            completed_paths.append(clip_path)
            state.setdefault("completed_scenes", [])
            if scene_number not in state["completed_scenes"]:
                state["completed_scenes"].append(scene_number)
            save_project_state(project_dir, state)
        except Exception as exc:
            st.session_state.generation_errors.append(f"Scene {scene_number} video: {exc}")
            st.warning(f"Could not render scene {scene_number}: {exc}")

        progress.progress(scene_number / len(scenes))

    if not completed_paths:
        st.error("No scenes were completed. Check the errors below and try again.")
        if st.session_state.generation_errors:
            st.code("\n".join(st.session_state.generation_errors))
        st.stop()

    status.text("Joining scenes and preparing final audio...")
    final_clips = []
    final = None
    music_clip = None
    mixed_audio = None
    try:
        final_clips = [VideoFileClip(str(path)) for path in completed_paths]
        final = concatenate_videoclips(final_clips, method="compose")

        if music_file is not None:
            music_path = project_dir / f"background_music{Path(music_file.name).suffix}"
            music_path.write_bytes(music_file.getvalue())
            try:
                music_clip = AudioFileClip(str(music_path))
                if music_clip.duration < final.duration:
                    repeats = math.ceil(final.duration / music_clip.duration)
                    if hasattr(music_clip, "loop"):
                        music_clip = music_clip.loop(n=repeats)
                    else:
                        from moviepy.audio.fx.all import audio_loop
                        music_clip = audio_loop(music_clip, n=repeats)
                music_clip = subclip(music_clip, 0, final.duration)
                music_clip = music_clip.with_volume_scaled(0.12) if hasattr(music_clip, "with_volume_scaled") else music_clip.volumex(0.12)
                narration_audio = final.audio
                mixed_audio = CompositeAudioClip([narration_audio, music_clip])
                final = set_audio(final, mixed_audio)
            except Exception as exc:
                st.warning(f"Background music was not added: {exc}")

        output_path = project_dir / "final_movie.mp4"
        write_clip(
            final, output_path, fps=fps, codec="libx264", audio_codec="aac",
            logger=None, preset="ultrafast", threads=2
        )
        st.session_state.movie_bytes = output_path.read_bytes()
        state["final_movie"] = str(output_path)
        state["final_duration_seconds"] = float(final.duration)
        state["completed_scene_files"] = [str(p) for p in completed_paths]
        save_project_state(project_dir, state)
        status.success(f"Movie complete — {len(completed_paths)} scenes, {final.duration / 60:.1f} minutes.")
        st.balloons()
    except Exception as exc:
        st.error(f"Final assembly failed: {exc}")
        st.info("Try a lower resolution, fewer scenes, or run locally with FFmpeg installed.")
    finally:
        if mixed_audio is not None:
            try: mixed_audio.close()
            except Exception: pass
        if music_clip is not None:
            try: music_clip.close()
            except Exception: pass
        if final is not None:
            try: final.close()
            except Exception: pass
        for clip in final_clips:
            try: clip.close()
            except Exception: pass

    if st.session_state.generation_errors:
        with st.expander("Generation warnings / errors"):
            st.code("\n".join(st.session_state.generation_errors))

if st.session_state.movie_bytes:
    st.divider()
    st.subheader("🎉 Your movie is ready")
    st.video(st.session_state.movie_bytes)
    st.download_button(
        "⬇️ Download MP4",
        data=st.session_state.movie_bytes,
        file_name="AI_Movie_Studio.mp4",
        mime="video/mp4",
        type="primary",
        use_container_width=True,
    )
elif st.session_state.last_project_dir:
    st.caption(f"Project checkpoint folder: {st.session_state.last_project_dir}")
