import asyncio
import re
import shutil
import subprocess
import time
from pathlib import Path

import streamlit as st
import edge_tts
from huggingface_hub import InferenceClient

# ---------------- APP SETTINGS ----------------

st.set_page_config(
    page_title="AI Story Video Studio",
    page_icon="🎬",
    layout="wide"
)

ROOT = Path("my_video_projects")
ROOT.mkdir(exist_ok=True)

VOICES = {
    "English US Female - Aria": "en-US-AriaNeural",
    "English US Female - Jenny": "en-US-JennyNeural",
    "English US Female - Michelle": "en-US-MichelleNeural",
    "English US Female - Ana": "en-US-AnaNeural",
    "English US Male - Guy": "en-US-GuyNeural",
    "English US Male - Davis": "en-US-DavisNeural",
    "English US Male - Tony": "en-US-TonyNeural",
    "English US Male - Jason": "en-US-JasonNeural",
    "English UK Female - Sonia": "en-GB-SoniaNeural",
    "English UK Female - Libby": "en-GB-LibbyNeural",
    "English UK Male - Ryan": "en-GB-RyanNeural",
    "English UK Male - Thomas": "en-GB-ThomasNeural",
    "Australian Female - Natasha": "en-AU-NatashaNeural",
    "Australian Male - William": "en-AU-WilliamNeural",
    "Indian English Female - Neerja": "en-IN-NeerjaNeural",
    "Indian English Male - Prabhat": "en-IN-PrabhatNeural",
    "Urdu Female - Uzma": "ur-PK-UzmaNeural",
    "Urdu Male - Asad": "ur-PK-AsadNeural",
    "Hindi Female - Swara": "hi-IN-SwaraNeural",
    "Hindi Male - Madhur": "hi-IN-MadhurNeural",
}


def safe_name(text):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)[:60] or "story"


def run_command(args):
    result = subprocess.run(
        args, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            (result.stderr or result.stdout)[-2500:]
        )


async def make_narration(text, voice, output_path, rate):
    speaker = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate
    )
    await speaker.save(str(output_path))


def make_image(client, prompt, model, output_path):
    image = client.text_to_image(
        prompt=prompt,
        model=model
    )
    image.save(str(output_path))


def make_video(client, prompt, model, output_path):
    # Actual moving-video generation, not a still-image slideshow.
    video_bytes = client.text_to_video(
        prompt=prompt,
        model=model
    )

    if not isinstance(video_bytes, (bytes, bytearray)):
        raise RuntimeError(
            "The provider did not return video bytes."
        )

    if len(video_bytes) < 1000:
        raise RuntimeError("The returned video file is too small.")

    output_path.write_bytes(video_bytes)


def attach_narration(video, audio, output):
    # No background music is added.
    run_command([
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(audio),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        "-movflags", "+faststart",
        str(output)
    ])


def assemble_videos(clips, output):
    concat_file = output.parent / "concat_list.txt"

    concat_file.write_text(
        "".join(
            f"file '{clip.resolve().as_posix()}'\n"
            for clip in clips
        ),
        encoding="utf-8"
    )

    run_command([
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output)
    ])


# ---------------- USER INTERFACE ----------------

st.title("🎬 AI Story Video Studio")
st.write(
    "Create AI video clips, generate images, "
    "add narration and download your MP4."
)

with st.sidebar:
    st.header("Settings")

    token = st.text_input(
        "Hugging Face API token",
        type="password"
    )

    provider = st.selectbox(
        "Video/image provider",
        [
            "fal-ai",
            "replicate",
            "wavespeed",
            "novita",
            "together"
        ]
    )

    video_model = st.text_input(
        "Video model",
        "Wan-AI/Wan2.1-T2V-1.3B"
    )

    image_model = st.text_input(
        "Image model",
        "black-forest-labs/FLUX.1-schnell"
    )

    voice_name = st.selectbox(
        "Narrator voice",
        list(VOICES.keys())
    )

    rate = st.selectbox(
        "Narration speed",
        ["-15%", "-10%", "-5%", "+0%", "+5%", "+10%"],
        index=3
    )

project_name = st.text_input(
    "Project name", "My Story"
)

mode = st.radio(
    "Generation mode",
    [
        "AI moving video",
        "AI images with narration"
    ]
)

aspect = st.selectbox(
    "Video format",
    ["Landscape 16:9", "Portrait 9:16", "Square 1:1"]
)

story = st.text_area(
    "Write your story",
    height=250,
    placeholder=(
        "Scene 1: A small rabbit lives in a forest.\n\n"
        "Scene 2: One morning, the rabbit meets a lion."
    )
)

st.caption(
    "Use a blank line between scenes. "
    "For your first test, use only one or two scenes."
)

generate = st.button(
    "🚀 Generate video",
    type="primary",
    use_container_width=True
)


# ---------------- GENERATION ----------------

if generate:
    if not story.strip():
        st.error("Please write your story first.")
        st.stop()

    if not token.strip():
        st.error("Enter your Hugging Face API token.")
        st.stop()

    if not shutil.which("ffmpeg"):
        st.error(
            "FFmpeg is not installed or is missing from PATH. "
            "Install it and restart your terminal."
        )
        st.stop()

    scenes = [
        paragraph.strip().replace("\n", " ")
        for paragraph in re.split(r"\n\s*\n", story.strip())
        if paragraph.strip()
    ]

    if len(scenes) > 20:
        st.error(
            "Please use 20 scenes or fewer per run. "
            "You can create a long film chapter by chapter."
        )
        st.stop()

    project_dir = ROOT / (
        safe_name(project_name) + "_" +
        time.strftime("%Y%m%d_%H%M%S")
    )
    project_dir.mkdir(parents=True, exist_ok=True)

    try:
        client = InferenceClient(
            provider=provider,
            api_key=token.strip(),
            timeout=300
        )
    except Exception as exc:
        st.error(f"Could not connect to provider: {exc}")
        st.stop()

    video_clips = []
    errors = []

    progress = st.progress(0)
    status = st.empty()

    for number, scene in enumerate(scenes, start=1):
        status.write(
            f"Generating scene {number} of {len(scenes)}..."
        )

        base = project_dir / f"scene_{number:02d}"
        audio = base.with_suffix(".mp3")
        image = base.with_suffix(".png")
        raw_video = project_dir / f"raw_{number:02d}.mp4"
        narrated_video = project_dir / f"scene_{number:02d}.mp4"

        visual_prompt = (
            scene +
            ". Cinematic visual storytelling, realistic motion, "
            "consistent characters, detailed environment, "
            "no subtitles, no text, no logos, no watermark."
        )

        # Narration is independent of video generation.
        try:
            asyncio.run(
                make_narration(
                    scene,
                    VOICES[voice_name],
                    audio,
                    rate
                )
            )
        except Exception as exc:
            errors.append(
                f"Scene {number} narration failed: {exc}"
            )
            audio = None

        # Generate a still image for the scene.
        try:
            make_image(
                client,
                visual_prompt,
                image_model,
                image
            )
        except Exception as exc:
            errors.append(
                f"Scene {number} image failed: {exc}"
            )
            image = None

        if mode == "AI moving video":
            try:
                make_video(
                    client,
                    visual_prompt,
                    video_model,
                    raw_video
                )

                if audio and audio.exists():
                    attach_narration(
                        raw_video, audio, narrated_video
                    )
                else:
                    # Keep the video even if TTS fails.
                    shutil.copy2(raw_video, narrated_video)

                video_clips.append(narrated_video)

            except Exception as exc:
                errors.append(
                    f"Scene {number} video failed: {exc}"
                )

        else:
            # This mode deliberately creates a still-image video.
            if image and image.exists():
                still_video = project_dir / f"scene_{number:02d}.mp4"

                cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1",
                    "-i", str(image)
                ]

                if audio and audio.exists():
                    cmd += ["-i", str(audio)]

                if aspect == "Portrait 9:16":
                    width, height = 720, 1280
                elif aspect == "Square 1:1":
                    width, height = 1080, 1080
                else:
                    width, height = 1280, 720

                cmd += [
                    "-vf",
                    f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
                    "format=yuv420p",
                    "-t", "8",
                    "-r", "24",
                    "-c:v", "libx264",
                    "-preset", "veryfast"
                ]

                if audio and audio.exists():
                    cmd += ["-c:a", "aac", "-shortest"]
                else:
                    cmd += ["-an"]

                cmd += [str(still_video)]

                try:
                    run_command(cmd)
                    video_clips.append(still_video)
                except Exception as exc:
                    errors.append(
                        f"Scene {number} assembly failed: {exc}"
                    )

        progress.progress(number / len(scenes))

    status.write("Finishing your project...")

    final_video = project_dir / "final_video_no_music.mp4"

    if video_clips:
        try:
            assemble_videos(video_clips, final_video)

            st.success("Your video is ready!")

            st.video(str(final_video))

            st.download_button(
                "⬇️ Download final MP4",
                data=final_video.read_bytes(),
                file_name=final_video.name,
                mime="video/mp4",
                use_container_width=True
            )

        except Exception as exc:
            st.error(f"Final video assembly failed: {exc}")

            st.info(
                "You can still download the individual clips below."
            )
    else:
        st.error(
            "No video clips were generated. "
            "Read the error details below."
        )

    # Individual file downloads.
    st.subheader("📥 Individual files")

    for number in range(1, len(scenes) + 1):
        st.markdown(f"**Scene {number}**")

        audio = project_dir / f"scene_{number:02d}.mp3"
        image = project_dir / f"scene_{number:02d}.png"
        clip = project_dir / f"scene_{number:02d}.mp4"

        left, middle, right = st.columns(3)

        if clip.exists():
            with left:
                st.download_button(
                    f"Video {number}",
                    data=clip.read_bytes(),
                    file_name=clip.name,
                    mime="video/mp4",
                    key=f"clip_{number}"
                )

        if image.exists():
            with middle:
                st.download_button(
                    f"Image {number}",
                    data=image.read_bytes(),
                    file_name=image.name,
                    mime="image/png",
                    key=f"image_{number}"
                )

        if audio.exists():
            with right:
                st.download_button(
                    f"Narration {number}",
                    data=audio.read_bytes(),
                    file_name=audio.name,
                    mime="audio/mpeg",
                    key=f"audio_{number}"
                )

    if errors:
        with st.expander(
            f"⚠️ Errors and warnings ({len(errors)})",
            expanded=True
        ):
            for error in errors:
                st.error(error)

    st.info(
        "No background music was added. "
        "You can add music to the downloaded MP4 in CapCut."
    )
