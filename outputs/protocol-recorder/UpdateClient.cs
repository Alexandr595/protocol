using System;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Text;
using System.Web.Script.Serialization;
using System.Security.Cryptography;
using System.Collections.Generic;
using System.Diagnostics;
class UpdateClient{
 public static string Run(){
 var config=Delivery.Read(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Protocol","server.json"));
 if(!config.ContainsKey("secret"))throw new Exception("Сначала сохраните подключение к серверу.");
 string tmp=Path.Combine(Path.GetTempPath(),"Protocol-"+Guid.NewGuid().ToString("N"));
 Directory.CreateDirectory(tmp);
 try{
 var req=(HttpWebRequest)WebRequest.Create((string)config["server"]+"/client.zip");req.AllowAutoRedirect=false;req.Proxy=null;req.Timeout=30000;req.ReadWriteTimeout=30000;
 var pass=Encoding.UTF8.GetString(ProtectedData.Unprotect(Convert.FromBase64String((string)config["secret"]),null,DataProtectionScope.CurrentUser));
 req.Headers["Authorization"]="Basic "+Convert.ToBase64String(Encoding.UTF8.GetBytes(config["username"]+":"+pass));
 string archive=Path.Combine(tmp,"release.zip");
 using(var res=req.GetResponse())using(var stream=res.GetResponseStream())using(var f=File.Create(archive)){
 byte[] b=new byte[65536];int n;while((n=stream.Read(b,0,b.Length))>0){if(f.Length+n>100*1024*1024)throw new InvalidDataException();f.Write(b,0,n);}
 }
 using(var z=ZipFile.OpenRead(archive)){
 var info=z.GetEntry("release.json");if(info==null || info.Length>8192)throw new Exception("Сервер не предоставляет подписанное обновление.");
 Dictionary<string,string> m;using(var rd=new StreamReader(info.Open()))m=new JavaScriptSerializer().Deserialize<Dictionary<string,string>>(rd.ReadToEnd());
 var signed=Encoding.UTF8.GetBytes("Protocol Windows\n"+m["version"]+"\n"+m["sha256"]);
 using(var rsa=new RSACryptoServiceProvider()){rsa.PersistKeyInCsp=false;rsa.FromXmlString(File.ReadAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"update-public.xml")));if(!rsa.VerifyData(signed,"SHA256",Convert.FromBase64String(m["signature"])))throw new Exception("Подпись обновления недействительна.");}
 if(new Version(m["version"])<=new Version("0.10.1"))return "Установлена актуальная версия 0.10.1.";
 var entry=z.GetEntry("ProtocolSetup.msi");if(entry==null||entry.Length>100*1024*1024)throw new InvalidDataException();
 string exe=Path.Combine(tmp,"ProtocolSetup.msi");entry.ExtractToFile(exe);
 using(var sha=SHA256.Create())using(var f=File.OpenRead(exe)){if(BitConverter.ToString(sha.ComputeHash(f)).Replace("-","").ToLowerInvariant()!=m["sha256"])throw new Exception("Файл обновления повреждён.");}
 using(var p=Process.Start(new ProcessStartInfo(Path.Combine(Environment.SystemDirectory,"msiexec.exe"),"/i \""+exe+"\" /passive /norestart"){UseShellExecute=false})){p.WaitForExit();if(p.ExitCode!=0)throw new Exception("Не удалось установить обновление.");}
 return "Обновление установлено. Закройте приложение и откройте Протокол через меню Пуск.";
 }
 }finally{foreach(var n in new[]{"release.zip","ProtocolSetup.msi"}){string f=Path.Combine(tmp,n);if(File.Exists(f))File.Delete(f);}Directory.Delete(tmp);}
 }
}

