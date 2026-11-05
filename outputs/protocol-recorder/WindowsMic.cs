using System;
using System.Threading;
using System.Runtime.InteropServices;
using Windows.Media;
using Windows.Media.Audio;
using Windows.Media.Render;
using Windows.Media.Capture;
using Windows.Media.MediaProperties;
using Windows.Foundation;
using System.Web.Script.Serialization;

// Only Windows selects/configures the capture endpoint. No microphone indexes or driver-specific formats.
class WindowsMic {
 [ComImport,Guid("5B0D3235-4DBA-4D44-865E-8F1D0E4FD04D"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
 interface IMemoryBufferByteAccess { void GetBuffer(out IntPtr data,out uint capacity); }
 static object gate=new object();
 static void Emit(object value){lock(gate) Console.WriteLine(new JavaScriptSerializer().Serialize(value));}
 static T Wait<T>(IAsyncOperation<T> op){using(var signal=new ManualResetEvent(false)){op.Completed=(o,status)=>signal.Set();signal.WaitOne();return op.GetResults();}}
 static int Main(string[] args){
 Console.OutputEncoding=new System.Text.UTF8Encoding(false);
 if(args.Length==1 && args[0]=="--call-output"){
   try{
     var id=Windows.Media.Devices.MediaDevice.GetDefaultAudioRenderId(Windows.Media.Devices.AudioDeviceRole.Communications);
     Emit(new {name=Wait(Windows.Devices.Enumeration.DeviceInformation.CreateFromIdAsync(id)).Name});return 0;
   }catch(Exception){return 1;}
 }
 var stop=new ManualResetEvent(false);
 try {
 if(Console.ReadLine()==null)return 1;
 new Thread(()=>{Console.ReadLine();stop.Set();}){IsBackground=true}.Start();
 var created=Wait(AudioGraph.CreateAsync(new AudioGraphSettings(AudioRenderCategory.Communications)));
 if(created.Status!=AudioGraphCreationStatus.Success)throw new Exception("Windows AudioGraph: "+created.Status);
 using(var graph=created.Graph){
#if TEST_INPUT
 var sample=Wait(Windows.Storage.StorageFile.GetFileFromPathAsync(Environment.GetEnvironmentVariable("PROTOCOL_TEST_WAV")));
 var fileResult=Wait(graph.CreateFileInputNodeAsync(sample));
 if(fileResult.Status!=AudioFileNodeCreationStatus.Success)throw new Exception(fileResult.Status.ToString());
 const string deviceName="test file";
 using(var mic=fileResult.FileInputNode)
#else
 var result=Wait(graph.CreateDeviceInputNodeAsync(MediaCategory.Communications));
 if(result.Status!=AudioDeviceNodeCreationStatus.Success)throw new Exception("Микрофон Windows: "+result.Status);
 string deviceName=result.DeviceInputNode.Device.Name;
 using(var mic=result.DeviceInputNode)
#endif
 using(var output=graph.CreateFrameOutputNode()){
 mic.AddOutgoingConnection(output);
 var fmt=output.EncodingProperties; if(fmt.BitsPerSample!=32 || !String.Equals(fmt.Subtype,"Float",StringComparison.OrdinalIgnoreCase))throw new Exception("Неожиданный формат AudioGraph: "+fmt.Subtype);
 bool first=true;Exception failure=null;
 TypedEventHandler<AudioGraph,Object> onFrame=(sender,eventArgs)=>{
 try{using(var frame=output.GetFrame())using(var buf=frame.LockBuffer(AudioBufferAccessMode.Read))using(var view=buf.CreateReference()){
 if(buf.Length==0)return;
 IntPtr ptr;uint cap;((IMemoryBufferByteAccess)view).GetBuffer(out ptr,out cap);
 if(cap<buf.Length)throw new Exception("Неполный аудиобуфер Windows.");
 var data=new byte[buf.Length];Marshal.Copy(ptr,data,0,data.Length);
 if(first){Emit(new {type="ready",name=deviceName,rate=fmt.SampleRate,channels=fmt.ChannelCount,bits=32,floating=true});first=false;}
 Emit(new {type="audio",data=Convert.ToBase64String(data)});
 }}catch(Exception e){failure=e;stop.Set();}
 };
 graph.UnrecoverableErrorOccurred+=(sender,err)=>{failure=new Exception("Windows AudioGraph: "+err.Error);stop.Set();};
 graph.QuantumStarted+=onFrame;

 graph.Start();stop.WaitOne();graph.Stop();graph.QuantumStarted-=onFrame;
 if(failure!=null)throw failure;
 }}
 }catch(Exception e){Emit(new {type="error",message=e.Message});return 1;}
 finally{Emit(new {type="stopped"});}return 0;
 }
}





