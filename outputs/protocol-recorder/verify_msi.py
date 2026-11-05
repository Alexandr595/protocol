"""Check every embedded MSI payload file against this build, without installing it."""
import ctypes as C, hashlib, msilib as m,sys,subprocess,tempfile
from pathlib import Path
root=Path(__file__).resolve().parent
msi=Path(sys.argv[1]).resolve()
db=m.OpenDatabase(str(msi),m.MSIDBOPEN_READONLY)
def rows(q,n):
    view=db.OpenView(q);view.Execute(None);result=[]
    while (row:=view.Fetch()):result.append(tuple(row.GetString(i+1) for i in range(n)))
    return result
paths=dict((i,(p,d.split('|')[-1])) for i,p,d in rows("SELECT `Directory`, `Directory_Parent`, `DefaultDir` FROM `Directory`",3))
def rel(k):
    if k=="INSTALLDIR":return Path()
    parent,name=paths[k];return rel(parent)/name
comps=dict(rows("SELECT `Component`, `Directory_` FROM `Component`",2))
files=rows("SELECT `File`, `Component_`, `FileName` FROM `File`",3)
assert rows("SELECT `Shortcut` FROM `Shortcut`",1)==[("StartProtocol",)]
dll=C.windll.msi
def handle(fn,*args):
    h=C.c_uint();code=fn(*args,C.byref(h));assert not code,code;return h
h=handle(dll.MsiOpenDatabaseW,str(msi),None)
v=handle(dll.MsiDatabaseOpenViewW,h,"SELECT `Data` FROM `_Streams` WHERE `Name`='payload'")
assert not dll.MsiViewExecute(v,0)
rec=handle(dll.MsiViewFetch,v)
import uuid
tmp=Path(tempfile.gettempdir())/('msi-payload-'+uuid.uuid4().hex);tmp.mkdir()
if tmp.is_dir():
    folder=Path(tmp);cab=folder/'payload.cab';out=folder/'files';out.mkdir()
    with cab.open('wb') as f:
        buf=C.create_string_buffer(65536)
        while True:
            count=C.c_uint(len(buf));assert not dll.MsiRecordReadStream(rec,1,buf,C.byref(count));f.write(buf.raw[:count.value])
            if count.value<len(buf):break
    for handle_id in [rec,v,h]:dll.MsiCloseHandle(handle_id)
    subprocess.run(['expand.exe','-F:*',str(cab),str(out)],check=True,stdout=subprocess.DEVNULL)
    for key,component,filename in files:
        src=root/rel(comps[component])/filename.split('|')[-1]
        assert (out/key).read_bytes()==src.read_bytes(),src
print('PASS: MSI shortcut and',len(files),'embedded files verified')

