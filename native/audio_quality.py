"""Boost PCM loudness with a soft knee instead of hard saturation."""
def gain_pcm(raw,gain):
    import numpy as np
    x=np.frombuffer(raw,dtype='<i2').astype(np.float32)/32768.0*gain
    magnitude=np.abs(x);threshold=.8
    y=np.where(magnitude<=threshold,magnitude,threshold+.2*np.tanh((magnitude-threshold)/.2))
    return (np.sign(x)*y*32766).astype('<i2').tobytes()

def limit_wav(path,gain):
    import wave
    with wave.open(str(path),'rb') as source:
        params=source.getparams();raw=source.readframes(source.getnframes())
    if params.sampwidth!=2:raise ValueError('Expected 16-bit speech audio')
    with wave.open(str(path),'wb') as output:
        output.setparams(params);output.writeframes(gain_pcm(raw,gain))
