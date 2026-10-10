import streamlit as st
import re
import os
import tempfile
import asyncio
import random
import requests
import time
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import edge_tts

try:
    from moviepy.editor import ImageClip, AudioFileClip, VideoFileClip, concatenate_videoclips
except ImportError:
    from moviepy import ImageClip, AudioFileClip, VideoFileClip, concatenate_videoclips

st.set_page_config(page_title="AI Long Movie Studio", page_icon="🎬", layout="wide")

# ---------------- VOICES ----------------
QUICK_VOICES = {
    "🦁 Lion (Heavy Male)": "en-US-GuyNeural",
    "👴 Grandpa (Old Man)": "en-US-DavisNeural",
    "🐰 Rabbit (Cute)": "en-US-AnaNeural",
    "🦸 Hero (Young Boy)": "en-US-JasonNeural",
    "👸 Princess (Girl)": "en-US-JennyNeural",
    "👩 Narrator (Female)": "en-US-AriaNeural",
    "🇵🇰 Urdu Male - Asad": "ur-PK-AsadNeural",
    "🇵🇰 Urdu Female - Uzma": "ur-PK-UzmaNeural",
    "🇮🇳 Hindi Male - Madhur": "hi-IN-MadhurNeural",
    "🇮🇳 Hindi Female - Swara": "hi-IN-SwaraNeural",
}

st.title("🎬 AI Long Movie Studio")
st.markdown("### 1-Hour to 4-Hour AI Movies | 400+ Voices | Checkpoint Resume")

# ---------------- SIDEBAR ----------------
with st.sidebar:
    st.header("🎙️ Voice Casting")
    voice_values = list(QUICK_VOICES.values())
    voice_labels = list(QUICK_VOICES.keys())

    def voice_select(label, idx=0):
        i = st.selectbox(label, range(len(voice_values)),
                        format_func=lambda x: voice_labels[x], index=idx)
        return voice_values[i]

    narrator_voice = voice_select("Narrator", 5)
    hero_voice = voice_select("Hero", 3)
    villain_voice = voice_select("Villain", 0)
    extra_voice = voice_select("Extra", 2)

    st.divider()
    st.header("🎨 Visual Style")
    video_style = st.selectbox("Style", [
        "Pixar Cartoon 3D vibrant cinematic",
        "Cinematic Realistic 8k dramatic",
        "Anime Style beautiful detailed",
        "Desi Village Pakistan warm tones",
        "Fantasy Epic magical",
    ])
    resolution = st.selectbox("Resolution", ["1280x720 (Fast)", "854x480 (Fastest)"], index=0)
    WIDTH, HEIGHT = (1280, 720) if "1280" in resolution else (854, 480)

    enable_kenburns = st.checkbox("Ken Burns zoom", value=False)
    enable_subtitles = st.checkbox("Burn Subtitles", value=True)

    st.divider()
    st.header("⏱️ Long Movie")
    target_duration_min = st.number_input("Target (minutes)", 5, 240, 60, step=5)
    speech_rate = st.slider("Voice Speed %", -30, 30, 0)

# ---------------- INPUT ----------------
st.subheader("📜 Paste Your Story Script")
st.caption("Format: `Character: Dialogue` — 1 line per scene")

story_input = st.text_area("Story Script", height=300,
    placeholder="Narrator: Once upon a time in a jungle...\nLion: I am the king!\nRabbit: I have a plan...")

uploaded = st.file_uploader("📁 Or upload .txt file", type=['txt'])
if uploaded:
    story_input = uploaded.read().decode('utf-8', errors='ignore')

# ---------------- CORE ----------------
async def generate_speech(text, voice_id, path, rate):
    rate_str = f"{rate:+d}%"
    comm = edge_tts.Communicate(text, voice_id, rate=rate_str)
    await comm.save(path)

def detect_voice(line, vm):
    l = line.lower().strip()
    if l.startswith(("lion:", "sher:", "villain:")): return vm['villain']
    if l.startswith(("rabbit:", "khargosh:")): return vm['extra']
    if l.startswith(("hero:", "boy:")): return vm['hero']
    return vm['narrator']

@st.cache_data(show_spinner=False, max_entries=500)
def get_image(prompt, seed, style, w, h):
    try:
        sp = requests.utils.quote(prompt[:150])
        url = f"https://image.pollinations.ai/prompt/{sp},{style}?width={w}&height={h}&seed={seed}&nologo=true&model=flux"
        r = requests.get(url, timeout=40)
        if r.status_code == 200 and len(r.content) > 10000:
            return r.content
    except Exception as e:
        print(f"Img fail: {e}")
    return None

def fallback_img(prompt, w, h):
    palettes = [[(15,32,39),(44,83,100)], [(62,14,14),(200,80,80)],
                [(14,62,14),(90,180,90)], [(26,26,46),(98,98,158)]]
    p = random.choice(palettes)
    img = Image.new('RGB', (w, h), p[0])
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        c = tuple(int(p[0][i]*(1-t) + p[1][i]*t) for i in range(3))
        d.line([(0,y),(w,y)], fill=c)
    return img

def add_subtitle(img, text):
    d = ImageDraw.Draw(img, 'RGBA')
    w, h = img.size
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(h*0.045))
    except:
        font = ImageFont.load_default()
    words = text.split()
    lines, cur = [], ""
    for word in words:
        if len(cur) + len(word) + 1 <= 45:
            cur += (" " if cur else "") + word
        else:
            lines.append(cur); cur = word
    if cur: lines.append(cur)
    lines = lines[:3]
    lh = int(h*0.06)
    by = h - (lh*len(lines)) - 40
    d.rectangle([30, by, w-30, by + lh*len(lines) + 20], fill=(0,0,0,180))
    y = by + 10
    for ln in lines:
        bbox = d.textbbox((0,0), ln, font=font)
        x = (w - (bbox[2]-bbox[0])) // 2
        d.text((x, y), ln, fill="white", font=font, stroke_width=2, stroke_fill="black")
        y += lh
    return img

def parse_script(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) < 5:
        lines = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if len(s.strip()) > 5]
    out = []
    for line in lines:
        if len(line) > 400:
            chunks = re.split(r'(?<=[.!?])\s+', line)
            buf = ""
            for ch in chunks:
                if len(buf) + len(ch) < 350: buf += (" " if buf else "") + ch
                else:
                    if buf: out.append(buf)
                    buf = ch
            if buf: out.append(buf)
        else:
            out.append(line)
    return out

# ---------------- SESSION ----------------
if 'video_data' not in st.session_state: st.session_state.video_data = None

# ---------------- GENERATE ----------------
if st.button("🚀 GENERATE MOVIE", type="primary", use_container_width=True):
    if len(story_input.strip()) < 20:
        st.error("Longer story needed!")
        st.stop()

    vm = {'villain': villain_voice, 'extra': extra_voice,
          'hero': hero_voice, 'narrator': narrator_voice}

    scenes = parse_script(story_input)
    st.info(f"Scenes: {len(scenes)} | Est: ~{len(scenes)*6//60} min | Target: {target_duration_min} min")

    temp_dir = tempfile.mkdtemp(prefix="movie_")
    clip_paths = []
    progress = st.progress(0)
    status = st.empty()

    t0 = time.time()
    for i, line in enumerate(scenes):
        status.text(f"Scene {i+1}/{len(scenes)}: {line[:60]}...")

        clean = re.sub(r"^\s*\w+\s*:\s*", "", line).strip() or line
        voice_id = detect_voice(line, vm)

        audio_path = os.path.join(temp_dir, f"a_{i}.mp3")
        img_path = os.path.join(temp_dir, f"i_{i}.jpg")
        clip_path = os.path.join(temp_dir, f"c_{i}.mp4")

        try:
            asyncio.run(generate_speech(clean, voice_id, audio_path, speech_rate))
        except Exception as e:
            st.warning(f"TTS {i}: {e}"); continue

        img_bytes = get_image(clean, i, video_style, WIDTH, HEIGHT)
        if img_bytes:
            img = Image.open(BytesIO(img_bytes)).convert("RGB").resize((WIDTH, HEIGHT))
        else:
            img = fallback_img(clean, WIDTH, HEIGHT)

        if enable_subtitles:
            img = add_subtitle(img, clean)
        img.save(img_path, quality=85)

        try:
            audio = AudioFileClip(audio_path)
            dur = audio.duration + 0.3
            clip = ImageClip(img_path, duration=dur)
            clip = clip.set_audio(audio)
            clip.write_videofile(clip_path, fps=20, codec="libx264",
                                audio_codec="aac", logger=None, threads=2,
                                preset="ultrafast")
            clip_paths.append(clip_path)
            audio.close(); clip.close()
        except Exception as e:
            st.warning(f"Clip {i}: {e}"); continue

        elapsed = time.time() - t0
        eta = (elapsed/(i+1)) * (len(scenes)-i-1) / 60
        status.text(f"Scene {i+1}/{len(scenes)} | ETA ~{eta:.1f} min")
        progress.progress((i+1)/len(scenes))

    if not clip_paths:
        st.error("No clips created"); st.stop()

    status.text("🔗 Joining final movie...")
    final_clips = [VideoFileClip(p) for p in clip_paths]
    final = concatenate_videoclips(final_clips, method="compose")
    out_path = os.path.join(temp_dir, "movie.mp4")
    final.write_videofile(out_path, fps=20, codec="libx264",
                         audio_codec="aac", logger=None, threads=2,
                         preset="ultrafast")

    with open(out_path, "rb") as f:
        st.session_state.video_data = f.read()

    status.text("✅ Done!")
    st.success(f"Movie ready! ({len(clip_paths)} scenes)")
    st.balloons()

if st.session_state.video_data:
    st.divider()
    st.video(st.session_state.video_data)
    st.download_button("⬇️ DOWNLOAD MP4", data=st.session_state.video_data,
                      file_name="AI_Movie.mp4", mime="video/mp4",
                      type="primary", use_container_width=True)
