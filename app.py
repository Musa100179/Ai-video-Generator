"""
AI Movie Studio — Single-file version for Streamlit Cloud.
Fixed for Pillow 10+ and gTTS (no Edge TTS blocking).
"""

import json
import math
import random
import re
import time
from io import BytesIO
from pathlib import Path

import requests
import streamlit as st
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont

# ---------- Pillow 10+ compatibility fix ----------
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS
if not hasattr(Image, "LANCZOS"):
    Image.LANCZOS = Image.Resampling.LANCZOS

# ---------- MoviePy import (v1 and v2) ----------
try:
    from moviepy import (
        AudioFileClip, CompositeAudioClip, ImageClip, VideoFileClip,
        concatenate_videoclips,
    )
except ImportError:
    from moviepy.editor import (
        AudioFileClip, CompositeAudioClip, ImageClip, VideoFileClip,
        concatenate_videoclips,
    )


# ============================================================
#  CONFIG
# ============================================================
st.set_page_config(page_title="AI Movie Studio", page_icon="🎬", layout="wide")

PROJECT_ROOT = Path("movie_projects")

LANGUAGES = {
    "English (US)": "en",
    "English (UK)": "en",
    "Urdu": "ur",
    "Hindi": "hi",
    "Arabic": "ar",
    "French": "fr",
    "Spanish": "es",
}

VISUAL_STYLES = [
    "Cinematic realistic, dramatic lighting, film still",
    "3D animated family adventure, vibrant cinematic colors",
    "Detailed anime film, expressive characters",
    "Pakistani village, warm natural colors, realistic",
    "Epic fantasy, magical atmosphere, cinematic lighting",
    "Historical adventure, natural textures, cinematic",
]

RESOLUTIONS = {
    "1280 × 720 (HD)": (1280, 720),
    "854 × 480 (SD, faster)": (854, 480),
}

FPS_OPTIONS = [24, 25, 30]


# ============================================================
#  HELPERS
# ============================================================
def file_ok(path, min_bytes=1000):
    return path.exists() and path.stat().st_size >= min_bytes


def set_duration(clip, d):
    return clip.with_duration(d) if hasattr(clip, "with_duration") else clip.set_duration(d)


def set_audio(clip, a):
    return clip.with_audio(a) if hasattr(clip, "with_audio") else clip.set_audio(a)


def set_position(clip, p):
    return clip.with_position(p) if hasattr(clip, "with_position") else clip.set_position(p)


def subclip(clip, s, e):
    return clip.subclipped(s, e) if hasattr(clip, "subclipped") else clip.subclip(s, e)


def write_clip(clip, path, **kw):
    return clip.write_videofile(str(path), **kw)


# ============================================================
#  SCRIPT PARSING
# ============================================================
def parse_script(text):
    lines = [l.strip() for l in text.replace("\r", "").split("\n") if l.strip()]
    if len(lines) <= 2:
        lines = [s.strip() for s in re.split(r"(?<=[.!?؟])\s+", text) if s.strip()]

    scenes = []
    for line in lines:
        if len(line) <= 420:
            scenes.append(line)
            continue
        for sent in re.split(r"(?<=[.!?؟])\s+", line):
            scenes.append(sent)
    return scenes


def strip_character(line):
    m = re.match(r"^\s*([^:：]{1,35})\s*[:：]\s*(.*)$", line)
    return m.group(2).strip() if m else line.strip()


def build_prompt(text, style, anchor):
    return f"{style}. {anchor}. Scene: {text[:240]}. Wide cinematic, 16:9, no words"


# ============================================================
#  TTS (gTTS — works on Streamlit Cloud)
# ============================================================
def generate_speech(text, language, output_path, max_retries=3):
    text = text.strip()
    if not text:
        return False
    for attempt in range(max_retries):
        try:
            tts = gTTS(text=text, lang=language, slow=False)
            tts.save(str(output_path))
            if file_ok(output_path, 500):
                return True
        except Exception as e:
            print(f"TTS attempt {attempt+1} failed: {e}")
            time.sleep(1.0 * (attempt + 1))
    return False


# ============================================================
#  IMAGE
# ============================================================
def fetch_pollinations(prompt, seed, w, h):
    encoded = requests.utils.quote(prompt[:700], safe="")
    url = f"https://image.pollinations.ai/prompt/{encoded}?width={w}&height={h}&seed={seed}&nologo=true"
    try:
        r = requests.get(url, timeout=(10, 90))
        r.raise_for_status()
        if len(r.content) > 8000:
            Image.open(BytesIO(r.content)).verify()
            return r.content
    except Exception as e:
        print(f"Pollinations failed: {e}")
    return None


def make_fallback(text, w, h, seed):
    rng = random.Random(seed)
    palettes = [
        ((12, 28, 45), (66, 105, 140)),
        ((42, 18, 28), (185, 92, 64)),
        ((16, 48, 39), (99, 150, 92)),
        ((27, 24, 54), (103, 90, 155)),
    ]
    top, bottom = rng.choice(palettes)
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        c = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        draw.line((0, y, w, y), fill=c)
    draw.ellipse((int(w * .68), int(h * .08), int(w * .83), int(h * .35)), fill=(245, 211, 137))
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", max(18, int(h * .027)))
    except OSError:
        font = ImageFont.load_default()
    words = text[:100].split()
    lines, cur = [], ""
    for wd in words:
        c = f"{cur} {wd}".strip()
        if len(c) > 32:
            lines.append(cur)
            cur = wd
        else:
            cur = c
    if cur:
        lines.append(cur)
    y = int(h * .68)
    for line in lines[:3]:
        draw.text((int(w * .06), y), line, font=font, fill="white", stroke_width=2, stroke_fill="black")
        y += int(h * .05)
    return img


def add_subtitles(img, text):
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(16, int(h * .035)))
    except OSError:
        font = ImageFont.load_default()
    words, lines, cur = text.split(), [], ""
    max_chars = 46 if w >= 1000 else 34
    for wd in words:
        c = f"{cur} {wd}".strip()
        if len(c) > max_chars:
            if cur:
                lines.append(cur)
            cur = wd
        else:
            cur = c
    if cur:
        lines.append(cur)
    lines = lines[:3]
    lh = int(h * .052)
    bh = lh * len(lines) + 22
    y0 = h - bh - int(h * .035)
    draw.rounded_rectangle((int(w * .035), y0, int(w * .965), y0 + bh), radius=12, fill=(0, 0, 0, 175))
    y = y0 + 10
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font, stroke_width=1)
        x = (w - (bb[2] - bb[0])) // 2
        draw.text((x, y), line, font=font, fill="white", stroke_width=1, stroke_fill="black")
        y += lh
    return img


def get_scene_image(prompt, clean, w, h, seed, retries):
    for attempt in range(retries + 1):
        b = fetch_pollinations(prompt, seed + attempt, w, h)
        if b:
            try:
                return Image.open(BytesIO(b)).convert("RGB").resize((w, h), Image.LANCZOS)
            except Exception:
                pass
    return make_fallback(clean, w, h, seed)


# ============================================================
#  VIDEO RENDERING
# ============================================================
def render_scene(image_path, audio_path, output_path, w, h, fps, zoom):
    audio = AudioFileClip(str(audio_path))
    duration = max(0.5, float(audio.duration))
    clip = ImageClip(str(image_path))
    clip = set_duration(clip, duration)
    if zoom:
        try:
            clip = clip.resized(lambda t: 1.0 + 0.035 * (t / max(duration, .1)))
        except AttributeError:
            clip = clip.resize(lambda t: 1.0 + 0.035 * (t / max(duration, .1)))
        clip = set_position(clip, ("center", "center"))
    clip = set_audio(clip, audio)
    write_clip(
        clip, output_path,
        fps=fps, codec="libx264", audio_codec="aac",
        logger=None, preset="ultrafast", threads=2,
    )
    clip.close()
    audio.close()
    return duration


def combine_all(scene_paths, output_path, fps, music_path=None):
    clips = []
    final = None
    music = None
    mixed = None
    try:
        clips = [VideoFileClip(str(p)) for p in scene_paths]
        final = concatenate_videoclips(clips, method="compose")
        if music_path and music_path.exists():
            try:
                music = AudioFileClip(str(music_path))
                if music.duration < final.duration:
                    reps = math.ceil(final.duration / music.duration)
                    if hasattr(music, "loop"):
                        music = music.loop(n=reps)
                    else:
                        from moviepy.audio.fx.all import audio_loop
                        music = audio_loop(music, n=reps)
                music = subclip(music, 0, final.duration)
                if hasattr(music, "with_volume_scaled"):
                    music = music.with_volume_scaled(0.12)
                else:
                    music = music.volumex(0.12)
                mixed = CompositeAudioClip([final.audio, music])
                final = set_audio(final, mixed)
            except Exception as e:
                print(f"Music skipped: {e}")
        write_clip(
            final, output_path,
            fps=fps, codec="libx264", audio_codec="aac",
            logger=None, preset="ultrafast", threads=2,
        )
        return float(final.duration)
    finally:
        for o in (mixed, music, final):
            if o is not None:
                try: o.close()
                except: pass
        for c in clips:
            try: c.close()
            except: pass


# ============================================================
#  UI
# ============================================================
st.title("🎬 AI Movie Studio")
st.caption("Create narrated story videos with AI images, TTS, subtitles, and MP4 export.")

with st.sidebar:
    st.header("🎙️ Language")
    lang_label = st.selectbox("Narration language", list(LANGUAGES.keys()), index=0)
    language = LANGUAGES[lang_label]

    st.divider()
    st.header("🎨 Movie settings")
    style = st.selectbox("Visual style", VISUAL_STYLES, index=0)
    anchor = st.text_area(
        "Character / world consistency notes",
        value="Keep the same character appearance, colors, clothing, and environment in every scene.",
        height=85,
    )
    res_label = st.selectbox("Resolution", list(RESOLUTIONS.keys()), index=0)
    width, height = RESOLUTIONS[res_label]

    target = st.number_input("Target length (minutes)", 1, 240, 10, 1)
    fps = st.selectbox("Frame rate", FPS_OPTIONS, index=0)
    subtitles = st.checkbox("Burn subtitles", value=True)
    zoom = st.checkbox("Gentle camera zoom", value=True)
    retries = st.slider("Retries per failed item", 0, 3, 2)
    st.caption("⚠️ Long videos need significant CPU, RAM, and time.")

tab_story, tab_scenes, tab_about = st.tabs(["📝 Story", "🎞️ Scene plan", "ℹ️ Notes"])

with tab_story:
    st.subheader("Paste your script")
    st.caption("One scene per line. Example — `Narrator: The sun rose over the village.`")
    story_text = st.text_area(
        "Story script", height=260, label_visibility="collapsed",
        placeholder="Narrator: One morning, a young hero entered a mysterious forest.\nHero: I must find the lost treasure.\nVillain: You will never find it!",
        key="story_text",
    )
    uploaded = st.file_uploader("Or upload a .txt file", type=["txt"])
    if uploaded:
        try:
            story_text = uploaded.getvalue().decode("utf-8", errors="replace")
            st.info("Uploaded script loaded.")
        except Exception as e:
            st.error(f"Could not read file: {e}")
    music_file = st.file_uploader("Optional background music", type=["mp3", "wav", "m4a"])

with tab_scenes:
    st.subheader("Scene preview")
    scenes = parse_script(story_text) if story_text.strip() else []
    if scenes:
        st.write(f"**{len(scenes)} scenes detected**")
        for i, s in enumerate(scenes[:12], 1):
            with st.expander(f"Scene {i}: {strip_character(s)[:80]}"):
                st.write(s)
        words = sum(len(strip_character(s).split()) for s in scenes)
        c1, c2, c3 = st.columns(3)
        c1.metric("Scenes", len(scenes))
        c2.metric("Words", words)
        c3.metric("Est. runtime", f"{(words/2.4)/60:.1f} min")
    else:
        st.info("Paste a story in the Story tab first.")

with tab_about:
    st.markdown("""
    **How it works**
    1. Script is split into scenes.
    2. Each scene → narration (Google TTS) + image (Pollinations / gradient fallback).
    3. Scenes rendered to MP4 and concatenated.

    **Limitations**
    - gTTS needs internet access to Google.
    - Pollinations.ai is a free service — may be slow.
    - Streamlit Cloud has ~1 GB RAM; very long videos may fail.
    """)

# ---------- Session state ----------
st.session_state.setdefault("movie_bytes", None)
st.session_state.setdefault("last_dir", None)
st.session_state.setdefault("errors", [])

# ---------- Buttons ----------
c1, c2 = st.columns([3, 1])
generate = c1.button("🚀 Generate movie", type="primary", use_container_width=True)
resume = c2.button("♻️ Resume", use_container_width=True)

if generate or resume:
    if len(story_text.strip()) < 20:
        st.error("Please enter a longer story.")
        st.stop()

    scenes = parse_script(story_text)

    if resume and st.session_state.last_dir:
        project_dir = Path(st.session_state.last_dir)
        if not project_dir.exists():
            st.error("Previous project not found. Click Generate to start fresh.")
            st.stop()
    else:
        project_dir = PROJECT_ROOT / f"project_{int(time.time())}"
        project_dir.mkdir(parents=True, exist_ok=True)

    audio_dir = project_dir / "audio"; audio_dir.mkdir(exist_ok=True)
    image_dir = project_dir / "images"; image_dir.mkdir(exist_ok=True)
    scene_dir = project_dir / "scenes"; scene_dir.mkdir(exist_ok=True)

    st.session_state.last_dir = str(project_dir)
    st.session_state.errors = []

    progress = st.progress(0)
    status = st.empty()
    log_area = st.empty()
    log_lines = []
    completed = []

    for i, scene in enumerate(scenes):
        n = i + 1
        clean = strip_character(scene)
        audio_path = audio_dir / f"scene_{i:04d}.mp3"
        image_path = image_dir / f"scene_{i:04d}.jpg"
        clip_path = scene_dir / f"scene_{i:04d}.mp4"

        if resume and file_ok(clip_path, 20000):
            completed.append(clip_path)
            progress.progress(n / len(scenes))
            status.text(f"Reused scene {n}/{len(scenes)}")
            continue

        status.text(f"Scene {n}/{len(scenes)}")
        log_lines.append(f"Scene {n}: {clean[:80]}")
        log_area.code("\n".join(log_lines[-10:]))

        # AUDIO
        if not file_ok(audio_path, 1000):
            ok = generate_speech(clean, language, audio_path, retries + 1)
            if not ok:
                st.session_state.errors.append(f"Scene {n}: TTS failed")
                st.warning(f"Skipping scene {n}: audio failed")
                progress.progress(n / len(scenes))
                continue

        # IMAGE
        if not file_ok(image_path, 5000):
            prompt = build_prompt(clean, style, anchor)
            try:
                img = get_scene_image(prompt, clean, width, height, i, retries)
                if subtitles:
                    img = add_subtitles(img, clean)
                img.save(image_path, "JPEG", quality=90, optimize=True)
            except Exception as e:
                st.session_state.errors.append(f"Scene {n}: image failed — {e}")
                st.warning(f"Skipping scene {n}: image failed")
                progress.progress(n / len(scenes))
                continue

        # VIDEO
        try:
            render_scene(image_path, audio_path, clip_path, width, height, fps, zoom)
            completed.append(clip_path)
        except Exception as e:
            st.session_state.errors.append(f"Scene {n}: video failed — {e}")
            st.warning(f"Could not render scene {n}: {e}")

        progress.progress(n / len(scenes))

    if not completed:
        st.error("No scenes completed. See errors below.")
        if st.session_state.errors:
            st.code("\n".join(st.session_state.errors))
        st.stop()

    # FINAL
    status.text("Joining scenes...")
    music_path = None
    if music_file is not None:
        music_path = project_dir / f"music{Path(music_file.name).suffix}"
        music_path.write_bytes(music_file.getvalue())

    output = project_dir / "final_movie.mp4"
    try:
        duration = combine_all(completed, output, fps, music_path)
        st.session_state.movie_bytes = output.read_bytes()
        status.success(f"Movie complete — {len(completed)} scenes, {(duration or 0)/60:.1f} min.")
        st.balloons()
    except Exception as e:
        st.error(f"Final assembly failed: {e}")

    if st.session_state.errors:
        with st.expander("⚠️ Warnings / errors"):
            st.code("\n".join(st.session_state.errors))

# ---------- Playback ----------
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
elif st.session_state.last_dir:
    st.caption(f"📁 Project folder: {st.session_state.last_dir}")
