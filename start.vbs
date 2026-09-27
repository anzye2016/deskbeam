' DeskBeam launcher (UAC elevation + hidden window)
' Kills old instance before starting
Dim fso, scriptDir, shell
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Kill old instance by port (read port from config.json, default 8769)
Dim port : port = "8769"
On Error Resume Next
Dim cfgText : cfgText = fso.OpenTextFile(scriptDir & "\config.json", 1).ReadAll
Dim keyPos : keyPos = InStr(cfgText, """port""")
If keyPos > 0 Then
    Dim colonPos : colonPos = InStr(keyPos, cfgText, ":")
    Dim p1 : p1 = colonPos + 1
    Dim p2 : p2 = InStr(p1, cfgText, ",")
    If p2 = 0 Then p2 = Len(cfgText) + 1
    Dim raw : raw = Trim(Mid(cfgText, p1, p2 - p1))
    raw = Replace(raw, """", "")
    raw = Replace(raw, vbCr, "")
    raw = Replace(raw, vbLf, "")
    If IsNumeric(raw) Then port = raw
End If
On Error GoTo 0
shell.Run "powershell -NoProfile -Command ""$ErrorActionPreference='SilentlyContinue'; Get-NetTCPConnection -LocalPort " & port & " -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }""", 0, False

Dim pythonw : pythonw = scriptDir & "\.venv\Scripts\pythonw.exe"
Dim serverpy : serverpy = scriptDir & "\server.py"

If Not fso.FileExists(pythonw) Then
    MsgBox "pythonw.exe not found:" & vbCrLf & pythonw, 16, "DeskBeam Error"
    WScript.Quit 1
End If
If Not fso.FileExists(serverpy) Then
    MsgBox "server.py not found:" & vbCrLf & serverpy, 16, "DeskBeam Error"
    WScript.Quit 1
End If

Dim app : Set app = CreateObject("Shell.Application")
app.ShellExecute pythonw, Chr(34) & serverpy & Chr(34), scriptDir, "runas", 0
