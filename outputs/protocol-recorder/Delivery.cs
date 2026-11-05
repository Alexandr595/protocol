using System;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Collections.Generic;
using System.Web.Script.Serialization;

public static class Delivery {
    static readonly object Gate=new object();
    static readonly object WorkerGate=new object();
    static readonly string Settings=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Protocol","server.json");
    static JavaScriptSerializer Json {get{return new JavaScriptSerializer{MaxJsonLength=16*1024*1024};}}
    public static Dictionary<string,object> Read(string path) {
        return File.Exists(path)?Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path)):new Dictionary<string,object>();
    }
    public static void Save(string path,object value) {
        string temp=path+".tmp";File.WriteAllText(temp,Json.Serialize(value),Encoding.UTF8);
        if(File.Exists(path))File.Replace(temp,path,null);else File.Move(temp,path);
    }
    public static string Address {
        get {lock(Gate){var s=Read(Settings);return s.ContainsKey("server")?(string)s["server"]:"http://192.168.7.66:18765";}}
    }
    public static bool Configured {get {lock(Gate)return File.Exists(Settings);}}
    public static string Username {get {lock(Gate){var s=Read(Settings);return s.ContainsKey("username")?(string)s["username"]:"meeting";}}}
    public static void CheckSaved() {Dictionary<string,object> s;lock(Gate)s=Read(Settings);Request(s,"/api/state",null);}
    public static Dictionary<string,object> ReusePassword(Dictionary<string,object> previous,string server,string username,string password) {
        if(String.IsNullOrEmpty(password)) {
            if(!previous.ContainsKey("secret") || !previous.ContainsKey("server") ||
                !String.Equals((string)previous["server"],server,StringComparison.OrdinalIgnoreCase) ||
                (string)previous["username"]!=username)throw new Exception("Для нового сервера или логина введите пароль.");
            return new Dictionary<string,object>(previous);
        }
        return new Dictionary<string,object>{{"server",server},{"username",username},
            {"secret",Convert.ToBase64String(ProtectedData.Protect(Encoding.UTF8.GetBytes(password),null,DataProtectionScope.CurrentUser))}};
    }
    public static void Configure(string server,string username,string password) {
        Uri uri;
        if(!Uri.TryCreate(server.Trim().TrimEnd('/'),UriKind.Absolute,out uri)||
            (uri.Scheme!="http"&&uri.Scheme!="https")||uri.UserInfo!=""||uri.AbsolutePath!="/"||uri.Query!=""||uri.Fragment!="")
            throw new Exception("Укажите адрес сервера без пути, например http://192.168.7.66:18765");
        Dictionary<string,object> settings;
        lock(Gate)settings=ReusePassword(Read(Settings),uri.GetLeftPart(UriPartial.Authority),username,password);
        // Check the actual credentials before storing them or sending audio.
        Request(settings,"/api/state",null);
        lock(Gate)Save(Settings,settings);
    }
    static string Request(Dictionary<string,object> settings,string route,string file,string person=null) {
        var request=(HttpWebRequest)WebRequest.Create((string)settings["server"]+route);
        request.Proxy=null;request.AllowAutoRedirect=false;request.Timeout=120000;request.ReadWriteTimeout=120000;
        request.ServicePoint.Expect100Continue=false;
        string password=Encoding.UTF8.GetString(ProtectedData.Unprotect(Convert.FromBase64String((string)settings["secret"]),null,DataProtectionScope.CurrentUser));
        request.Headers["Authorization"]="Basic "+Convert.ToBase64String(Encoding.UTF8.GetBytes((string)settings["username"]+":"+password));
        request.Headers["X-Local-App"]="meeting-ai";
        if(file!=null) {
            request.Method="POST";request.ContentType="application/octet-stream";
            request.ContentLength=new FileInfo(file).Length;request.AllowWriteStreamBuffering=false;
            request.Headers["X-Filename"]=Uri.EscapeDataString(person==null?Path.GetFileName(Path.GetDirectoryName(file))+".meeting":Path.GetFileName(file));
            if(person!=null)request.Headers["X-Person-Name"]=Uri.EscapeDataString(person);
            using(var src=File.OpenRead(file))using(var dst=request.GetRequestStream())src.CopyTo(dst,256*1024);
            request.Timeout=24*60*60*1000;
        }
        try {
            using(var response=(HttpWebResponse)request.GetResponse())using(var reader=new StreamReader(response.GetResponseStream()))return reader.ReadToEnd();
        }catch(WebException ex) {
            var response=ex.Response as HttpWebResponse;
            if(response!=null)using(response)using(var reader=new StreamReader(response.GetResponseStream()))
                throw new Exception("Сервер: "+(int)response.StatusCode+" "+reader.ReadToEnd());
            throw;
        }
    }
    public static string UploadVoice(string file,string person) {
        if(person.Trim().Length<2)throw new Exception("Введите имя сотрудника.");
        Dictionary<string,object> settings;lock(Gate)settings=Read(Settings);
        if(!settings.ContainsKey("secret"))throw new Exception("Сначала подключите сервер.");
        return UploadVoiceWithSettings(settings,file,person);
    }
    internal static string UploadVoiceWithSettings(Dictionary<string,object> settings,string file,string person) {
        Request(settings,"/api/state",null);
        var accepted=Json.Deserialize<Dictionary<string,object>>(Request(settings,"/api/voices/upload",file,person.Trim()));
        object expected;accepted.TryGetValue("file",out expected);
        for(int i=0;i<120;i++) {
            System.Threading.Thread.Sleep(2000);
            var state=Json.Deserialize<Dictionary<string,object>>(Request(settings,"/api/state",null));
            var rec=(Dictionary<string,object>)state["recording"];
            if(expected==null || !Object.Equals(rec["file"],expected))return "Образец принят. Проверьте результат в разделе «Голоса» сайта.";
            if((string)rec["status"]=="error")throw new Exception((string)rec["error"]);
            if((string)rec["status"]=="complete")return "Голос сохранён: "+person.Trim();
        }
        return "Образец ещё обрабатывается. Результат появится в разделе «Голоса» сайта.";
    }
    public static void Enqueue(string session) {
        lock(Gate) {
            if(!File.Exists(Path.Combine(session,"delivery.json")))
                Save(Path.Combine(session,"delivery.json"),new {status="pending",error=""});
        }
    }
    public static string Package(string folder) {
string bundle=Path.Combine(folder,"recording.meeting");
    if(!File.Exists(bundle)) {
        var manifest=Read(Path.Combine(folder,"session.json"));
        if((string)manifest["status"]!="stopped"&&(string)manifest["status"]!="capture_error")throw new Exception("Сначала завершите запись.");
        string temp=bundle+".tmp";
        using(var stream=new FileStream(temp,FileMode.Create))using(var archive=new ZipArchive(stream,ZipArchiveMode.Create)) {
            archive.CreateEntryFromFile(Path.Combine(folder,"session.json"),"session.json");
            foreach(var source in (System.Collections.IEnumerable)manifest["sources"]) {
                if(source==null)continue;
                var s=(Dictionary<string,object>)source;
                foreach(var part in (System.Collections.IEnumerable)s["segments"]) {
                    string name=(string)((Dictionary<string,object>)part)["file"];
                    if(name!=Path.GetFileName(name)||!name.EndsWith(".wav"))throw new Exception("Неверное имя аудиофайла");
                    archive.CreateEntryFromFile(Path.Combine(folder,name),name,CompressionLevel.Fastest);
                }
            }
        }
        File.Move(temp,bundle);
    }
        return bundle;
    }
    public static string RunOnce(string storage) {
        lock(WorkerGate) {
            if(!File.Exists(Settings))return "Укажите сервер для автоматической отправки.";
            Dictionary<string,object> settings;
            lock(Gate)settings=Read(Settings);
            foreach(string folder in Directory.GetDirectories(storage)) {
                string journal=Path.Combine(folder,"delivery.json");
                if(!File.Exists(journal))continue;
                var state=Read(journal);
                if((string)state["status"]=="accepted")continue;
                try {
                    Request(settings,"/api/state",null);
                    string bundle=Package(folder);
                    var reply=Json.Deserialize<Dictionary<string,object>>(Request(settings,"/api/upload",bundle));
                    string id=reply.ContainsKey("id")?reply["id"] as string:null;
                    if(id==null||!System.Text.RegularExpressions.Regex.IsMatch(id,"^[a-f0-9]{64}$"))throw new Exception("Неверный ответ сервера");
                    Save(journal,new {status="accepted",job_id=id,server=settings["server"],error=""});
                    return "Встреча принята сервером в очередь. Результат появится на сайте.";
                }catch(Exception ex) {
                    Save(journal,new {status="pending",error=ex.Message});
                    return "Запись сохранена на ПК; отправка будет повторена: "+ex.Message;
                }
            }
            return null;
        }
    }
}
