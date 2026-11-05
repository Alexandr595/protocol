"""Build a per-user Windows Installer package. No custom actions or elevation."""
import os,sys,uuid,msilib as m
from pathlib import Path
from msilib import schema,sequence
root=Path(__file__).resolve().parent
dest=Path(sys.argv[1]).resolve()
version="0.10.1"
guid=lambda key:"{"+str(uuid.uuid5(uuid.NAMESPACE_URL,"protocol.internal/"+key)).upper()+"}"
db=m.init_database(str(dest),schema,"Protocol",guid("product/"+version),version,"Protocol")
summary=db.GetSummaryInformation(1)
summary.SetProperty(m.PID_WORDCOUNT,10)  # compressed, long names, install without elevation
summary.Persist()
def rows(table,data):m.add_data(db,table,data)
rows("Property",[("UpgradeCode",guid("desktop/x64")),("SecureCustomProperties","PREVIOUS;NEWER")])
rows("Upgrade",[(guid("desktop/x64"),None,version,None,1,None,"PREVIOUS"),(guid("desktop/x64"),version,None,None,2,None,"NEWER")])
rows("LaunchCondition",[("NOT NEWER OR Installed","A newer version is already installed.")])
rows("InstallExecuteSequence",[(a,c,1450 if a=="RemoveExistingProducts" else i) for a,c,i in sequence.InstallExecuteSequence])
for table in ["InstallUISequence","AdminUISequence"]:rows(table,[r for r in getattr(sequence,table) if r[0] in {"FindRelatedProducts","LaunchConditions","CostInitialize","CostFinalize","FileCost","ExecuteAction"}])
rows("AdminExecuteSequence",sequence.AdminExecuteSequence)
import itertools
cab=m.CAB('payload');counter=itertools.count(1);cab.gen_id=lambda name:'File%05d'%next(counter)
feat=m.Feature(db,"Client","Protocol","Meeting capture",0);feat.set_current()
base=m.Directory(db,cab,None,str(root),"TARGETDIR","SourceDir")
local=m.Directory(db,cab,base,"","LocalAppDataFolder",".")
apps=m.Directory(db,cab,local,"","ProgramsDir","Programs")
home=m.Directory(db,cab,apps,"","INSTALLDIR","ProtocolDesktop")
menu=m.Directory(db,cab,base,"","ProgramMenuFolder",".")
desktop=m.Directory(db,cab,base,"","DesktopFolder",".")
dirs={root:home}
def folder(p):
    if p not in dirs:
        parent=folder(p.parent)
        dirs[p]=m.Directory(db,cab,parent,p.name,"D"+str(len(dirs)),parent.make_short(p.name)+"|"+p.name)
    return dirs[p]
files=[root/n for n in ["Protocol.exe","DeliveryBridge.exe","WindowsMic.exe","launch.py","recorder_app.py","capture_worker.py","portable_session.py","update-public.xml"]]
for name in ("audio-runtime","audio-packages"):
    files+=sorted(p for p in (root/name).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix!=".pyc")
for p in files:
    d=folder(p.parent)
    if not d.component:d.start_component(flags=0,keyfile=p.name,uuid=guid("component/"+str(p.parent.relative_to(root))))
    ident=d.add_file(p.name,src=str(p))
    if p.name=="Protocol.exe":
        rows("Shortcut",[("StartProtocol","ProgramMenuFolder","Protocol",d.component,"[#"+ident+"]",None,"Meeting recorder",None,None,None,None,"INSTALLDIR")])
        rows("Shortcut",[("DesktopProtocol","DesktopFolder","Protocol",d.component,"[#"+ident+"]",None,"Meeting recorder",None,None,None,None,"INSTALLDIR")])
        rows("CustomAction",[("LaunchProtocol",210,ident,None)])
        dlg=m.Dialog(db,"ProtocolReady",50,50,310,110,3,"Protocol","Open","Open","Close")
        dlg.text("Info",12,14,288,38,3,"Protocol is installed. You can also open it from your desktop or the Start menu.")
        btn=dlg.pushbutton("Open",108,72,90,20,3,"Open Protocol","Close")
        btn.event("DoAction","LaunchProtocol",ordering=1)
        btn.event("EndDialog","Return",ordering=2)
        dlg.pushbutton("Close",202,72,90,20,3,"Close","Open").event("EndDialog","Return")
        rows("InstallUISequence",[("ProtocolReady",'NOT (REMOVE~="ALL")',-1)])
cab.commit(db)
print("MSI files:",len(files))

