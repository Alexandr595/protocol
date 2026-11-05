// Windows 10/11 shared-mode WASAPI. No PortAudio, virtual drivers or network.
using System;
using System.IO;
using System.Text;
using System.Diagnostics;
using System.Threading;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
using System.Collections.Generic;

[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class EnumeratorClass {}
[ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface Enumerator {
    void EnumAudioEndpoints(int flow, uint mask, out Devices devices);
    void GetDefaultAudioEndpoint(int flow, int role, out Device device);
    void GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out Device device);
    void RegisterEndpointNotificationCallback(IntPtr callback);
    void UnregisterEndpointNotificationCallback(IntPtr callback);
}
[ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface Devices { void GetCount(out uint count); void Item(uint index, out Device device); }
[ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface Device {
    void Activate(ref Guid iid, uint context, IntPtr parameters, [MarshalAs(UnmanagedType.IUnknown)] out object result);
    void OpenPropertyStore(uint access, out Properties properties);
    void GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
    void GetState(out uint state);
}
[StructLayout(LayoutKind.Sequential)] struct PropertyKey { public Guid guid; public uint id; }
[StructLayout(LayoutKind.Explicit, Size=24)] struct PropertyValue {
    [FieldOffset(0)] public ushort type;
    [FieldOffset(8)] public IntPtr pointer;
}
[ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface Properties {
    void GetCount(out uint count); void GetAt(uint index, out PropertyKey key);
    void GetValue(ref PropertyKey key, out PropertyValue value);
}
[StructLayout(LayoutKind.Sequential, Pack=2)] struct WaveFormat {
    public ushort tag, channels; public uint rate, bytesPerSecond;
    public ushort align, bits, extra;
}
[ComImport, Guid("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface AudioClient {
    void Initialize(int mode, uint flags, long duration, long periodicity, IntPtr format, IntPtr session);
    void GetBufferSize(out uint size); void GetStreamLatency(out long latency); void GetCurrentPadding(out uint padding);
    [PreserveSig] int IsFormatSupported(int mode, IntPtr format, out IntPtr closest);
    void GetMixFormat(out IntPtr format); void GetDevicePeriod(out long normal, out long minimum);
    void Start(); void Stop(); void Reset(); void SetEventHandle(IntPtr handle);
    void GetService(ref Guid iid, [MarshalAs(UnmanagedType.IUnknown)] out object service);
}
[ComImport, Guid("C8ADBD64-E71E-48A0-A4DE-185C395CD317"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface CaptureClient {
    void GetBuffer(out IntPtr data, out uint frames, out uint flags, out ulong position, out ulong qpc);
    void ReleaseBuffer(uint frames); void GetNextPacketSize(out uint frames);
}

class AudioHost {
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    static volatile bool stop;
    static string phase="initialization";
    static Guid audioGuid = new Guid("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2");
    static Guid captureGuid = new Guid("C8ADBD64-E71E-48A0-A4DE-185C395CD317");
    [DllImport("ole32.dll")] static extern int PropVariantClear(ref PropertyValue value);
    static void Release(object value) { if(value != null && Marshal.IsComObject(value)) Marshal.ReleaseComObject(value); }
    static string Id(Device device) { string id; device.GetId(out id); return id; }
    static string Name(Device device) {
        Properties properties = null;
        var key = new PropertyKey { guid=new Guid("A45C254E-DF1C-4EFD-8020-67D146A850E0"), id=14 };
        try {
            device.OpenPropertyStore(0, out properties);
            PropertyValue value; properties.GetValue(ref key, out value);
            try { return value.type == 31 ? Marshal.PtrToStringUni(value.pointer) : Id(device); }
            finally { PropVariantClear(ref value); }
        } finally { Release(properties); }
    }
    static Device Resolve(Enumerator enumerator, string selector, int flow) {
        Device device;
        if(selector == "@default") enumerator.GetDefaultAudioEndpoint(flow, 2, out device); // eCommunications
        else enumerator.GetDevice(selector, out device);
        return device;
    }
    static void Status(string type, string message) {
        Console.Error.WriteLine(Json.Serialize(new { type=type, message=message })); Console.Error.Flush();
    }
    static string Error(Exception exc) {
        uint code = unchecked((uint)Marshal.GetHRForException(exc));
        string hint = code == 0x80070005 ? "Windows запретила доступ к микрофону. Разрешите доступ классическим приложениям." :
            code == 0x8889000A ? "Устройство занято другим приложением в монопольном режиме." :
            code == 0x88890004 ? "Устройство отключено или Windows изменила его режим." :
            code == 0x80070490 ? "В Windows нет доступного устройства для выбранного источника." :
            code == 0x88890008 ? "Аудиодрайвер не принял формат shared-mode с преобразованием Windows." : exc.Message;
        return hint + " (WASAPI 0x" + code.ToString("X8") + ")";
    }
    static bool Recoverable(Exception exc) {
        uint code=unchecked((uint)Marshal.GetHRForException(exc));
        return code==0x88890004 || code==0x88890026 || code==0x88890010 || code==0x80070490;
    }
    static byte[] Pcm(byte[] raw, int frames, WaveFormat format, bool floating, int outputChannels) {
        if(!floating && format.bits==16 && format.channels==outputChannels && format.align==outputChannels*2) return raw;
        var result=new byte[checked(frames*outputChannels*2)];
        int bytes=format.bits/8;
        for(int frame=0;frame<frames;frame++) {
            double sum=0, left=0, right=0;
            for(int channel=0;channel<format.channels;channel++) {
                int offset=frame*format.align+channel*bytes; double sample;
                if(floating) sample=bytes==4 ? BitConverter.ToSingle(raw,offset) : BitConverter.ToDouble(raw,offset);
                else if(bytes==1) sample=(raw[offset]-128)/128.0;
                else if(bytes==2) sample=BitConverter.ToInt16(raw,offset)/32768.0;
                else if(bytes==3) sample=((raw[offset]|raw[offset+1]<<8|raw[offset+2]<<16)<<8)/2147483648.0;
                else sample=BitConverter.ToInt32(raw,offset)/2147483648.0;
                if(Double.IsNaN(sample)||Double.IsInfinity(sample)) sample=0;
                sum+=sample; if(channel==0) left=sample; else if(channel==1) right=sample;
            }
            for(int channel=0;channel<outputChannels;channel++) {
                double sample=(outputChannels==2 && format.channels==2) ? (channel==0 ? left : right) : sum/format.channels;
                short value=(short)Math.Max(-32768,Math.Min(32767,Math.Round(sample*32768)));
                int offset=(frame*outputChannels+channel)*2;
                result[offset]=(byte)value; result[offset+1]=(byte)(value>>8);
            }
        }
        return result;
    }
    static void List() {
        var enumerator=(Enumerator)new EnumeratorClass();
        var result=new List<object>();
        try {
            for(int flow=0;flow<=1;flow++) {
                string kind=flow==1 ? "mic" : "system";
                Device selected=null;
                try {
                    selected=Resolve(enumerator,"@default",flow);
                    result.Add(new { native_id="@default", kind=kind, name="Автоматически — устройство связи Windows ("+Name(selected)+")", automatic=true });
                } catch(COMException) {} finally { Release(selected); }
                Devices devices=null;
                try {
                    enumerator.EnumAudioEndpoints(flow,1,out devices);
                    uint count; devices.GetCount(out count);
                    for(uint index=0;index<count;index++) {
                        Device device=null;
                        try { devices.Item(index,out device); result.Add(new { native_id=Id(device),kind=kind,name=Name(device),automatic=false }); }
                        finally { Release(device); }
                    }
                } finally { Release(devices); }
            }
            Console.WriteLine(Json.Serialize(result));
        } finally { Release(enumerator); }
    }
    static void Capture(string kind,string selector) {
        int flow=kind=="mic" ? 1 : 0;
        ushort channels=(ushort)(flow==1 ? 1 : 2);
        var inputThread=new Thread(delegate() { try { Console.ReadLine(); } finally {stop=true;} });
        inputThread.IsBackground=true; inputThread.Start();
        bool ready=false;
        DateTime? missingSince=null;
        using(var output=new BinaryWriter(Console.OpenStandardOutput())) {
            while(!stop) {
                Enumerator enumerator=null; Device device=null; AudioClient audio=null; CaptureClient capture=null;
                try {
                    phase="endpoint"; enumerator=(Enumerator)new EnumeratorClass(); device=Resolve(enumerator,selector,flow);
                    string openedId=Id(device);
                    phase="Activate IAudioClient"; object activated; device.Activate(ref audioGuid,23,IntPtr.Zero,out activated); audio=(AudioClient)activated;
                    // Use the actual engine mix format, not a guessed microphone/BT format.
                    phase="GetMixFormat"; IntPtr mix; audio.GetMixFormat(out mix);
                    WaveFormat format; bool floating;
                    try {
                        format=(WaveFormat)Marshal.PtrToStructure(mix,typeof(WaveFormat));
                        int tag=format.tag;
                        if(tag==0xfffe) {
                            Guid subtype=(Guid)Marshal.PtrToStructure(IntPtr.Add(mix,24),typeof(Guid));
                            if(subtype==new Guid("00000003-0000-0010-8000-00aa00389b71")) tag=3;
                            else if(subtype==new Guid("00000001-0000-0010-8000-00aa00389b71")) tag=1;
                            else throw new NotSupportedException("Неизвестный формат аудиодрайвера: "+subtype);
                        }
                        floating=tag==3;
                        if(format.channels<1 || format.rate<8000 || format.rate>384000 ||
                           (floating ? (format.bits!=32 && format.bits!=64) : (tag!=1 || (format.bits!=8 && format.bits!=16 && format.bits!=24 && format.bits!=32))))
                            throw new NotSupportedException("Неподдерживаемый формат аудиодрайвера.");
                        phase="Initialize shared"; audio.Initialize(0,flow==0 ? 0x00020000u : 0,1000000,0,mix,IntPtr.Zero);
                    } finally {Marshal.FreeCoTaskMem(mix);}
                    phase="GetService capture"; object service; audio.GetService(ref captureGuid,out service); capture=(CaptureClient)service;
                    phase="Start"; audio.Start(); phase="GetBuffer";
                    Status(ready ? "resumed" : "ready",Name(device)); ready=true; missingSince=null;
                    DateTime check=DateTime.UtcNow.AddSeconds(1);
                    while(!stop) {
                        uint frames; capture.GetNextPacketSize(out frames);
                        while(frames>0 && !stop) {
                            IntPtr pointer; uint flags; ulong position,qpc;
                            capture.GetBuffer(out pointer,out frames,out flags,out position,out qpc);
                            try {
                                var raw=new byte[checked((int)frames*format.align)];
                                if((flags & 2)==0) Marshal.Copy(pointer,raw,0,raw.Length);
                                else if(!floating && format.bits==8) for(int i=0;i<raw.Length;i++) raw[i]=128;
                                var bytes=Pcm(raw,(int)frames,format,floating,channels);
                                output.Write(bytes.Length);
                                output.Write((flags & 4)==0 ? qpc/10000000.0 : 0.0);
                                output.Write(Stopwatch.GetTimestamp()/(double)Stopwatch.Frequency);
                                output.Write((int)(flags & 5)); output.Write((int)format.rate); output.Write(bytes); output.Flush();
                            } finally { capture.ReleaseBuffer(frames); }
                            capture.GetNextPacketSize(out frames);
                        }
                        if(selector=="@default" && DateTime.UtcNow>=check) {
                            Device current=null;
                            try { current=Resolve(enumerator,selector,flow); if(Id(current)!=openedId) {Status("warning","Windows сменила устройство связи. Переподключение…"); break;} }
                            finally {Release(current);}
                            check=DateTime.UtcNow.AddSeconds(1);
                        }
                        Thread.Sleep(10);
                    }
                } catch(COMException exc) {
                    if(!Recoverable(exc)) throw;
                    if(!missingSince.HasValue) { missingSince=DateTime.UtcNow; Status("warning",Error(exc)+" Повторное подключение…"); }
                    if((DateTime.UtcNow-missingSince.Value).TotalSeconds >= (ready ? 20 : 5)) throw;
                    Thread.Sleep(250);
                } finally {
                    if(audio!=null) {try {audio.Stop();} catch(COMException) {}}
                    Release(capture); Release(audio); Release(device); Release(enumerator);
                }
            }
        }
    }
    [MTAThread] static int Main(string[] args) {
        Console.OutputEncoding=new UTF8Encoding(false);
        Console.InputEncoding=new UTF8Encoding(false);
        try {
            if(args.Length==1 && args[0]=="list") List();
            else if(args.Length==3 && args[0]=="capture" && (args[1]=="mic" || args[1]=="system")) Capture(args[1],args[2]);
            else throw new ArgumentException("Usage: AudioHost list | capture mic|system endpoint-id|@default");
            return 0;
        } catch(Exception exc) {Status("error",phase+": "+Error(exc)); return 1;}
    }
}

