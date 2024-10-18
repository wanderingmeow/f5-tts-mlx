import argparse
import datetime
import pkgutil
import re
from typing import Optional

import mlx.core as mx

import numpy as np

from f5_tts_mlx.cfm import F5TTS
from f5_tts_mlx.utils import convert_char_to_pinyin

from vocos_mlx import Vocos

import soundfile as sf

from pathlib import Path

SAMPLE_RATE = 24_000
HOP_LENGTH = 256
FRAMES_PER_SEC = SAMPLE_RATE / HOP_LENGTH
TARGET_RMS = 0.1


def generate(
    generation_text: str,
    duration: Optional[float] = None,
    model_name: str = "f5-tts",
    ref_audio_path: Optional[str] = None,
    ref_audio_text: Optional[str] = None,
    cfg_strength: float = 2.0,
    sway_sampling_coef: float = -1.0,
    steps: int = 32,
    speed: float = 1.0, # used when duration is None as part of the duration heuristic
    seed: Optional[int] = None,
    output_path: str = "output.wav",
):
    f5tts = F5TTS.from_pretrained(model_name)

    if ref_audio_path is None:
        data = pkgutil.get_data("f5_tts_mlx", "tests/test_en_1_ref_short.wav")

        # write to a temp file
        tmp_ref_audio_file = "/tmp/ref.wav"
        with open(tmp_ref_audio_file, "wb") as f:
            f.write(data)

        if data is not None:
            audio, sr = sf.read(tmp_ref_audio_file)
            ref_audio_text = "Some call me nature, others call me mother nature."
    else:
        # load reference audio
        audio, sr = sf.read(ref_audio_path)
        if sr != SAMPLE_RATE:
            raise ValueError("Reference audio must have a sample rate of 24kHz")

    audio = mx.array(audio)
    ref_audio_duration = audio.shape[0] / SAMPLE_RATE
    print(f"Got reference audio with duration: {ref_audio_duration:.2f} seconds")

    rms = mx.sqrt(mx.mean(mx.square(audio)))
    if rms < TARGET_RMS:
        audio = audio * TARGET_RMS / rms

    # generate the audio for the given text
    text = convert_char_to_pinyin([ref_audio_text + " " + generation_text])

    # use a heuristic to determine the duration if not provided
    if duration is None:
        ref_audio_len = audio.shape[0] // HOP_LENGTH
        zh_pause_punc = r"。，、；：？！"
        ref_text_len = len(ref_audio_text.encode('utf-8')) + 3 * len(re.findall(zh_pause_punc, ref_audio_text))
        gen_text_len = len(generation_text.encode('utf-8')) + 3 * len(re.findall(zh_pause_punc, generation_text))
        duration_in_frames = ref_audio_len + int(ref_audio_len / ref_text_len * gen_text_len / speed)
        duration = (duration_in_frames / FRAMES_PER_SEC) - ref_audio_duration
        print(f"Using duration of {duration:.2f} seconds for generated speech.")

    frame_duration = int((ref_audio_duration + duration) * FRAMES_PER_SEC)
    print(f"Generating {frame_duration} total frames of audio...")

    start_date = datetime.datetime.now()
    vocos = Vocos.from_pretrained(Path.cwd() / "models/vocos-mel-24khz")

    wave, _ = f5tts.sample(
        mx.expand_dims(audio, axis=0),
        text=text,
        duration=frame_duration,
        steps=steps,
        cfg_strength=cfg_strength,
        sway_sampling_coef=sway_sampling_coef,
        seed=seed,
        vocoder=vocos.decode,
    )

    # trim the reference audio
    wave = wave[audio.shape[0]:]
    generated_duration = wave.shape[0] / SAMPLE_RATE
    elapsed_time = datetime.datetime.now() - start_date

    print(f"Generated {generated_duration:.2f} seconds of audio in {elapsed_time}.")

    sf.write(output_path, np.array(wave), SAMPLE_RATE)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate audio from text using f5-tts-mlx"
    )

    parser.add_argument(
        "--model",
        type=str,
        default="f5-tts",
        help="Name of the model to use",
    )
    parser.add_argument(
        "--text", type=str, required=True, help="Text to generate speech from"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Duration of the generated audio in seconds",
    )
    parser.add_argument(
        "--ref-audio",
        type=str,
        default=None,
        help="Path to the reference audio file",
    )
    parser.add_argument(
        "--ref-text",
        type=str,
        default=None,
        help="Text spoken in the reference audio",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output.wav",
        help="Path to save the generated audio output",
    )
    parser.add_argument(
        "--cfg",
        type=float,
        default=2.0,
        help="Strength of classifer free guidance",
    )
    parser.add_argument(
        "--sway-coef",
        type=float,
        default=-1.0,
        help="Coefficient for sway sampling",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speed factor for the duration heuristic",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed for noise generation",
    )
    parser.add_argument(
        "--step",
        type=int,
        default=32,
        help="Step count for ODE sampling",
    )

    args = parser.parse_args()

    generate(
        generation_text=args.text,
        duration=args.duration,
        model_name=args.model,
        ref_audio_path=args.ref_audio,
        ref_audio_text=args.ref_text,
        cfg_strength=args.cfg,
        sway_sampling_coef=args.sway_coef,
        steps=args.step,
        speed=args.speed,
        seed=args.seed,
        output_path=args.output,
    )
