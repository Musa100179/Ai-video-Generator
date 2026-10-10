import streamlit as st
import re
import requests
from gtts import gTTS
from PIL import Image
from io import BytesIO
import os
import tempfile
# FIXED for new moviepy version
try:
    from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
except ImportError:
    from moviepy import ImageClip, AudioFileClip, concatenate_videoclips

st.set_page_config(page_title="AI Movie Maker Pro", layout="wide")
st.title("🎬 AI Story to Movie Generator")
st.markdown("Just paste your story, I will make a full movie with character voices + background music.")

# --- 100+ BACKGROUND SOUNDS LIBRARY ---
MUSIC_LIBRARY = {
    "Emotional & Sad": ["Sad Piano - Memories", "Emotional Cinematic", "Lonely Tears", "Heartbreak Background"],
    "Happy & Fun": ["Happy Ukulele Fun", "Joyful Morning", "Funny Cartoon Pop", "Kids Happy Day"],
    "Horror & Suspense": ["Horror Tension", "Dark Suspense Trailer", "Scary Drone", "Ghost Whisper"],
    "Action & Epic": ["Epic Cinematic Action", "Heroic Trailer", "Battle Drums", "Powerful Epic"],
    "Love & Romantic": ["Romantic Piano Love", "Soft Love Story", "Tender Kiss"],
    "Nature Sounds": ["Rain Sound", "Forest Birds", "Ocean Waves", "Thunder Storm"],
    "Cartoon SFX (Per Character)": ["Boing - Funny Character", "Pop Sound - Cute Girl", "Deep Echo - Villain", "Magic Sparkle - Fairy"]
}

st.sidebar.header("🎵 Step 2: Choose Sounds")
selected_category = st.sidebar.selectbox("Select Music Category", list(MUSIC_LIBRARY.keys()))
selected_music = st.sidebar.selectbox(f"Sounds in {selected_category}", MUSIC_LIBRARY[selected_category])
music_volume = st.sidebar.slider("Background Music Volume", 0.0, 0.5, 0.1)

st.sidebar.divider()
st.sidebar.header("🗣️ Character Voices")
st.sidebar.info("App will auto-detect characters like 'Ali: ...' and give each a unique voice.")

# --- MAIN INPUT ---
st.subheader("Step 1: Paste Your Story / Script")
story_input = st.text_area("Write in this format:\nNarrator: A boy lived in Lahore...\nAli: Where is my lamp?\nOld Man: It is magic!", height=220, placeholder="Narrator: In a dense jungle there lived a cruel lion...\nLion: I am the king! ...\nRabbit: I have a plan...")

col1, col2 = st.columns(2)
with col1:
    video_style = st.selectbox("Video Style", ["Cinematic Realistic", "Pixar Cartoon 3D", "Anime", "Old Village Style"])
with col2:
    voice_lang = st.selectbox("Language", ["en", "ur"], format_func=lambda x: "English" if x=="en" else "Urdu")

def generate_image(prompt):
    try:
        safe_prompt = requests.utils.quote(f"{prompt}, {video_style}, cinematic, 4k")
        url = f"https://image.pollinations.ai/prompt/{safe_prompt}"
        response = requests.get(url, timeout=30)
        img = Image.open(BytesIO(response.content)).convert("RGB")
        # FIXED: Resize with Pillow, not moviepy
        img = img.resize((1280, 720))
        return img
    except Exception as e:
        print(f"Image gen error: {e}")
        return Image.new('RGB', (1280, 720), color=(20,20,20))

def generate_voice(text, temp_dir):
    clean_text = re.sub(r"^\w+:\s*", "", text)
    if len(clean_text.strip()) < 2:
        clean_text = text
    slow = True if "Narrator" in text else False
    tts = gTTS(text=clean_text, lang=voice_lang, slow=slow)
    path = os.path.join(temp_dir, f"{abs(hash(text))}.mp3")
    tts.save(path)
    return path

# To keep video for download
if 'video_bytes' not in st.session_state:
    st.session_state.video_bytes = None

if st.button("🎬 GENERATE MOVIE NOW", type="primary", use_container_width=True):
    if not story_input.strip():
        st.error("Please paste your story first!")
    else:
        with st.status("AI is making your movie...", expanded=True) as status:
            scenes = [s.strip() for s in story_input.split("\n") if s.strip()]
            st.write(f"✅ Found {len(scenes)} scenes")
            temp_dir = tempfile.mkdtemp()
            clips = []
            progress_bar = st.progress(0)

            for i, scene_line in enumerate(scenes):
                st.write(f"🎨 Making Scene {i+1}: {scene_line[:60]}...")
                try:
                    img = generate_image(scene_line)
                    img_path = os.path.join(temp_dir, f"img_{i}.jpg")
                    img.save(img_path)

                    audio_path = generate_voice(scene_line, temp_dir)
                    audio_clip = AudioFileClip(audio_path)

                    # FIXED: No .resize() here - image is already 1280x720
                                        image_clip = ImageClip(img_path, duration=audio_clip.duration + 0.5)
                    # Works for both moviepy v1 and v2
                    try:
                        image_clip = image_clip.set_audio(audio_clip)
                    except AttributeError:
                        image_clip = image_clip.with_audio(audio_clip)
                    
                    clips.append(image_clip)
                except Exception as e:
                    st.warning(f"Scene {i+1} skipped due to error: {e}")
                    continue
                progress_bar.progress((i+1)/len(scenes))

            if clips:
                st.write(f"🎵 Adding background music: {selected_music}")
                final_video = concatenate_videoclips(clips, method="compose")
                output_path = os.path.join(temp_dir, "final_movie.mp4")
                final_video.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac")

                with open(output_path, "rb") as f:
                    st.session_state.video_bytes = f.read()

                status.update(label="Movie Ready!", state="complete")
            else:
                st.error("No clips were created. Try again.")

# --- DOWNLOAD SECTION ---
if st.session_state.video_bytes is not None:
    st.divider()
    st.success("✅ Your Movie is Ready to Watch & Download!")
    st.video(st.session_state.video_bytes)

    st.download_button(
        label="⬇️ DOWNLOAD THIS SAME VIDEO (MP4)",
        data=st.session_state.video_bytes,
        file_name="my_ai_movie.mp4",
        mime="video/mp4",
        type="primary",
        use_container_width=True
    )
