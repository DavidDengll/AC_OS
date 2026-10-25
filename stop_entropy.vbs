' ============================================================
'  stop_entropy.vbs -- Stop background Entropy (ASCII only)
' ============================================================
Option Explicit

Dim wmi, procs, p, killed, cmdline
killed = 0

Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name='python.exe'")

For Each p In procs
    On Error Resume Next
    cmdline = p.CommandLine
    Err.Clear
    On Error GoTo 0
    If InStr(1, cmdline, "main.py", 1) > 0 Then
        WScript.Echo "  [STOP] python.exe PID=" & p.ProcessId
        p.Terminate()
        killed = killed + 1
    End If
Next

If killed > 0 Then
    WScript.Echo "  [DONE] Stopped " & killed & " Entropy process(es)."
Else
    WScript.Echo "  [INFO] No running main.py process found."
End If
