import os
import inflect
import pytest

from dataset.forced_alignment.search import similarity
from dataset.transcribe import create_transcription_model
from synthesis.synthesize import load_model, synthesize
from synthesis.waveglow import Waveglow
from synthesis.hifigan import Hifigan


MIN_SYNTHESIS_SCORE = 0.3


@pytest.mark.slow
def test_waveglow_synthesis():
    model_path = os.path.join("test_samples", "model.pt")
    waveglow_path = os.path.join("test_samples", "waveglow_256channels_universal_v5.pt")
    graph_path = "graph.png"
    audio_path = "synthesized_audio.wav"
    transcription_model = create_transcription_model()

    model = load_model(model_path)
    waveglow = Waveglow(waveglow_path)
    text = "hello everybody my name is david attenborough"
    inflect_engine = inflect.engine()
    synthesize(model=model, text=text, inflect_engine=inflect_engine, graph=graph_path, audio=audio_path, vocoder=waveglow)

    assert os.path.isfile(graph_path)
    assert os.path.isfile(audio_path)
    assert similarity(text, transcription_model.transcribe(audio_path)) > MIN_SYNTHESIS_SCORE

    os.remove(graph_path)
    os.remove(audio_path)


@pytest.mark.slow
def test_hifigan_synthesis():
    model_path = os.path.join("test_samples", "model.pt")
    hifigan_model_path = os.path.join("test_samples", "hifigan.pt")
    hifigan_config_path = os.path.join("test_samples", "config.json")
    graph_path = "graph.png"
    audio_path = "synthesized_audio.wav"
    transcription_model = create_transcription_model()

    model = load_model(model_path)
    hifigan = Hifigan(hifigan_model_path, hifigan_config_path)
    text = "hello everybody my name is david attenborough"
    inflect_engine = inflect.engine()
    synthesize(model=model, text=text, inflect_engine=inflect_engine, graph=graph_path, audio=audio_path, vocoder=hifigan)

    assert os.path.isfile(graph_path)
    assert os.path.isfile(audio_path)
    assert similarity(text, transcription_model.transcribe(audio_path)) > MIN_SYNTHESIS_SCORE

    os.remove(graph_path)
    os.remove(audio_path)
