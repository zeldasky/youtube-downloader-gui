' YouTube Downloader launcher - starts the GUI without a console window.
'
' NOTE: Windows Script Host reads .vbs files as ANSI (the system codepage),
' not UTF-8. Non-ASCII characters here get mis-decoded and can swallow the
' line break that follows, which breaks the script. Keep this file ASCII-only.

Option Explicit
Dim fso, shell, here, pyw, script, candidates, c

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

here = fso.GetParentFolderName(WScript.ScriptFullName)
script = fso.BuildPath(here, "ytdl_gui.py")

' Locate pythonw.exe in the usual install locations; fall back to PATH.
candidates = Array( _
    "C:\Python314\pythonw.exe", _
    "C:\Python313\pythonw.exe", _
    "C:\Python312\pythonw.exe", _
    shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe"), _
    shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"), _
    shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"))

pyw = "pythonw.exe"
For Each c In candidates
    If fso.FileExists(c) Then
        pyw = c
        Exit For
    End If
Next

If Not fso.FileExists(script) Then
    MsgBox "ytdl_gui.py not found:" & vbCrLf & script, 16, "YouTube Downloader"
    WScript.Quit 1
End If

shell.CurrentDirectory = here
shell.Run """" & pyw & """ """ & script & """", 0, False
