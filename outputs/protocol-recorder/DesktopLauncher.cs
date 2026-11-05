using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
class DesktopLauncher {
 [STAThread] static void Main(){
 string dir=AppDomain.CurrentDomain.BaseDirectory;
 try {
 Process.Start(new ProcessStartInfo(Path.Combine(dir,@"audio-runtime\pythonw.exe"),"-c \"import runpy;runpy.run_path('launch.py',run_name='__main__')\""){WorkingDirectory=dir,UseShellExecute=false});
 }catch(Exception e){MessageBox.Show(e.Message,"Протокол");}
 }
}
