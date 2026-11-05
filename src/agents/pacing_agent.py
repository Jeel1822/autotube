import numpy as np
import scipy.io.wavfile as wav

def get_impact_peaks(audio_path: str, threshold=0.7):
    """Detects peak energy moments in TTS for cinematic cuts."""
    rate, data = wav.read(audio_path)
    # Convert to mono if stereo
    if len(data.shape) > 1:
        data = data.mean(axis=1)
    # Calculate rolling energy
    window = int(rate * 0.2)
    energy = np.convolve(data**2, np.ones(window)/window, mode='same')
    peaks = np.where(energy > np.percentile(energy, threshold * 100))[0]
    return peaks / rate
