"""WASAPI inputs and loopback endpoints. No cloud services or virtual drivers."""
import pyaudiowpatch as pa
import re


class KernelCapture:
    """Expose the recorder's stream contract for a sounddevice input stream."""
    def __init__(self, stream): self.stream = stream
    def start_stream(self): self.stream.start()
    def stop_stream(self): self.stream.stop()
    def is_active(self): return self.stream.active
    def close(self): self.stream.close()


def kernel_microphone(device, callback):
    import sounddevice as sd
    hosts = sd.query_hostapis()
    inventory = list(sd.query_devices())
    failures = []
    def receive(data, frames, times, flags):
        callback(bytes(data), frames, {'current_time': times.currentTime,
                 'input_buffer_adc_time': times.inputBufferAdcTime}, bool(flags))
    # sounddevice uses a separate PortAudio build. Try the selected endpoint
    # in shared mode before the older Bluetooth-only WDM-KS fallback. Keep the
    # PCM format unchanged: the recorder callback already owns rate/channels.
    for host in ('Windows WASAPI', 'Windows DirectSound', 'MME'):
        matches = [(i,d) for i,d in enumerate(inventory)
                   if d['max_input_channels'] >= device['channels']
                   and hosts[d['hostapi']]['name'] == host
                   and d['name'].strip().casefold() == device['name'].strip().casefold()]
        if len(matches) > 1:
            raise ValueError('Несколько микрофонов с одинаковым именем; резервный источник нельзя выбрать однозначно.')
        if not matches: continue
        options = {'extra_settings': sd.WasapiSettings(exclusive=False, auto_convert=True)} if host == 'Windows WASAPI' else {}
        try:
            stream = sd.RawInputStream(device=matches[0][0], samplerate=device['rate'],
                                      channels=device['channels'], dtype='int16', callback=receive, **options)
        except Exception as exc:
            failures.append(f'{host}: {exc}')
            continue
        device['backend'] = 'sounddevice / ' + host
        return KernelCapture(stream)
    # WDM Bluetooth names include a driver resource string followed by (model).
    # Require a unique exact model token; never fall back to the default mic.
    match = re.search(r'\((.+?) Hands-Free AG Audio\)', device['name'], re.I)
    if not match:
        raise ValueError('; '.join(failures) if failures else 'Резервный вход с точным именем выбранного микрофона не найден.')
    token = '(' + match[1].casefold() + ')'
    candidates = [(i,d) for i,d in enumerate(inventory)
                  if d['max_input_channels'] >= device['channels']
                  and hosts[d['hostapi']]['name'] == 'Windows WDM-KS'
                  and token in d['name'].casefold()]
    if len(candidates) != 1: raise ValueError('Резервный вход микрофона не найден однозначно.')
    stream = sd.RawInputStream(device=candidates[0][0], samplerate=device['rate'],
                              channels=device['channels'], dtype='int16', callback=receive)
    device['backend'] = 'WDM-KS'
    return KernelCapture(stream)


class WindowsAudio:
    def __init__(self):
        self.audio = pa.PyAudio()

    def devices(self):
        api = self.audio.get_host_api_info_by_type(pa.paWASAPI)
        host = api['index']
        inventory = list(self.audio.get_device_info_generator())
        outputs = [d for d in inventory if d['hostApi']==host and d['maxOutputChannels']>0]
        loops = [d for d in inventory if d['hostApi']==host and d['isLoopbackDevice']]
        # PortAudio appends loopback counterparts in render-endpoint order.
        default_loop = next((l['index'] for o,l in zip(outputs,loops) if o['index']==api['defaultOutputDevice']), None)
        devices = []
        for info in inventory:
            if info['hostApi'] != host or info['maxInputChannels'] < 1:
                continue
            devices.append({'id': int(info['index']), 'name': info['name'],
                            'kind': 'system' if info['isLoopbackDevice'] else 'mic',
                            'rate': int(info['defaultSampleRate']),
                            'channels': min(2, int(info['maxInputChannels']))})
            devices[-1]['default'] = info['index'] == (default_loop if info['isLoopbackDevice'] else api['defaultInputDevice'])
        return devices

    def open(self, device, callback):
        def receive(data, frames, times, flags):
            callback(data, frames, times, flags)
            return None, pa.paContinue
        try:
            return self.audio.open(format=pa.paInt16, channels=device['channels'],
                                   rate=device['rate'], input=True, input_device_index=device['id'],
                                   frames_per_buffer=2048, stream_callback=receive, start=False)
        except OSError as exc:
            if device['kind'] != 'mic' or exc.errno != -9996: raise
            try: return kernel_microphone(device, callback)
            except Exception as fallback:
                raise OSError(exc.errno, f'{exc.strerror}; резервный захват: {fallback}') from fallback

    def close(self):
        self.audio.terminate()
