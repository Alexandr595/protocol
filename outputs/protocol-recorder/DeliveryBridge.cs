using System;using System.Web.Script.Serialization;using System.Collections.Generic;
class DeliveryBridge{
static int Main(){Console.OutputEncoding=new System.Text.UTF8Encoding(false);var json=new JavaScriptSerializer();try{var q=json.Deserialize<Dictionary<string,object>>(Console.ReadLine());object result=null;switch((string)q["op"]){
case "settings":result=new{server=Delivery.Address,username=Delivery.Username,configured=Delivery.Configured};break;
case "update":result=UpdateClient.Run();break;
case "configure":Delivery.Configure((string)q["server"],(string)q["username"],(string)q["password"]);result="Подключено. Вход сохранён.";break;
case "check":Delivery.CheckSaved();result="Сохранённый вход восстановлен.";break;
case "package":result=Delivery.Package((string)q["folder"]);break;
case "enqueue":Delivery.Enqueue((string)q["folder"]);result="Запись ожидает отправки.";break;
case "queue":result=Delivery.RunOnce((string)q["storage"]);break;
case "voice":result=Delivery.UploadVoice((string)q["file"],(string)q["name"]);break;
default:throw new Exception("Unknown operation");}
Console.WriteLine(json.Serialize(new{ok=true,result=result}));return 0;
}catch(Exception ex){Console.WriteLine(json.Serialize(new{ok=false,error=ex.Message}));return 1;}}}
