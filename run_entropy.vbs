' ============================================================
'  run_entropy.vbs -- Silent background launcher for Entropy
'
'  Double-click this file to run:  python main.py --auto
'  No console window will appear.
'
'  Stop:  double-click stop_entropy.bat
'  Note : This file is intentionally ASCII-only, because Windows
'         Script Host does not reliably parse UTF-8 source.
' ============================================================
Option Explicit

Dim fso, shell, scriptDir, pyExe, mainPy, logDir, logFile
Dim extraArgs, i, arg, cmd, rc

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

extraArgs = ""
For i = 0 To WScript.Arguments.Count - 1
    arg = WScript.Arguments(i)
    If InStr(arg, " ") > 0 Then
        extraArgs = extraArgs & " """ & arg & """"
    Else
        extraArgs = extraArgs & " " & arg
    End If
Next
If Trim(extraArgs) = "" Then extraArgs = " --auto"

mainPy = scriptDir & "\newlivingthings\main.py"

If Not fso.FileExists(mainPy) Then
    MsgBox "main.py not found:" & vbCrLf & mainPy & vbCrLf & vbCrLf & "Please put run_entropy.vbs in the AC_OS repo root.", vbCritical, "AC_OS"
    WScript.Quit 1
End If

' Prefer the py launcher, then python on PATH.
pyExe = ""
If Probe("py -3 -c ""import sys""") Then
    pyExe = "py -3"
ElseIf Probe("python -c ""import sys""") Then
    pyExe = "python"
Else
    MsgBox "Python not found." & vbCrLf & vbCrLf & "Please run setup_env.bat first.", vbCritical, "AC_OS"
    WScript.Quit 1
End If

logDir = scriptDir & "\logs"
If Not fso.FolderExists(logDir) Then fso.CreateFolder(logDir)
logFile = logDir & "\entropy_" & Stamp() & ".log"

cmd = "cmd /c cd /d """ & scriptDir & "\newlivingthings"" && " & pyExe & " """ & mainPy & """" & extraArgs & " >> """ & logFile & """ 2>&1"

shell.CurrentDirectory = scriptDir
shell.Run cmd, 0, False

WScript.Quit 0


Function Probe(cmdline)
    Dim r
    On Error Resume Next
    r = -1
    r = shell.Run("cmd /c " & cmdline & " >nul 2>&1", 0, True)
    If Err.Number <> 0 Then
        Err.Clear
        Probe = False
    Else
        Probe = (r = 0)
    End If
    On Error GoTo 0
End Function

Function Stamp()
    Dim d
    d = Now
    Stamp = Year(d) & Right("0" & Month(d), 2) & Right("0" & Day(d), 2) & "_" & Right("0" & Hour(d), 2) & Right("0" & Minute(d), 2) & Right("0" & Second(d), 2)
End Function
