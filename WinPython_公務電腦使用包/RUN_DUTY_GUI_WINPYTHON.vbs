Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batchFile = fso.BuildPath(scriptDir, "RUN_DUTY_GUI_WINPYTHON.bat")

shell.CurrentDirectory = scriptDir
If WScript.Arguments.Count > 0 Then
    If WScript.Arguments(0) = "--check-update" Then
        batchFile = fso.BuildPath(scriptDir, "UPDATE_PACKAGE.bat")
        exitCode = shell.Run(Chr(34) & batchFile & Chr(34) & " --hidden", 0, True)
        If exitCode <> 0 Then
            MsgBox "Cannot open the SinpoSmart update window. Please run SETUP_WINPYTHON.bat first.", 16, "SinpoSmart"
        End If
        WScript.Quit exitCode
    End If
End If
shell.Run Chr(34) & batchFile & Chr(34), 0, False
