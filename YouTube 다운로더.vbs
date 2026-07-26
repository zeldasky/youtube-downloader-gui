' YouTube 다운로더 실행기 - 콘솔 창 없이 GUI만 띄운다.
Option Explicit
Dim fso, shell, here, pyw, script

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

here = fso.GetParentFolderName(WScript.ScriptFullName)
script = fso.BuildPath(here, "ytdl_gui.py")

pyw = "C:\Python314\pythonw.exe"
If Not fso.FileExists(pyw) Then
    pyw = "pythonw.exe"
End If

If Not fso.FileExists(script) Then
    MsgBox "ytdl_gui.py 파일을 찾을 수 없습니다:" & vbCrLf & script, 16, "YouTube 다운로더"
    WScript.Quit 1
End If

shell.CurrentDirectory = here
shell.Run """" & pyw & """ """ & script & """", 0, False
